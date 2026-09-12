"""Remote platform for IRHub.

ESPHome IRHubノード1台につき `remote` エンティティを1つ作る。

- 送信 (`async_send_command`): 学習済みコードをStorageから引いて、
  ESPHome側のカスタムサービス `esphome.<device_slug>_send_raw` を呼ぶ。
- 学習 (`async_learn_command`): `esphome.<device_slug>_ir_raw_received`
  イベントを一定時間待ち受け、最初に届いた生タイミングをコマンド名で保存する。
- 保存先: HAのStorageヘルパー経由で `.storage/irhub_codes_<device_slug>` に
  JSONとして永続化。ESP32側には何も保存しない。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the IRHub remote entity for this config entry."""
    device_slug: str = entry.data[CONF_DEVICE_SLUG]
    store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{device_slug}")
    async_add_entities([IRHubRemote(device_slug, store)])


class IRHubRemote(RemoteEntity):
    """Generic learning IR remote backed by one ESPHome IRHub node."""

    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND
    _attr_should_poll = False

    def __init__(self, device_slug: str, store: Store) -> None:
        self._device_slug = device_slug
        self._store = store
        self._codes: dict[str, str] = {}
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

    async def async_added_to_hass(self) -> None:
        """Load previously learned codes from storage."""
        data = await self._store.async_load()
        self._codes = data or {}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more previously-learned commands."""
        for name in command:
            raw = self._codes.get(name)
            if raw is None:
                _LOGGER.warning("Unknown IRHub command '%s', skipping", name)
                continue
            data = [int(v) for v in raw.split(",")]
            await self.hass.services.async_call(
                "esphome",
                self._send_service,
                {"data": data},
                blocking=True,
            )

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn one or more commands by waiting for the device's IR-received event."""
        commands: Iterable[str] = kwargs.get("command", [])
        timeout: int = kwargs.get("timeout", DEFAULT_LEARN_TIMEOUT)

        for name in commands:
            _LOGGER.info(
                "IRHub: '%s' の学習を開始。%d秒以内にリモコンのボタンを押してください",
                name,
                timeout,
            )
            raw = await self._await_next_raw_code(timeout)
            if raw is None:
                raise TimeoutError(
                    f"'{name}' の学習がタイムアウトしました"
                    f"({timeout}秒以内にIR信号を受信できませんでした)"
                )
            self._codes[name] = raw
            await self._store.async_save(self._codes)
            _LOGGER.info(
                "IRHub: '%s' を学習・保存しました(%d pulses)",
                name,
                len(raw.split(",")),
            )

    async def _await_next_raw_code(self, timeout: int) -> str | None:
        """Wait for the next raw-IR event fired from the ESPHome node."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()

        @callback
        def _handle_event(event: Event) -> None:
            if not future.done():
                future.set_result(event.data["raw"])

        remove_listener = self.hass.bus.async_listen(self._learn_event_name, _handle_event)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            remove_listener()
