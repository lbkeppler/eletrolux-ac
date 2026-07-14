"""Coordinator and pure helpers for Electrolux AC."""
from __future__ import annotations

import copy
from typing import Any

from .const import CONNECTION_CONNECTED  # noqa: F401  (used by coordinator class later)
from .models import ApplianceData


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
