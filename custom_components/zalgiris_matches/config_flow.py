from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_TEAM_PATH,
    DEFAULT_TEAM_PATH,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    CONF_LIVE_SCAN_INTERVAL,
    DEFAULT_LIVE_SCAN_INTERVAL,
    CONF_STORE_DAYS,
    DEFAULT_STORE_DAYS,
)


class ZalgirisMatchesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Optional(CONF_TEAM_PATH, default=DEFAULT_TEAM_PATH): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                        vol.Coerce(int), vol.Range(min=60, max=3600)
                    ),
                    vol.Optional(CONF_LIVE_SCAN_INTERVAL, default=DEFAULT_LIVE_SCAN_INTERVAL): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=120)
                    ),
                    vol.Optional(CONF_STORE_DAYS, default=DEFAULT_STORE_DAYS): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=365)
                    ),
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema)

        # Only one entry by default
        await self.async_set_unique_id(f"{DOMAIN}_default")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title="Žalgiris Matches", data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ZalgirisMatchesOptionsFlow(config_entry)


class ZalgirisMatchesOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is None:
            opts = {**self.config_entry.data, **self.config_entry.options}
            schema = vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(
                        vol.Coerce(int), vol.Range(min=60, max=3600)
                    ),
                    vol.Optional(CONF_LIVE_SCAN_INTERVAL, default=opts.get(CONF_LIVE_SCAN_INTERVAL, DEFAULT_LIVE_SCAN_INTERVAL)): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=120)
                    ),
                    vol.Optional(CONF_STORE_DAYS, default=opts.get(CONF_STORE_DAYS, DEFAULT_STORE_DAYS)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=365)
                    ),
                }
            )
            return self.async_show_form(step_id="init", data_schema=schema)

        return self.async_create_entry(title="", data=user_input)
