"""Tests for the Electrolux AC sensor/switch/binary_sensor platforms."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.electrolux_ac.binary_sensor import ElectroluxConnectivity
from custom_components.electrolux_ac.coordinator import parse_appliance
from custom_components.electrolux_ac.sensor import build_sensors
from custom_components.electrolux_ac.switch import build_switches

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _coord():
    data = parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.last_update_success = True
    return coord, data.appliance_id


def test_sensors_created_for_ac():
    coord, aid = _coord()
    sensors = build_sensors(coord, aid)
    keys = {s._attr_translation_key for s in sensors}
    assert "ambient_temperature" in keys
    assert "filter_state" in keys
    assert "link_quality" in keys
    filt = next(s for s in sensors if s._attr_translation_key == "filter_state")
    assert filt._attr_device_class == SensorDeviceClass.ENUM
    assert "good" in filt.options
    assert filt.native_value == "good"


def test_switches_created_for_ac():
    coord, aid = _coord()
    switches = build_switches(coord, aid)
    keys = {s._attr_translation_key for s in switches}
    assert {"sleep_mode", "clean_air_mode", "ui_lock_mode", "scheduler_mode", "display_light"} <= keys
    display = next(s for s in switches if s._attr_translation_key == "display_light")
    # fixture reports DISPLAY_LIGHT_1 -> on
    assert display.is_on is True


def test_connectivity_binary_sensor():
    coord, aid = _coord()
    ent = ElectroluxConnectivity(coord, aid)
    assert ent._attr_device_class == BinarySensorDeviceClass.CONNECTIVITY
    assert ent.is_on is True  # fixture connection_state == connected
    # available even if disconnected
    coord.data[aid].connection_state = "disconnected"
    assert ent.available is True
    assert ent.is_on is False
