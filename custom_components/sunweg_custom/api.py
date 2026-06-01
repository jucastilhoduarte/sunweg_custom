"""
API wrapper for the SunWEG platform.

This module abstracts the HTTP interactions with the SunWEG API. It uses
asyncio-compatible methods via aiohttp to login and fetch data for a given
photovoltaic plant (usina). The API encapsulates token handling and
automatically injects required headers on each request.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

import aiohttp

from .const import API_BASE_URL, HEADER_USER_AGENT, PORTAL_BASE_URL

_LOGGER = logging.getLogger(__name__)


class SunWegAPIError(Exception):
    """Raised when an unexpected response is returned from the API."""


class SunWegAuthError(SunWegAPIError):
    """Raised when authentication fails or the token has expired."""


AUTH_ERROR_STATUSES = {401, 403}


class SunWegAPI:
    """Asynchronous client for interacting with the SunWEG REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        token_updated_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._token: Optional[str] = token
        self._token_updated_callback = token_updated_callback

    @property
    def token(self) -> Optional[str]:
        """Return the current API token."""
        return self._token

    async def async_login(self) -> None:
        """Authenticate with the API and store the returned token.

        Raises:
            SunWegAuthError: If authentication fails.
            SunWegAPIError: If an unexpected error occurs.
        """
        if not self._username or not self._password:
            raise SunWegAuthError("Credentials are required to request a new token")

        url = f"{API_BASE_URL}/login/autenticacao"
        payload = {
            "usuario": self._username,
            "senha": self._password,
            "rememberMe": True,
            "aceito": False,
        }
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": HEADER_USER_AGENT,
            "Origin": PORTAL_BASE_URL,
            "Referer": f"{PORTAL_BASE_URL}/sign-in",
        }
        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("Authentication failed, status %s", resp.status)
                    raise SunWegAuthError(f"Authentication failed: HTTP {resp.status}")
                data: Dict[str, Any] = await resp.json()
        except aiohttp.ClientError as err:
            raise SunWegAPIError(f"Error communicating with SunWEG API: {err}") from err

        if not data.get("success") or "token" not in data:
            _LOGGER.error("Authentication response did not include a token")
            raise SunWegAuthError("Invalid credentials or unexpected response")
        self._token = str(data["token"])
        if self._token_updated_callback:
            await self._token_updated_callback(self._token)
        _LOGGER.debug("Logged in successfully, token set")

    def _auth_headers(self) -> Dict[str, str]:
        """Construct headers for authenticated API calls."""
        if not self._token:
            raise SunWegAuthError("Attempted to call API without a token")
        return {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": HEADER_USER_AGENT,
            "Origin": PORTAL_BASE_URL,
            "Referer": f"{PORTAL_BASE_URL}/",
            "X-Auth-Token-Update": self._token,
        }

    async def _get_json(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Internal helper to perform a GET request and return the parsed JSON.

        Args:
            endpoint: Path portion of the API endpoint (starting with '/').
            params: Optional dictionary of query parameters.

        Returns:
            The parsed JSON response.

        Raises:
            SunWegAuthError: If authentication is missing or the token has expired.
            SunWegAPIError: For connection problems or non-JSON responses.
        """
        url = f"{API_BASE_URL}{endpoint}"
        headers = self._auth_headers()
        try:
            async with self._session.get(url, headers=headers, params=params) as resp:
                # If unauthorized, refresh the token once and retry when credentials exist.
                if resp.status in AUTH_ERROR_STATUSES:
                    if not self._username or not self._password:
                        raise SunWegAuthError(
                            "Stored token has expired and no credentials are available"
                        )
                    _LOGGER.warning("Token appears to have expired, attempting reauthentication")
                    await self.async_login()
                    headers = self._auth_headers()
                    async with self._session.get(url, headers=headers, params=params) as retry_resp:
                        if retry_resp.status in AUTH_ERROR_STATUSES:
                            raise SunWegAuthError(
                                f"Authentication failed when fetching {endpoint}"
                            )
                        if retry_resp.status >= 400:
                            raise SunWegAPIError(
                                f"HTTP {retry_resp.status} when fetching {endpoint}"
                            )
                        try:
                            data = await retry_resp.json()
                        except aiohttp.ContentTypeError:
                            text = await retry_resp.text()
                            raise SunWegAPIError(
                                f"Unexpected content type for {endpoint}: {text[:100]}..."
                            )
                else:
                    if resp.status >= 400:
                        text = await resp.text()
                        _LOGGER.warning(
                            "SunWEG API returned HTTP %s for %s: %s",
                            resp.status,
                            endpoint,
                            text[:200],
                        )
                        raise SunWegAPIError(f"HTTP {resp.status} when fetching {endpoint}")
                    try:
                        data = await resp.json()
                    except aiohttp.ContentTypeError:
                        # API sometimes returns HTML with 500 errors; capture for debugging
                        text = await resp.text()
                        raise SunWegAPIError(
                            f"Unexpected content type for {endpoint}: {text[:100]}..."
                        )
        except aiohttp.ClientError as err:
            raise SunWegAPIError(f"Error fetching {endpoint}: {err}") from err
        except SunWegAPIError:
            raise
        except Exception as ex:
            raise SunWegAPIError(f"Unexpected response from {endpoint}: {ex}") from ex

        return data

    async def async_validate_token(self) -> None:
        """Validate the current token with a lightweight authenticated endpoint."""
        data = await self._get_json("/get/version/activate")
        if not data.get("success", True):
            raise SunWegAuthError("Session token was rejected by SunWEG")

    async def async_get_all_plants(self) -> Dict[str, Any]:
        """Retrieve a mapping of plant IDs to their names.

        Returns:
            A dictionary {id: name} for each accessible plant.
        """
        params = {
            "usina": "",
            "id": "",
            "situacao": "null",
            "limite": 100,
            "quantidade": 0,
            "paginaAtual": 1,
            "agrupado": "false",
            "gettotalizadores": "false",
        }
        data = await self._get_json("/getdadosresumo", params=params)
        plants = {}
        if data.get("success"):
            for plant in data.get("usinas", []):
                pid = plant.get("id")
                name = plant.get("nome")
                if pid is not None and name is not None:
                    plants[str(pid)] = name
        return plants

    async def async_get_viewresumov2(self, plant_id: str) -> Dict[str, Any]:
        """Fetch detailed plant data from the viewresumov2 endpoint.

        Args:
            plant_id: Identifier of the plant (usina).

        Returns:
            A dictionary containing detailed plant data, including the
            ``ultimaleitura`` timestamp of the most recent inverter reading.
        """
        data = await self._get_json(
            "/viewresumov2", params={"id": plant_id, "agrupado": "false"}
        )
        if not data.get("success"):
            raise SunWegAPIError(
                f"Failed to fetch viewresumov2 for plant {plant_id}: {data}"
            )
        return data
