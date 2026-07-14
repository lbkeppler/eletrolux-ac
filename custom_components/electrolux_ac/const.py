"""Constants for the Electrolux AC integration."""
from __future__ import annotations

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    HVACMode,
)
from homeassistant.const import Platform

DOMAIN = "electrolux_ac"

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
]

# Config entry keys
CONF_API_KEY = "api_key"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

# API network limits
POLL_INTERVAL_MINUTES = 5
SSE_RECONNECT_SECONDS = 10
SSE_RECONNECT_MAX_SECONDS = 300
# Consider the stream "healthy" (reset backoff) after this many seconds connected.
SSE_HEALTHY_SECONDS = 60

# Capability / reported-state property names (from openapi.json)
PROP_MODE = "mode"
PROP_TARGET_TEMP_C = "targetTemperatureC"
PROP_TARGET_TEMP_F = "targetTemperatureF"
PROP_AMBIENT_TEMP_C = "ambientTemperatureC"
PROP_AMBIENT_TEMP_F = "ambientTemperatureF"
PROP_FAN_SPEED = "fanSpeedSetting"
PROP_VERTICAL_SWING = "verticalSwing"
PROP_TEMP_REPRESENTATION = "temperatureRepresentation"
PROP_EXECUTE_COMMAND = "executeCommand"
PROP_APPLIANCE_STATE = "applianceState"
PROP_FILTER_STATE = "filterState"
PROP_SLEEP_MODE = "sleepMode"
PROP_CLEAN_AIR_MODE = "cleanAirMode"
PROP_DISPLAY_LIGHT = "displayLight"
PROP_UI_LOCK_MODE = "uiLockMode"
PROP_SCHEDULER_MODE = "schedulerMode"
PROP_NETWORK_INTERFACE = "networkInterface"

# Values
UNIT_FAHRENHEIT = "FAHRENHEIT"
UNIT_CELSIUS = "CELSIUS"
STATE_RUNNING = "RUNNING"
STATE_OFF = "OFF"
CONNECTION_CONNECTED = "connected"

# API mode string <-> HA HVACMode
HVAC_MODE_MAP: dict[str, HVACMode] = {
    "COOL": HVACMode.COOL,
    "AUTO": HVACMode.AUTO,
    "DRY": HVACMode.DRY,
    "FANONLY": HVACMode.FAN_ONLY,
    "HEAT": HVACMode.HEAT,
}
HVAC_MODE_MAP_REVERSE: dict[HVACMode, str] = {
    v: k for k, v in HVAC_MODE_MAP.items()
}

# Display hint for KNOWN API fan-speed tokens -> HA's canonical fan-mode
# strings. This is only a *hint*: the climate entity builds per-appliance
# forward/reverse maps from the appliance's own ``fanSpeedSetting`` values, and
# any token NOT listed here (TURBO, or any future token) falls back to the
# lowercased token so it is never silently dropped.
FAN_DISPLAY: dict[str, str] = {
    "AUTO": FAN_AUTO,
    "LOW": FAN_LOW,
    "MIDDLE": FAN_MEDIUM,
    "HIGH": FAN_HIGH,
}

# Deprecated lossy global maps. Kept only for backward-compatibility with any
# external importer; climate no longer uses these because ``.get`` on them
# drops unknown tokens (e.g. TURBO). Prefer the per-entity maps in climate.py.
FAN_MODE_MAP: dict[str, str] = dict(FAN_DISPLAY)
FAN_MODE_MAP_REVERSE: dict[str, str] = {v: k for k, v in FAN_MODE_MAP.items()}
