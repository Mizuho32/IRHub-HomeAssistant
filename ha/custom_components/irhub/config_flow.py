"""Config flow for IRHub.

MVP: ESPHomeノードのslug(YAMLの `name`)を手入力してもらうだけ。
TODO(将来): 既存のESPHome統合済みデバイス一覧から選択できるようにする、
または `esphome` 統合のconfig entryを検出して自動サジェストする。
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

from .const import CONF_DEVICE_SLUG, DOMAIN


class IRHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for IRHub."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_slug = user_input[CONF_DEVICE_SLUG].strip()
            await self.async_set_unique_id(device_slug)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"IRHub ({device_slug})",
                data={CONF_DEVICE_SLUG: device_slug},
            )

        schema = vol.Schema({vol.Required(CONF_DEVICE_SLUG): str})
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
