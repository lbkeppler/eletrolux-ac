# tests/test_const.py
from homeassistant.components.climate import HVACMode
from homeassistant.const import Platform

from custom_components.electrolux_ac import const


def test_domain_and_platforms():
    assert const.DOMAIN == "electrolux_ac"
    assert Platform.CLIMATE in const.PLATFORMS
    assert Platform.SENSOR in const.PLATFORMS
    assert Platform.SWITCH in const.PLATFORMS
    assert Platform.SELECT in const.PLATFORMS
    assert Platform.BINARY_SENSOR in const.PLATFORMS


def test_hvac_mode_map_round_trips():
    assert const.HVAC_MODE_MAP["COOL"] is HVACMode.COOL
    assert const.HVAC_MODE_MAP["AUTO"] is HVACMode.AUTO
    assert const.HVAC_MODE_MAP["DRY"] is HVACMode.DRY
    assert const.HVAC_MODE_MAP["FANONLY"] is HVACMode.FAN_ONLY
    # reverse map turns a HA mode back into the API string
    assert const.HVAC_MODE_MAP_REVERSE[HVACMode.COOL] == "COOL"
    assert const.HVAC_MODE_MAP_REVERSE[HVACMode.FAN_ONLY] == "FANONLY"


def test_fan_mode_map():
    assert const.FAN_MODE_MAP["MIDDLE"] == "medium"
    assert const.FAN_MODE_MAP_REVERSE["medium"] == "MIDDLE"
    assert const.FAN_MODE_MAP["AUTO"] == "auto"
