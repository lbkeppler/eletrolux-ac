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
        except TimeoutError as err:
            # A ClientTimeout(total=...) raises asyncio.TimeoutError (aliased to
            # the builtin TimeoutError in 3.11+), which is NOT a ClientError.
            # Wrap it with a "timed out" message so async_get_info_with_retry
            # recognizes it as retryable — the real /info endpoint times out
            # intermittently at the gateway.
            raise ElectroluxApiError(f"Request timed out for {url}") from err
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

    async def async_get_info_with_retry(
        self, appliance_id: str, *, attempts: int = 5
    ) -> dict[str, Any]:
        """Fetch /info, retrying the API's intermittent gateway failures.

        The real ``GET /{id}/info`` endpoint is flaky: it sporadically returns
        an HTTP 502/503/504 gateway error, OR a 200 body of
        ``{"message": "Endpoint request timed out"}`` (no ``capabilities`` key),
        OR a real connection timeout. All three are transient and retryable;
        real auth/4xx errors are NOT (they propagate immediately).

        Retries up to ``attempts`` times with exponential backoff capped at 30s
        (2s, 4s, 8s, 16s...). A real /info always carries ``capabilities``.
        Raises ``ElectroluxApiError`` after exhaustion so the caller can fall
        back to its last-good cache. ``asyncio.sleep`` is used so tests patch it.
        """
        last_error: ElectroluxApiError | None = None
        for attempt in range(attempts):
            try:
                info = await self.async_get_info(appliance_id)
            except ElectroluxApiError as err:
                # Retry gateway/timeout failures; propagate auth and real 4xx.
                if isinstance(err, ElectroluxAuthError) or not _is_retryable(err):
                    raise
                last_error = err
                _LOGGER.debug(
                    "GET /info attempt %d/%d for %s failed (%s); retrying",
                    attempt + 1, attempts, appliance_id, err,
                )
            else:
                if not _is_timeout_body(info):
                    return info
                last_error = ElectroluxApiError(
                    f"/info for {appliance_id} timed out (body)"
                )

            if attempt < attempts - 1:
                await asyncio.sleep(min(2 ** (attempt + 1), 30))

        raise ElectroluxApiError(
            f"/info for {appliance_id} failed after {attempts} attempts"
        ) from last_error

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


# 502/503/504 are gateway/proxy errors — transient, worth retrying. 500 is a
# real server error and is NOT retried (it usually means a genuine failure).
_RETRYABLE_STATUSES = frozenset({502, 503, 504})


def _is_timeout_message(message: str) -> bool:
    """True if a message looks like the API's gateway-timeout text."""
    return "timed out" in message.lower()


def _is_retryable(err: "ElectroluxApiError") -> bool:
    """True if an /info error is a transient gateway/timeout worth retrying.

    The Electrolux /info endpoint is flaky and answers intermittently with a
    502/503/504 gateway error or a "timed out" message. Both are transient.
    A real 4xx (bad request/forbidden) or any other error is NOT retried.
    """
    if err.status in _RETRYABLE_STATUSES:
        return True
    return _is_timeout_message(str(err))


def _is_timeout_body(info: Any) -> bool:
    """True if an /info response is the timeout placeholder rather than real data.

    The timeout shape is a dict with NO ``capabilities`` key whose ``message``
    mentions "timed out" (case-insensitive). A real /info always carries
    ``capabilities``.
    """
    if not isinstance(info, dict):
        return False
    if "capabilities" in info:
        return False
    message = info.get("message")
    return isinstance(message, str) and _is_timeout_message(message)


async def _safe_json(resp: aiohttp.ClientResponse) -> dict[str, Any] | None:
    try:
        return await resp.json()
    except (ClientError, ValueError):
        return None
