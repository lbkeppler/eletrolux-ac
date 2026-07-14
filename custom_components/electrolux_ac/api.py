"""Electrolux Group Developer API client."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientTimeout

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.developer.electrolux.one"
_APPLIANCES = f"{BASE_URL}/api/v1/appliances"
_INFO = f"{BASE_URL}/api/v1/appliances/{{id}}/info"
_STATE = f"{BASE_URL}/api/v1/appliances/{{id}}/state"
_COMMAND = f"{BASE_URL}/api/v1/appliances/{{id}}/command"
_LIVESTREAM = f"{BASE_URL}/api/v1/configurations/livestream"
_REFRESH = f"{BASE_URL}/api/v1/token/refresh"


@dataclass(frozen=True)
class Tokens:
    """A JWT access/refresh pair."""

    access_token: str
    refresh_token: str


class ElectroluxApiError(Exception):
    """Generic API failure."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ElectroluxAuthError(ElectroluxApiError):
    """Credentials are invalid or the refresh failed."""


class ElectroluxCommandError(ElectroluxApiError):
    """A command was rejected (HTTP 406)."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message, status=406)
        self.detail = detail


class ElectroluxApiClient:
    """Thin async client over the Electrolux Developer API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        access_token: str,
        refresh_token: str,
        token_updated_cb: Callable[[Tokens], None] | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_updated_cb = token_updated_cb
        self._refresh_lock = asyncio.Lock()

    @property
    def tokens(self) -> Tokens:
        return Tokens(self._access_token, self._refresh_token)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_retry: bool = True,
    ) -> Any:
        try:
            async with self._session.request(
                method, url, headers=self._headers(), json=json_body,
                timeout=ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401 and allow_retry:
                    await self._async_refresh()
                    return await self._request(
                        method, url, json_body=json_body, allow_retry=False
                    )
                if resp.status in (200, 202, 204):
                    if resp.status == 204:
                        return None
                    # Do not read resp.content_length — the test mock lacks it
                    # and real aiohttp reports None for chunked/unset bodies.
                    text = await resp.text()
                    return json.loads(text) if text else None
                if resp.status == 406:
                    body = await _safe_json(resp)
                    raise ElectroluxCommandError(
                        "Command validation failed",
                        detail=(body or {}).get("detail"),
                    )
                if resp.status == 401:
                    # 401 that survived the retry above → credentials are dead.
                    raise ElectroluxAuthError(
                        "Unauthorized (401)", status=401
                    )
                # 403 is a per-resource forbidden, NOT an auth failure — let it
                # become UpdateFailed in the coordinator, not a reauth flow.
                raise ElectroluxApiError(
                    f"API error {resp.status} for {url}", status=resp.status
                )
        except ClientError as err:
            raise ElectroluxApiError(f"Connection error: {err}") from err

    async def _async_refresh(self) -> None:
        # Double-checked locking: if two concurrent requests both 401, only the
        # first refreshes; the second sees the token already rotated and returns,
        # then retries with the fresh token (headers are re-read on retry).
        snapshot = self._access_token
        async with self._refresh_lock:
            if self._access_token != snapshot:
                return
            try:
                async with self._session.post(
                    _REFRESH,
                    headers={"x-api-key": self._api_key, "Accept": "application/json"},
                    json={"refreshToken": self._refresh_token},
                    timeout=ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise ElectroluxAuthError(
                            f"Token refresh failed ({resp.status})", status=resp.status
                        )
                    data = await resp.json()
            except ClientError as err:
                raise ElectroluxAuthError(f"Token refresh error: {err}") from err

            self._access_token = data["accessToken"]
            self._refresh_token = data["refreshToken"]
            if self._token_updated_cb is not None:
                self._token_updated_cb(Tokens(self._access_token, self._refresh_token))

    async def async_get_appliances(self) -> list[dict[str, Any]]:
        return await self._request("GET", _APPLIANCES)

    async def async_get_info(self, appliance_id: str) -> dict[str, Any]:
        return await self._request("GET", _INFO.format(id=appliance_id))

    async def async_get_state(self, appliance_id: str) -> dict[str, Any]:
        return await self._request("GET", _STATE.format(id=appliance_id))

    async def async_send_command(
        self, appliance_id: str, command: dict[str, Any]
    ) -> None:
        await self._request(
            "PUT", _COMMAND.format(id=appliance_id), json_body=command
        )

    async def async_get_livestream_config(self) -> dict[str, Any]:
        return await self._request("GET", _LIVESTREAM)

    async def async_iter_events(self) -> AsyncIterator[dict[str, Any]]:
        config = await self.async_get_livestream_config()
        url = config["url"]
        async with self._session.get(
            url,
            headers=self._headers(),
            # sock_read=120 is the keepalive guard: a half-open/stalled stream
            # raises ServerTimeoutError after 120s so the coordinator reconnects.
            timeout=ClientTimeout(total=None, sock_connect=10, sock_read=120),
        ) as resp:
            if resp.status == 401:
                await self._async_refresh()
                raise ElectroluxApiError("SSE auth expired; reconnect")
            if resp.status != 200:
                raise ElectroluxApiError(
                    f"SSE connect failed ({resp.status})", status=resp.status
                )
            data_buf: list[str] = []
            async for raw in resp.content:
                line = raw.decode(errors="replace").strip()
                if line.startswith("data:"):
                    data_buf.append(line[len("data:"):].strip())
                elif line == "":
                    if not data_buf:
                        continue
                    payload = "".join(data_buf)
                    data_buf = []
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        _LOGGER.debug("Bad SSE payload: %s", payload)


async def _safe_json(resp: aiohttp.ClientResponse) -> dict[str, Any] | None:
    try:
        return await resp.json()
    except (ClientError, ValueError):
        return None
