"""
Config flow for the SunWEG integration.

This module manages the UI configuration steps when a user adds the SunWEG
integration through Home Assistant's user interface. It collects user
credentials, validates them against the remote API, and lets the user
select which photovoltaic plant they wish to monitor.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import (  # type: ignore[attr-defined]
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_AUTH_TOKEN,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
)
from .api import SunWegAPI, SunWegAuthError, SunWegAPIError

_LOGGER = logging.getLogger(__name__)


def _normalize_auth_token(value: str) -> str:
    """Accept common copied token formats and return only the JWT value."""
    token = value.strip().strip('"').strip("'")
    if not token:
        return ""

    jwt_match = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
    if jwt_match:
        return jwt_match.group(0)

    lowered = token.lower()
    for prefix in ("x-auth-token-update:", "authorization:", "bearer "):
        if lowered.startswith(prefix):
            token = token[len(prefix):].strip().strip('"').strip("'")
            break
    return token


class SunWegConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SunWEG."""

    VERSION = 1

    def __init__(self) -> None:
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._auth_token: Optional[str] = None
        self._api: Optional[SunWegAPI] = None
        self._plants: Dict[str, str] = {}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step where the user enters credentials."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._username = (user_input.get(CONF_USERNAME) or "").strip() or None
            self._password = user_input.get(CONF_PASSWORD) or None
            raw_auth_token = user_input.get(CONF_AUTH_TOKEN) or ""
            self._auth_token = _normalize_auth_token(raw_auth_token) or None

            if not self._auth_token and not (self._username and self._password):
                errors["base"] = "missing_auth"
            else:
                session = aiohttp_client.async_get_clientsession(self.hass)
                self._api = SunWegAPI(
                    session,
                    self._username,
                    self._password,
                    token=self._auth_token,
                )
                try:
                    if not self._auth_token:
                        await self._api.async_login()
                        self._auth_token = self._api.token
                    else:
                        await self._api.async_validate_token()
                    # Fetch available plants to determine whether we need a secondary step
                    self._plants = await self._api.async_get_all_plants()
                    # If there are no plants accessible, abort
                    if not self._plants:
                        return self.async_abort(reason="no_plants")
                    # If only one plant, skip plant selection
                    if len(self._plants) == 1:
                        plant_id, plant_name = next(iter(self._plants.items()))
                        return await self._create_entry(plant_id, plant_name)
                    # Otherwise, continue to plant selection step
                    return await self.async_step_select_plant()
                except SunWegAuthError:
                    errors["base"] = "auth"
                except SunWegAPIError:
                    errors["base"] = "cannot_connect"
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected error: %s", err)
                    errors["base"] = "unknown"

        # Show the credentials form to the user
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_AUTH_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_select_plant(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Ask the user to select which plant to configure."""
        if user_input is not None:
            plant_id = user_input[CONF_PLANT_ID]
            plant_name = self._plants.get(plant_id, plant_id)
            return await self._create_entry(plant_id, plant_name)

        # Present a dropdown selector with all available plants
        options = list(self._plants.keys())
        selector = SelectSelector(
            SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
        )
        data_schema = vol.Schema({vol.Required(CONF_PLANT_ID): selector})
        return self.async_show_form(
            step_id="select_plant",
            data_schema=data_schema,
        )

    async def _create_entry(self, plant_id: str, plant_name: str) -> FlowResult:
        """Create the configuration entry after collecting all information."""
        title = f"SunWEG {plant_name}"
        return self.async_create_entry(
            title=title,
            data={
                CONF_USERNAME: self._username or "",
                CONF_PASSWORD: self._password or "",
                CONF_AUTH_TOKEN: self._auth_token or "",
                CONF_PLANT_ID: plant_id,
                CONF_PLANT_NAME: plant_name,
            },
        )
