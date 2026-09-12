"""The IRHub integration.

MVP方針:
  - 1つのconfig entry = 1つのESPHome IRHubノード(remoteエンティティ1個)。
  - ESPHomeノードとの紐付けは `device_slug` (=ESPHomeのYAMLで設定した `name`)
    をユーザーに手入力してもらうだけの最小構成(config_flow.py参照)。
  - 学習済みコードの永続化はHomeAssistantのStorageヘルパー経由で
    `.storage/` にJSONとして保存する(remote.py参照)。ESP32側は
    ステートレス(何も保存しない)。
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = ["remote"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up IRHub from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
