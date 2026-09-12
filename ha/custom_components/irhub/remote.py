"""Remote platform for IRHub.

ESPHome IRHubノード1台につき `remote` エンティティを1つ作る。

- 送信 (`async_send_command`): 学習済みコードをStorageから引いて、
  ESPHome側のカスタムサービス `esphome.<device_slug>_send_raw` を呼ぶ。
- 学習 (`async_learn_command`): `esphome.<device_slug>_ir_raw_received`
  イベントを一定時間待ち受け、届いた生タイミングをコマンド名で保存する。
- マルチフレーム対応: DaikinなどのエアコンリモコンはESPHomeの
  `remote_receiver`の`idle:`判定(既定10ms)より長いギャップを挟んで
  複数の赤外線バーストを1回の操作で送ってくることがあり、その場合
  `on_raw`イベントが1回の操作につき複数回発火する。これを1つの複合
  コマンドとして学習・再送するため、コードは常に「フレーム(生データ
  文字列)のリスト」として保存する(単一フレームのリモコンならリストの
  要素数が1になるだけ)。
- 保存先: HAのStorageヘルパー経由で `.storage/irhub_codes_<device_slug>` に
  JSONとして永続化。ESP32側には何も保存しない。
- 削除・リネーム: `remote`ドメインに標準の削除/リネーム機能が無いため、
  カスタムサービス `irhub.delete_command` / `irhub.rename_command` を
  entity serviceとして追加している(services.yaml参照)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

import voluptuous as vol

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DEVICE_SLUG,
    DEFAULT_LEARN_TIMEOUT,
    DOMAIN,
    EVENT_IR_RAW_RECEIVED_SUFFIX,
    SERVICE_SEND_RAW_SUFFIX,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_DELETE_COMMAND = "delete_command"
SERVICE_RENAME_COMMAND = "rename_command"

# 1フレーム目が届いた後、これより短い間隔で次のフレームが届く限り
# 「同じ操作の続き」とみなして拾い続ける(Daikin等のマルチフレーム対策)。
# 実際のフレーム間ギャップは数十ms程度と見られるが、余裕を持たせてある。
FRAME_GATHER_WINDOW = 0.5  # seconds
# フレーム間の送信間隔(送信側)。受信側と同様、多少の間隔を空けて送る。
FRAME_SEND_GAP = 0.03  # seconds


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the IRHub remote entity for this config entry."""
    device_slug: str = entry.data[CONF_DEVICE_SLUG]
    store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{device_slug}")
    async_add_entities([IRHubRemote(device_slug, store)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_DELETE_COMMAND,
        {vol.Required("command"): str},
        "async_delete_command",
    )
    platform.async_register_entity_service(
        SERVICE_RENAME_COMMAND,
        {vol.Required("old_name"): str, vol.Required("new_name"): str},
        "async_rename_command",
    )


def _as_frames(value: list[str] | str) -> list[str]:
    """Normalize a stored code value to a list of frames.

    旧フォーマット(単一フレームの生文字列)との後方互換用。
    """
    if isinstance(value, str):
        return [value]
    return list(value)


class IRHubRemote(RemoteEntity):
    """Generic learning IR remote backed by one ESPHome IRHub node."""

    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND
    _attr_should_poll = False

    def __init__(self, device_slug: str, store: Store) -> None:
        self._device_slug = device_slug
        self._store = store
        self._codes: dict[str, list[str] | str] = {}
        self._attr_unique_id = f"{DOMAIN}_{device_slug}"
        self._attr_name = f"IRHub {device_slug}"
        self._attr_is_on = True
        # ESPHome側YAMLで直接書いたイベント名(esphome/irhub-common.yamlの
        # on_raw -> homeassistant.event)はリテラル文字列なのでハイフンそのまま。
        self._learn_event_name = f"esphome.{device_slug}{EVENT_IR_RAW_RECEIVED_SUFFIX}"
        # 一方、HA側の`esphome`統合が`api:services:`をサービスとして公開する際は
        # デバイス名をslugify(ハイフン等を"_"に変換)した名前になるため、
        # device_slugにハイフンが含まれる場合はここで変換する。
        self._send_service = f"{device_slug.replace('-', '_')}{SERVICE_SEND_RAW_SUFFIX}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the list of learned command names for dashboards/scripts."""
        return {"commands": sorted(self._codes)}

    async def async_added_to_hass(self) -> None:
        """Load previously learned codes from storage."""
        data = await self._store.async_load()
        self._codes = data or {}
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more previously-learned commands."""
        for name in command:
            stored = self._codes.get(name)
            if stored is None:
                _LOGGER.warning("Unknown IRHub command '%s', skipping", name)
                continue
            frames = _as_frames(stored)
            for i, frame in enumerate(frames):
                data = [int(v) for v in frame.split(",")]
                await self.hass.services.async_call(
                    "esphome",
                    self._send_service,
                    {"data": data},
                    blocking=True,
                )
                if i < len(frames) - 1:
                    await asyncio.sleep(FRAME_SEND_GAP)

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn one or more commands by waiting for the device's IR-received event(s)."""
        commands: Iterable[str] = kwargs.get("command", [])
        timeout: int = kwargs.get("timeout", DEFAULT_LEARN_TIMEOUT)

        for name in commands:
            _LOGGER.info(
                "IRHub: '%s' の学習を開始。%d秒以内にリモコンのボタンを押してください",
                name,
                timeout,
            )
            frames = await self._collect_raw_frames(timeout)
            if frames is None:
                raise TimeoutError(
                    f"'{name}' の学習がタイムアウトしました"
                    f"({timeout}秒以内にIR信号を受信できませんでした)"
                )
            self._codes[name] = frames
            await self._store.async_save(self._codes)
            self.async_write_ha_state()  # commands属性(ダッシュボードのドロップダウン等)を更新
            total_pulses = sum(len(f.split(",")) for f in frames)
            _LOGGER.info(
                "IRHub: '%s' を学習・保存しました(%dフレーム, 計%d pulses)",
                name,
                len(frames),
                total_pulses,
            )

    async def async_delete_command(self, command: str) -> None:
        """Delete a previously-learned command (service: irhub.delete_command)."""
        if command not in self._codes:
            _LOGGER.warning("IRHub: '%s' は存在しないので削除できません", command)
            return
        del self._codes[command]
        await self._store.async_save(self._codes)
        self.async_write_ha_state()
        _LOGGER.info("IRHub: '%s' を削除しました", command)

    async def async_rename_command(self, old_name: str, new_name: str) -> None:
        """Rename a previously-learned command (service: irhub.rename_command)."""
        if old_name not in self._codes:
            _LOGGER.warning("IRHub: '%s' は存在しないのでリネームできません", old_name)
            return
        if new_name in self._codes:
            _LOGGER.warning(
                "IRHub: '%s' は既に存在するのでリネームできません(上書き防止)", new_name
            )
            return
        self._codes[new_name] = self._codes.pop(old_name)
        await self._store.async_save(self._codes)
        self.async_write_ha_state()
        _LOGGER.info("IRHub: '%s' を '%s' にリネームしました", old_name, new_name)

    async def _collect_raw_frames(self, timeout: int) -> list[str] | None:
        """Wait for the first frame, then keep collecting frames that arrive
        in quick succession (within FRAME_GATHER_WINDOW of the previous one)
        as parts of the same logical command.

        DaikinなどのエアコンリモコンはESPHomeのidle判定より長いギャップを
        挟んで複数バーストを送ってくるため、on_rawイベントが1回の操作で
        複数回発火することがある。それらをまとめて1コマンドとして扱う。
        """
        queue: asyncio.Queue[str] = asyncio.Queue()

        @callback
        def _handle_event(event: Event) -> None:
            queue.put_nowait(event.data["raw"])

        remove_listener = self.hass.bus.async_listen(self._learn_event_name, _handle_event)
        try:
            try:
                first = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                return None
            frames = [first]

            while True:
                try:
                    frames.append(await asyncio.wait_for(queue.get(), timeout=FRAME_GATHER_WINDOW))
                except asyncio.TimeoutError:
                    break

            return frames
        finally:
            remove_listener()
