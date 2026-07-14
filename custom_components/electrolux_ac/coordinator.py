"""Coordinator and pure helpers for Electrolux AC."""
from __future__ import annotations

import asyncio
import copy
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ElectroluxApiClient,
    ElectroluxApiError,
    ElectroluxAuthError,
    ElectroluxCommandError,
)
from .const import (
    CONNECTION_CONNECTED,  # noqa: F401  (kept for helper parity/back-compat)
    DOMAIN,
    POLL_INTERVAL_MINUTES,
    PROP_APPLIANCE_STATE,
    PROP_EXECUTE_COMMAND,
    SSE_HEALTHY_SECONDS,
    SSE_RECONNECT_MAX_SECONDS,
    SSE_RECONNECT_SECONDS,
    STATE_OFF,
    STATE_RUNNING,
)
from .models import ApplianceData, ElectroluxConfigEntry

_LOGGER = logging.getLogger(__name__)


def parse_appliance(
    appliance: dict[str, Any], info: dict[str, Any], state: dict[str, Any]
) -> ApplianceData:
    """Build an ApplianceData snapshot from the three API payloads."""
    appliance_info = info.get("applianceInfo", {})
    model = appliance_info.get("model", "")
    variant = appliance_info.get("variant")
    if variant:
        model = f"{model} {variant}".strip()
    reported = state.get("properties", {}).get("reported", {})
    sw_version = reported.get("networkInterface", {}).get("swVersion")
    return ApplianceData(
        appliance_id=appliance["applianceId"],
        name=appliance.get("applianceName", appliance["applianceId"]),
        brand=appliance_info.get("brand", "Electrolux"),
        model=model,
        sw_version=sw_version,
        capabilities=info.get("capabilities", {}),
        reported=reported,
        connection_state=state.get("connectionState", "unknown"),
    )


def apply_sse_event(data: ApplianceData, event: dict[str, Any]) -> ApplianceData:
    """Return a new ApplianceData with one SSE event applied."""
    prop = event.get("property")
    value = event.get("value")
    if prop is None or value is None:
        return data

    if prop in ("connectionState", "connectivityState"):
        return ApplianceData(
            appliance_id=data.appliance_id,
            name=data.name,
            brand=data.brand,
            model=data.model,
            sw_version=data.sw_version,
            capabilities=data.capabilities,
            reported=data.reported,
            connection_state=value,
        )

    new_reported = copy.deepcopy(data.reported)
    path = prop.split("/")
    target = new_reported
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value

    return ApplianceData(
        appliance_id=data.appliance_id,
        name=data.name,
        brand=data.brand,
        model=data.model,
        sw_version=data.sw_version,
        capabilities=data.capabilities,
        reported=new_reported,
        connection_state=data.connection_state,
    )


class ElectroluxCoordinator(DataUpdateCoordinator[dict[str, ApplianceData]]):
    """Coordinates polling + SSE push for Electrolux ACs."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ElectroluxConfigEntry,
        client: ElectroluxApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=POLL_INTERVAL_MINUTES),
            always_update=False,
        )
        self.client = client
        self._appliance_ids: list[str] = []
        self._info: dict[str, dict] = {}
        self._appliance_by_id: dict[str, dict] = {}
        self._discovered = False

    async def _async_update_data(self) -> dict[str, ApplianceData]:
        try:
            if not self._discovered:
                await self._async_discover()
            result: dict[str, ApplianceData] = {}
            for aid in self._appliance_ids:
                appliance = self._appliance_by_id[aid]
                state = await self.client.async_get_state(aid)
                result[aid] = parse_appliance(appliance, self._info[aid], state)
            return result
        except ElectroluxAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ElectroluxApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_discover(self) -> None:
        appliances = await self.client.async_get_appliances()
        self._appliance_by_id = {}
        # NOTE: self._info is the last-good cache and MUST survive across
        # re-discovers — do NOT reset it here. On a transient /info timeout we
        # fall back to the previously cached capabilities rather than dropping
        # the appliance or failing setup.
        for appliance in appliances:
            aid = appliance["applianceId"]
            try:
                info = await self.client.async_get_info_with_retry(aid)
            except ElectroluxAuthError:
                # A real auth failure is not a per-appliance transient — let it
                # bubble up to become a reauth flow in _async_update_data.
                raise
            except ElectroluxApiError as err:
                cached = self._info.get(aid)
                if cached is not None:
                    _LOGGER.warning(
                        "GET /info timed out for %s (%s); reusing last-good "
                        "cached capabilities",
                        aid,
                        err,
                    )
                    self._appliance_by_id[aid] = appliance
                    # cached info already in self._info — keep it.
                    continue
                _LOGGER.warning(
                    "GET /info unavailable for %s (%s) and no cached "
                    "capabilities exist; skipping this appliance",
                    aid,
                    err,
                )
                continue

            device_type = info.get("applianceInfo", {}).get("deviceType") or ""
            is_ac = (
                appliance.get("applianceType") == "AC"
                or "AIR_CONDITIONER" in device_type
            )
            if not is_ac:
                continue
            self._appliance_by_id[aid] = appliance
            self._info[aid] = info
        self._appliance_ids = list(self._appliance_by_id)
        self._discovered = True
        if not self._appliance_ids:
            _LOGGER.warning(
                "No AC appliances found among %d appliances; types=%s",
                len(appliances),
                [a.get("applianceType") for a in appliances],
            )

    async def async_run_sse(self) -> None:
        """Long-lived SSE listen loop with exponential reconnect backoff.

        A flapping stream (e.g. the API's 1-concurrent-SSE-channel limit, or a
        server that accepts the GET then immediately EOFs) must NOT reconnect
        every ``SSE_RECONNECT_SECONDS`` forever: at 10 s that is ~17k calls/day,
        over the 5000/day free-tier quota, which would then also 429 the poll.
        So the backoff doubles each consecutive failure up to
        ``SSE_RECONNECT_MAX_SECONDS`` and only resets once the stream has stayed
        connected for ``SSE_HEALTHY_SECONDS``.
        """
        backoff = SSE_RECONNECT_SECONDS
        loop = asyncio.get_running_loop()
        consecutive_failures = 0
        while True:
            started = loop.time()
            try:
                async for event in self.client.async_iter_events():
                    self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 — reconnect on anything
                _LOGGER.debug("SSE stream error, reconnecting: %s", err)

            # If the stream stayed up long enough, treat it as healthy and reset.
            if loop.time() - started >= SSE_HEALTHY_SECONDS:
                backoff = SSE_RECONNECT_SECONDS
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    _LOGGER.warning(
                        "Electrolux SSE stream keeps dropping immediately "
                        "(%d times); backing off %ds. Check API quota / the "
                        "1-concurrent-channel limit.",
                        consecutive_failures,
                        backoff,
                    )

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            backoff = min(backoff * 2, SSE_RECONNECT_MAX_SECONDS)

    @callback
    def _handle_event(self, event: dict) -> None:
        aid = event.get("applianceId")
        if not aid or self.data is None or aid not in self.data:
            return
        new_data = dict(self.data)
        new_data[aid] = apply_sse_event(self.data[aid], event)
        # Update state and notify entities WITHOUT rescheduling the poll —
        # async_set_updated_data would reset the 5-min timer, and a chatty SSE
        # stream would then starve the reconciliation poll forever. See the
        # spec's reconciliation requirement (section 3.2).
        self.data = new_data
        self.async_update_listeners()

    async def async_send_command(
        self, appliance_id: str, command: dict
    ) -> None:
        try:
            await self.client.async_send_command(appliance_id, command)
        except ElectroluxCommandError as err:
            raise HomeAssistantError(
                f"Command rejected: {err.detail or err}"
            ) from err
        except ElectroluxApiError as err:
            raise HomeAssistantError(str(err)) from err

        if self.data is None or appliance_id not in self.data:
            return
        current = self.data[appliance_id]
        new_reported = dict(current.reported)
        for key, value in command.items():
            # executeCommand is write-only — the device never reports it, so
            # only derive applianceState from it, don't store the raw key.
            if key == PROP_EXECUTE_COMMAND:
                new_reported[PROP_APPLIANCE_STATE] = (
                    STATE_RUNNING if value == "ON" else STATE_OFF
                )
                continue
            new_reported[key] = value
        updated = ApplianceData(
            appliance_id=current.appliance_id,
            name=current.name,
            brand=current.brand,
            model=current.model,
            sw_version=current.sw_version,
            capabilities=current.capabilities,
            reported=new_reported,
            connection_state=current.connection_state,
        )
        new_data = dict(self.data)
        new_data[appliance_id] = updated
        # Same as _handle_event: push optimistically without resetting the poll.
        self.data = new_data
        self.async_update_listeners()
