"""Config flow for Nightscout Extended Alt."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_GLUCOSE_UNIT,
    CONF_TOKEN,
    DOMAIN,
    UNIT_MGDL,
    UNIT_MMOLL,
)


async def _test_url(hass: HomeAssistant, url: str, token: str) -> None:
    """Check that Nightscout responds."""
    session = async_get_clientsession(hass)
    params = {"token": token} if token else None
    async with session.get(
        f"{url.rstrip('/')}/api/v1/status.json",
        params=params,
        timeout=10,
    ) as response:
        if response.status >= 400:
            raise HomeAssistantError(f"Nightscout returned HTTP {response.status}")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input:
            url = user_input[CONF_URL].strip().rstrip("/")
            token = user_input.get(CONF_TOKEN, "").strip()
            try:
                await _test_url(self.hass, url, token)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(url.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=url,
                    data={
                        CONF_URL: url,
                        CONF_TOKEN: token,
                        CONF_GLUCOSE_UNIT: user_input[CONF_GLUCOSE_UNIT],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL): str,
                vol.Optional(CONF_TOKEN, default=""): str,
                vol.Required(
                    CONF_GLUCOSE_UNIT, default=UNIT_MMOLL
                ): vol.In([UNIT_MMOLL, UNIT_MGDL]),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
