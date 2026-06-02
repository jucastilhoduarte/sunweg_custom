"""
The top-level initialization for the SunWEG integration.

This file sets up the integration within Home Assistant, managing the
communication with the remote API via an update coordinator and exposing
sensor entities for energy production, power and other metrics.

Timestamp note: the SunWEG API returns the inverter's last-reading timestamp
with a misleading "GMT" suffix (e.g. "Tue, 02 Jun 2026 08:59:19 GMT"). The
time is actually in the plant's local timezone, which the same API response
provides as the integer field ``plant_tz`` (hours offset from UTC, e.g. -3).
We discard the "GMT" label and attach the correct offset so HA stores the
right UTC-equivalent value.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import SunWegAPI, SunWegAPIError, SunWegAuthError
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_AUTH_TOKEN,
    CONF_PLANT_ID,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SunWEG integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]
    auth_token: str = entry.data.get(CONF_AUTH_TOKEN, "")
    plant_id: str = entry.data[CONF_PLANT_ID]

    session = aiohttp_client.async_get_clientsession(hass)

    async def async_store_token(token: str) -> None:
        """Persist refreshed tokens so Home Assistant restarts reuse them."""
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_AUTH_TOKEN: token,
            },
        )

    api = SunWegAPI(
        session,
        username or None,
        password or None,
        token=auth_token or None,
        token_updated_callback=async_store_token,
    )
    try:
        # Reuse a stored/manual token when available. If only credentials were
        # configured, request and persist a fresh token.
        if not auth_token:
            await api.async_login()
    except SunWegAuthError as err:
        _LOGGER.error("SunWEG authentication error: %s", err)
        raise ConfigEntryNotReady from err
    except SunWegAPIError as err:
        _LOGGER.error("SunWEG API communication error: %s", err)
        raise ConfigEntryNotReady from err

    async def async_update_data() -> Dict[str, Any]:
        """Fetch the latest data from SunWEG for the configured plant."""
        try:
            data = await api.async_get_viewresumov2(plant_id)
            # Parse the inverter's last-reading timestamp into a
            # timezone-aware datetime.  The API labels the value as "GMT" but
            # the actual offset is given by the plant_tz field (integer hours,
            # e.g. -3 for BRT).  We strip the bogus "GMT" suffix and replace
            # it with the real offset so HA receives the correct UTC time.
            ul_raw = data.get("ultimaleitura")
            if ul_raw:
                try:
                    plant_tz_hours = int(data.get("plant_tz") or 0)
                    tz = timezone(timedelta(hours=plant_tz_hours))
                    raw_no_tz = ul_raw.rsplit(" ", 1)[0]  # strip trailing "GMT"
                    naive_dt = datetime.strptime(raw_no_tz, "%a, %d %b %Y %H:%M:%S")
                    data["_ultimaleitura_dt"] = naive_dt.replace(tzinfo=tz)
                except Exception:  # pylint: disable=broad-except
                    data["_ultimaleitura_dt"] = None
            return data
        except SunWegAuthError as err:
            # Authentication error implies token expiry; raise UpdateFailed to trigger a retry
            _LOGGER.warning("Authentication failure during update: %s", err)
            raise UpdateFailed("Authentication failure") from err
        except SunWegAPIError as err:
            raise UpdateFailed(f"API error: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"SunWEG Data ({plant_id})",
        update_method=async_update_data,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )

    # Fetch initial data to validate connection
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "plant_id": plant_id,
    }

    # Forward setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
