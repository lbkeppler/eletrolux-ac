"""Pure capability classifier for Electrolux/Frigidaire appliances.

This module is intentionally free of Home Assistant imports so it can be
unit-tested directly against real ``/info`` capability payloads. It answers one
question per capability: *what kind of entity (if any) should this become?* —
driven entirely by the capability's STRUCTURE and ACCESS, never by hardcoded
per-model name lists.

The discriminators (in the order the plan mandates):

1. Names climate owns (``CLIMATE_CONSUMED``) are handed to the bespoke climate
   entity, not turned into generic controls.
2. ``constant`` access, ``alert`` type, and ``hCPN_*`` bookkeeping caps are noise.
3. ``write`` access caps (executeCommand, cleanFilterAlertReset) are actions with
   no readable state — nothing to surface.
4. A non-empty ``values`` map is checked BEFORE ``min``/``max`` so a capability
   like ``flapPosition`` (``type: number`` yet carrying ``POSITION_*`` values)
   routes to a SELECT, not a NUMBER.
5. A numeric range (``min``/``max``, no ``values``) becomes a NUMBER (readwrite)
   or a measurement SENSOR (read).
6. Anything left (e.g. a bare read-only string with no values or range) is
   ignored — there is no meaningful generic entity for it.

``access == "read"`` never yields a control: it is a SENSOR or BINARY_SENSOR.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

# Capabilities the climate entity consumes directly. They must NOT be turned
# into generic switches/selects/sensors — climate reads/writes them itself with
# domain-specific logic (HA climate enums, the executeCommand on/off protocol,
# C/F handling, swing).
CLIMATE_CONSUMED: frozenset[str] = frozenset(
    {
        "mode",
        "fanSpeedSetting",
        "verticalSwing",
        "flapOscillate",
        "horizontalSwing",
        "targetTemperatureC",
        "targetTemperatureF",
        "ambientTemperatureC",
        "ambientTemperatureF",
        "temperatureRepresentation",
        "executeCommand",
        "applianceState",
    }
)

# Swing capability names, in preference order. Climate picks the first one an
# appliance actually exposes (Frigidaire uses verticalSwing; YI09F uses
# flapOscillate).
SWING_KEYS: tuple[str, ...] = ("verticalSwing", "flapOscillate", "horizontalSwing")

# Value-key sets that mean "this is really a boolean on/off control".
_BOOLEAN_LIKE_SETS: tuple[frozenset[str], ...] = (
    frozenset({"ON", "OFF"}),
    frozenset({"0", "1"}),
)


class EntityKind(Enum):
    """What a capability should become in Home Assistant."""

    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    CLIMATE = "climate"
    IGNORE = "ignore"


_SNAKE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake_case(name: str) -> str:
    """Convert an API capability name to ``snake_case``.

    Handles camelCase, acronym runs, digit boundaries and existing separators
    (``hCPN_ACAlerts`` -> ``h_cpn_ac_alerts``, ``targetTemperatureC`` ->
    ``target_temperature_c``).
    """
    # Normalise any existing separator to a boundary marker first.
    spaced = re.sub(r"[_\-\s]+", " ", name)
    # Insert boundaries at camelCase / acronym transitions within each token.
    spaced = _SNAKE_BOUNDARY.sub(" ", spaced)
    parts = [p for p in spaced.split() if p]
    return "_".join(p.lower() for p in parts)


def coerce_value(val: Any) -> int | float | None:
    """Tolerantly coerce a reported/API value to a number, else ``None``.

    - ``"DISPLAY_LIGHT_3"`` / ``"POSITION_2"`` -> the trailing int.
    - real ``int``/``float`` pass through unchanged.
    - numeric strings (``"7"``, ``"15.56"``) -> parsed number.
    - ``bool`` (``True``/``False``) -> ``None`` (a bool is not a numeric level).
    - anything else (``"ON"``, ``"AUTO"``, ``None``) -> ``None``.

    Used by number/select/displayLight readers so the enum-token vs raw-numeric
    inconsistency in the API never crashes.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return val
    if not isinstance(val, str):
        return None

    # DISPLAY_LIGHT_N / POSITION_N (or any TOKEN_<int> shape) -> trailing int.
    m = re.search(r"(\d+)$", val)
    stripped = val.strip()
    # Pure numeric string first (covers "7", "-3", "15.56").
    try:
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"-?\d+\.\d+", stripped):
            return float(stripped)
    except ValueError:  # pragma: no cover - regex guards this
        pass
    # Enum token with a trailing integer index.
    if m and "_" in val:
        return int(m.group(1))
    return None


def _values(cap: dict[str, Any]) -> dict[str, Any]:
    values = cap.get("values")
    return values if isinstance(values, dict) else {}


def _is_boolean_like(keys: set[str], cap: dict[str, Any]) -> bool:
    """True if a value set represents a two-state on/off control.

    Qualifies: ``type: boolean``; the canonical ``{ON,OFF}`` / ``{0,1}`` sets;
    and any exactly-two-value set whose keys are numeric-index tokens (e.g.
    ``{DISPLAY_LIGHT_0, DISPLAY_LIGHT_1}``) — an off/on pair the plan routes to a
    switch. A two-value *word* enum such as ``{DEFROSTING, NOT_DEFROSTING}`` is
    NOT boolean-like: it stays a proper enum sensor/select.
    """
    if cap.get("type") == "boolean":
        return True
    fk = frozenset(keys)
    if any(fk == s for s in _BOOLEAN_LIKE_SETS):
        return True
    if len(keys) == 2 and all(coerce_value(k) is not None for k in keys):
        return True
    return False


def _on_off(keys: set[str]) -> tuple[Any, Any]:
    """Pick the (on, off) key for a boolean-like value set."""
    if keys == {"ON", "OFF"}:
        return "ON", "OFF"
    if keys == {"0", "1"}:
        return "1", "0"
    if keys == {"DISPLAY_LIGHT_0", "DISPLAY_LIGHT_1"}:
        return "DISPLAY_LIGHT_1", "DISPLAY_LIGHT_0"
    # Fallback: coerce each key and treat the larger as "on".
    on = off = None
    for k in keys:
        c = coerce_value(k)
        if c is not None and c > 0:
            on = k
        else:
            off = k
    return on, off


def classify_capability(name: str, cap: dict[str, Any]) -> tuple[EntityKind, dict]:
    """Route one capability to an :class:`EntityKind` plus a small spec dict.

    See the module docstring for the ordered rules. The spec dict carries only
    what the eventual entity builder needs: ``on``/``off`` for switches &
    binary sensors, ``values`` (lowercased option keys) for selects & enum
    sensors, ``min``/``max``/``step`` for numbers & measurement sensors.
    """
    if not isinstance(cap, dict):
        return EntityKind.IGNORE, {}

    access = cap.get("access")
    cap_type = cap.get("type")

    # 1. Constants / alerts / hCPN_ bookkeeping — pure noise. Checked before the
    #    climate hand-off so a write-only cap that climate consumes internally
    #    (executeCommand) is dropped, not surfaced as a climate spec here.
    if access == "constant" or cap_type == "alert" or name.startswith("hCPN_"):
        return EntityKind.IGNORE, {}

    # 2. Write-only actions (executeCommand, cleanFilterAlertReset) — no state.
    if access == "write":
        return EntityKind.IGNORE, {}

    # 3. Climate owns the remaining consumed caps (mode, fan, swing, temps, ...).
    if name in CLIMATE_CONSUMED:
        return EntityKind.CLIMATE, {}

    values = _values(cap)

    # 4. Has a non-empty value set (checked BEFORE min/max on purpose).
    if values:
        keys = set(values)
        options = [k.lower() for k in sorted(values)]
        if _is_boolean_like(keys, cap):
            on, off = _on_off(keys)
            if access == "readwrite":
                return EntityKind.SWITCH, {"on": on, "off": off}
            # access == "read" (or anything non-writable) -> read-only.
            return EntityKind.BINARY_SENSOR, {"on": on, "off": off}
        # Multi-value enum.
        if access == "readwrite":
            return EntityKind.SELECT, {"values": options}
        # Any values + read -> enum sensor.
        return EntityKind.SENSOR, {"values": options}

    # 5. Numeric range (min/max present, no values).
    if "min" in cap and "max" in cap:
        # 5a. R1: a numeric-looking range declared type=string speaks enum tokens
        #     ("DISPLAY_LIGHT_0"), not integers — it's an on/off token control.
        #     Genuine numbers (type number/int: stopTime, currentEnergyUsePercent)
        #     skip this and fall through to the numeric spec below.
        if cap_type == "string":
            prefix = snake_case(name).upper()   # displayLight -> "DISPLAY_LIGHT"
            lo = cap["min"]
            off = f"{prefix}_{lo}"              # "DISPLAY_LIGHT_0"
            on = f"{prefix}_{lo + 1}"          # "DISPLAY_LIGHT_1"
            if access == "readwrite":
                return EntityKind.SWITCH, {"on": on, "off": off}
            return EntityKind.BINARY_SENSOR, {"on": on, "off": off}

        spec = {"min": cap["min"], "max": cap["max"], "step": cap.get("step", 1)}

        # 5b. R2: an integer range whose bounds are whole hours (max a positive
        #     multiple of 3600s, step also a multiple of 3600s) is a duration
        #     off-timer in seconds — expose it in HOURS. currentEnergyUsePercent
        #     (max 100) and temperatures never match.
        if (
            cap_type in {"number", "int"}
            and cap["max"] >= 3600
            and cap["max"] % 3600 == 0
            and cap.get("step", 1) % 3600 == 0
        ):
            scale = 3600
            spec = {
                "min": cap["min"] // scale,
                "max": cap["max"] // scale,
                "step": cap.get("step", 1) // scale,
                "unit": "h",
                "device_class": "duration",
                "scale": scale,
            }

        if access == "readwrite":
            return EntityKind.NUMBER, spec
        if access == "read":
            return EntityKind.SENSOR, spec
        return EntityKind.IGNORE, {}

    # 6. Nothing meaningful (bare read string, nested container, etc.).
    return EntityKind.IGNORE, {}
