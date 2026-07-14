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
    Platform.BINARY_SENSOR,
]

# Config entry keys
CONF_API_KEY = "api_key"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

# API network limits
POLL_INTERVAL_MINUTES = 5
SSE_RECONNECT_SECONDS = 10

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

# API fan-speed string <-> HA fan mode
FAN_MODE_MAP: dict[str, str] = {
    "AUTO": FAN_AUTO,
    "LOW": FAN_LOW,
    "MIDDLE": FAN_MEDIUM,
    "HIGH": FAN_HIGH,
}
FAN_MODE_MAP_REVERSE: dict[str, str] = {v: k for k, v in FAN_MODE_MAP.items()}
