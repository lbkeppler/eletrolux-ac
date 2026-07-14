"""Tests for the Electrolux AC sensor/switch/select/number/binary_sensor platforms.

The secondary platforms are generated from the pure ``classify_capability``
classifier, so these tests exercise the pure builders over BOTH real appliance
fixtures (Frigidaire type AC and Electrolux YI09F type CA) with a MagicMock
coordinator whose ``.data`` comes from ``parse_appliance`` — no full HA setup
required.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.electrolux_ac.binary_sensor import (
    ElectroluxConnectivity,
    build_binary_sensors,
)
from custom_components.electrolux_ac.coordinator import parse_appliance
from custom_components.electrolux_ac.number import build_numbers
from custom_components.electrolux_ac.select import build_selects
from custom_components.electrolux_ac.sensor import build_sensors
from custom_components.electrolux_ac.switch import build_switches

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _coord_for(prefix):
    """Build a MagicMock coordinator from a fixture triple.

    prefix "" -> Frigidaire (appliances/info/state.json);
    prefix "real_ac_" -> YI09F (real_ac_*.json).
    """
    data = parse_appliance(
        _load(f"{prefix}appliances.json")[0],
        _load(f"{prefix}info.json"),
        _load(f"{prefix}state.json"),
    )
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.last_update_success = True
    return coord, data.appliance_id


def _coord():
    return _coord_for("")


def _real_coord():
    return _coord_for("real_ac_")


def _keys(entities):
    return {e._attr_translation_key for e in entities}


# --- existing bespoke-sensor / switch / connectivity coverage ----------------


def test_sensors_created_for_ac():
    coord, aid = _coord()
    sensors = build_sensors(coord, aid)
    keys = _keys(sensors)
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
    keys = _keys(switches)
    assert {"sleep_mode", "clean_air_mode", "ui_lock_mode", "scheduler_mode", "display_light"} <= keys
    display = next(s for s in switches if s._attr_translation_key == "display_light")
    # fixture reports DISPLAY_LIGHT_1 -> on
    assert display.is_on is True
    # uiLockMode reports a JSON bool false -> off
    lock = next(s for s in switches if s._attr_translation_key == "ui_lock_mode")
    assert lock.is_on is False


def test_connectivity_binary_sensor():
    coord, aid = _coord()
    ent = ElectroluxConnectivity(coord, aid)
    assert ent._attr_device_class == BinarySensorDeviceClass.CONNECTIVITY
    assert ent.is_on is True  # fixture connection_state == connected
    # available even if disconnected
    coord.data[aid].connection_state = "disconnected"
    assert ent.available is True
    assert ent.is_on is False


# --- Frigidaire: no selects, no numbers, five switches -----------------------


def test_frigidaire_no_numbers():
    coord, aid = _coord()
    assert build_numbers(coord, aid) == []


def test_frigidaire_no_selects():
    coord, aid = _coord()
    assert build_selects(coord, aid) == []


def test_frigidaire_switch_set_exact():
    coord, aid = _coord()
    keys = _keys(build_switches(coord, aid))
    assert keys == {
        "sleep_mode",
        "clean_air_mode",
        "ui_lock_mode",
        "scheduler_mode",
        "display_light",
    }


def test_frigidaire_display_light_is_switch_not_number():
    coord, aid = _coord()
    switch_keys = _keys(build_switches(coord, aid))
    number_keys = _keys(build_numbers(coord, aid))
    assert "display_light" in switch_keys
    assert "display_light" not in number_keys


# --- YI09F switches ----------------------------------------------------------


def test_yi09f_switches_are_the_readwrite_booleans():
    coord, aid = _real_coord()
    keys = _keys(build_switches(coord, aid))
    # R1: displayLight is now a switch (min/max + type=string on/off token).
    # R3: batchSchedulerMode is a phantom (absent from reported) -> SKIPPED.
    # sleep/autoSense/comfortAir/soundVolume are genuine readwrite booleans.
    assert keys == {
        "sleep_mode",
        "auto_sense_mode",
        "comfort_air",
        "sound_volume",
        "display_light",
    }
    # batchSchedulerMode classifies SWITCH but is never reported -> skipped (R3)
    assert "batch_scheduler_mode" not in keys
    # flapOscillate is climate's swing key -> NOT a switch
    assert "flap_oscillate" not in keys
    # cleanAirMode is read -> binary_sensor, NOT a switch
    assert "clean_air_mode" not in keys


def test_yi09f_display_light_switch_reported_off():
    # R1: reported "DISPLAY_LIGHT_0" == off token -> is_on False.
    coord, aid = _real_coord()
    dl = next(
        s for s in build_switches(coord, aid) if s._attr_translation_key == "display_light"
    )
    assert dl._on_value == "DISPLAY_LIGHT_1"
    assert dl._off_value == "DISPLAY_LIGHT_0"
    assert dl.is_on is False


async def test_yi09f_display_light_switch_turn_on_writes_token():
    coord, aid = _real_coord()
    coord.async_send_command = _AsyncRecorder()
    dl = next(
        s for s in build_switches(coord, aid) if s._attr_translation_key == "display_light"
    )
    await dl.async_turn_on()
    assert coord.async_send_command.calls == [(aid, {"displayLight": "DISPLAY_LIGHT_1"})]


def test_yi09f_sound_volume_switch_on_off():
    coord, aid = _real_coord()
    sw = next(
        s for s in build_switches(coord, aid) if s._attr_translation_key == "sound_volume"
    )
    # spec on="1"/off="0"; reported soundVolume == 1 (int) -> on
    assert sw.is_on is True


# --- YI09F numbers -----------------------------------------------------------


def test_yi09f_numbers_only_stop_time_in_hours():
    # R1: displayLight is now a SWITCH, not a number.
    # R2: stopTime is exposed in HOURS (seconds/3600).
    coord, aid = _real_coord()
    numbers = build_numbers(coord, aid)
    keys = _keys(numbers)
    assert keys == {"stop_time"}
    assert "display_light" not in keys
    st = next(n for n in numbers if n._attr_translation_key == "stop_time")
    assert st.native_min_value == 0
    assert st.native_max_value == 24
    assert st.native_step == 1
    # reported stopTime == 0 seconds -> 0.0 hours
    assert st.native_value == 0.0


async def test_yi09f_stop_time_set_writes_seconds():
    # R2: setting 2 hours writes 7200 seconds back to the API.
    coord, aid = _real_coord()
    coord.async_send_command = _AsyncRecorder()
    st = next(
        n for n in build_numbers(coord, aid) if n._attr_translation_key == "stop_time"
    )
    await st.async_set_native_value(2)
    assert coord.async_send_command.calls == [(aid, {"stopTime": 7200})]


# --- YI09F selects -----------------------------------------------------------


def test_yi09f_select_flap_position_seven_options():
    coord, aid = _real_coord()
    selects = build_selects(coord, aid)
    keys = _keys(selects)
    assert keys == {"flap_position"}
    sel = selects[0]
    assert sel.options == [
        "position_0",
        "position_1",
        "position_2",
        "position_3",
        "position_4",
        "position_5",
        "position_6",
    ]
    # reported flapPosition == 0 (int) -> maps back to position_0
    assert sel.current_option == "position_0"


async def test_yi09f_select_set_sends_int_for_numeric_cap():
    coord, aid = _real_coord()
    coord.async_send_command = _AsyncRecorder()
    sel = build_selects(coord, aid)[0]
    await sel.async_select_option("position_3")
    # flapPosition is type=number -> send the int index
    assert coord.async_send_command.calls == [(aid, {"flapPosition": 3})]


# --- YI09F sensors (generic read) -------------------------------------------


def test_yi09f_generic_sensors_include_energy_and_defrost():
    coord, aid = _real_coord()
    sensors = build_sensors(coord, aid)
    keys = _keys(sensors)
    # bespoke ones survive
    assert "filter_state" in keys
    assert "link_quality" in keys
    # generic read sensors from the classifier
    assert "current_energy_use_percent" in keys
    assert "evaporator_defrost_state" in keys
    # informational ones are disabled by default to avoid entity sprawl
    energy = next(
        s for s in sensors if s._attr_translation_key == "current_energy_use_percent"
    )
    assert energy._attr_entity_registry_enabled_default is False
    assert energy.native_value == 100
    defrost = next(
        s for s in sensors if s._attr_translation_key == "evaporator_defrost_state"
    )
    assert defrost._attr_entity_registry_enabled_default is False
    assert defrost.native_value == "not_defrosting"


def test_yi09f_link_quality_not_double_created():
    """networkInterface classifies IGNORE; the bespoke LinkQualitySensor stays the
    single source of link quality (no duplicate generic sensor)."""
    coord, aid = _real_coord()
    keys = [s._attr_translation_key for s in build_sensors(coord, aid)]
    assert keys.count("link_quality") == 1


# --- YI09F binary sensors (generic read) ------------------------------------


def test_yi09f_clean_air_mode_is_binary_sensor():
    coord, aid = _real_coord()
    bins = build_binary_sensors(coord, aid)
    keys = _keys(bins)
    assert "clean_air_mode" in keys
    cam = next(b for b in bins if b._attr_translation_key == "clean_air_mode")
    assert cam._attr_entity_registry_enabled_default is False
    # reported cleanAirMode == "OFF" -> off
    assert cam.is_on is False


def test_frigidaire_no_generic_binary_sensors():
    """Frigidaire's cleanAirMode is readwrite (a switch), so no read-only
    binary sensor is generated for it."""
    coord, aid = _coord()
    keys = _keys(build_binary_sensors(coord, aid))
    assert "clean_air_mode" not in keys


class _AsyncRecorder:
    """Minimal awaitable call recorder for coordinator.async_send_command."""

    def __init__(self):
        self.calls = []

    async def __call__(self, appliance_id, command):
        self.calls.append((appliance_id, command))
