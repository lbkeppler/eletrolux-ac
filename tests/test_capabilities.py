"""Tests for the pure capability classifier (`capabilities.py`).

These tests iterate the REAL capabilities from both info fixtures and assert the
exact ``(EntityKind, spec)`` each one routes to. They are the contract that
makes entity generation data-driven: if a real appliance shape changes, these
break — on purpose.
"""
import json
from pathlib import Path

import pytest

from custom_components.electrolux_ac.capabilities import (
    CLIMATE_CONSUMED,
    SWING_KEYS,
    EntityKind,
    classify_capability,
    coerce_value,
    snake_case,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _caps(name):
    return json.loads((FIXTURES / name).read_text())["capabilities"]


FRIGIDAIRE = _caps("info.json")
YI09F = _caps("real_ac_info.json")


# --- snake_case -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("displayLight", "display_light"),
        ("cleanAirMode", "clean_air_mode"),
        ("fanSpeedSetting", "fan_speed_setting"),
        ("targetTemperatureC", "target_temperature_c"),
        ("hCPN_ACAlerts", "h_cpn_ac_alerts"),
        ("mode", "mode"),
        ("uiLockMode", "ui_lock_mode"),
        ("currentEnergyUsePercent", "current_energy_use_percent"),
    ],
)
def test_snake_case(raw, expected):
    assert snake_case(raw) == expected


# --- coerce_value -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("DISPLAY_LIGHT_3", 3),
        ("DISPLAY_LIGHT_0", 0),
        ("POSITION_2", 2),
        ("POSITION_6", 6),
        (5, 5),
        (23.0, 23.0),
        ("7", 7),
        ("15.56", 15.56),
        ("ON", None),
        ("OFF", None),
        ("AUTO", None),
        (None, None),
        (True, None),  # bool is not a numeric value here
        (False, None),
    ],
)
def test_coerce_value(raw, expected):
    result = coerce_value(raw)
    assert result == expected
    if expected is not None:
        assert type(result) is type(expected)


# --- CLIMATE_CONSUMED / SWING_KEYS constants --------------------------------


def test_climate_consumed_membership():
    for name in (
        "mode",
        "fanSpeedSetting",
        "verticalSwing",
        "flapOscillate",
        "targetTemperatureC",
        "targetTemperatureF",
        "ambientTemperatureC",
        "ambientTemperatureF",
        "temperatureRepresentation",
        "executeCommand",
        "applianceState",
    ):
        assert name in CLIMATE_CONSUMED, name


def test_swing_keys():
    assert SWING_KEYS == ("verticalSwing", "flapOscillate", "horizontalSwing")


# --- classification helper --------------------------------------------------


def _kind(caps, name):
    kind, _spec = classify_capability(name, caps[name])
    return kind


# --- Frigidaire (info.json) full classification -----------------------------

FRIGIDAIRE_EXPECTED = {
    "ambientTemperatureC": EntityKind.CLIMATE,
    "applianceState": EntityKind.CLIMATE,
    "cleanAirMode": EntityKind.SWITCH,          # readwrite {ON,OFF}
    "displayLight": EntityKind.SWITCH,          # values DISPLAY_LIGHT_0/1, no min/max
    "executeCommand": EntityKind.IGNORE,        # write
    "fanSpeedSetting": EntityKind.CLIMATE,
    "filterState": EntityKind.SENSOR,           # read enum
    "mode": EntityKind.CLIMATE,
    "schedulerMode": EntityKind.SWITCH,         # readwrite {ON,OFF}
    "sleepMode": EntityKind.SWITCH,             # readwrite {ON,OFF}
    "targetTemperatureC": EntityKind.CLIMATE,
    "targetTemperatureF": EntityKind.CLIMATE,
    "temperatureRepresentation": EntityKind.CLIMATE,
    "uiLockMode": EntityKind.SWITCH,            # boolean type {ON,OFF}
    "verticalSwing": EntityKind.CLIMATE,        # swing key
}


def test_frigidaire_covers_every_capability():
    """Guard: the expected table must list every top-level capability."""
    assert set(FRIGIDAIRE_EXPECTED) == set(FRIGIDAIRE)


@pytest.mark.parametrize("name", sorted(FRIGIDAIRE_EXPECTED))
def test_frigidaire_classification(name):
    assert _kind(FRIGIDAIRE, name) == FRIGIDAIRE_EXPECTED[name]


def test_frigidaire_display_light_switch_spec():
    kind, spec = classify_capability("displayLight", FRIGIDAIRE["displayLight"])
    assert kind == EntityKind.SWITCH
    assert spec["on"] == "DISPLAY_LIGHT_1"
    assert spec["off"] == "DISPLAY_LIGHT_0"


def test_frigidaire_clean_air_mode_switch_spec():
    kind, spec = classify_capability("cleanAirMode", FRIGIDAIRE["cleanAirMode"])
    assert kind == EntityKind.SWITCH
    assert spec["on"] == "ON"
    assert spec["off"] == "OFF"


def test_frigidaire_filter_state_sensor_options():
    kind, spec = classify_capability("filterState", FRIGIDAIRE["filterState"])
    assert kind == EntityKind.SENSOR
    assert spec["values"] == ["buy", "change", "clean", "good"]


# --- YI09F (real_ac_info.json) full classification --------------------------

YI09F_EXPECTED = {
    "alerts": EntityKind.IGNORE,                    # type alert
    "applianceMainBoardSwVersion": EntityKind.IGNORE,  # read string, no values & no min/max
    "applianceState": EntityKind.CLIMATE,
    "autoSenseMode": EntityKind.SWITCH,             # readwrite {ON,OFF}
    "batchSchedulerMode": EntityKind.SWITCH,        # boolean {ON,OFF}
    "cleanAirMode": EntityKind.BINARY_SENSOR,       # read {ON,OFF}
    "cleanFilterAlertReset": EntityKind.IGNORE,     # write
    "comfortAir": EntityKind.SWITCH,                # readwrite {ON,OFF}
    "currentEnergyUsePercent": EntityKind.SENSOR,   # read numeric
    "displayLight": EntityKind.NUMBER,              # min0/max100, NO values
    "evaporatorDefrostState": EntityKind.SENSOR,    # read enum (2 values)
    "executeCommand": EntityKind.IGNORE,            # write
    "fanSpeedSetting": EntityKind.CLIMATE,
    "filterState": EntityKind.SENSOR,               # read enum
    "flapOscillate": EntityKind.CLIMATE,            # swing key
    "flapPosition": EntityKind.SELECT,              # type=number BUT has values -> values first
    "hCPN_ACAlerts": EntityKind.IGNORE,             # constant / hCPN_
    "hCPN_AirFilterBuy": EntityKind.IGNORE,
    "hCPN_AirFilterChange": EntityKind.IGNORE,
    "hCPN_AirFilterClean": EntityKind.IGNORE,
    "hCPN_TimerEnding": EntityKind.IGNORE,
    "mode": EntityKind.CLIMATE,
    "networkInterface": EntityKind.IGNORE,          # nested container, not a leaf capability
    "sleepMode": EntityKind.SWITCH,                 # readwrite {ON,OFF}
    "soundVolume": EntityKind.SWITCH,               # readwrite boolean-like {0,1} -> switch (plan defers)
    "stopTime": EntityKind.NUMBER,                  # readwrite numeric range
    "targetTemperatureC": EntityKind.CLIMATE,
}


def test_yi09f_covers_every_capability():
    """Guard: the expected table must list every top-level capability."""
    assert set(YI09F_EXPECTED) == set(YI09F)


@pytest.mark.parametrize("name", sorted(YI09F_EXPECTED))
def test_yi09f_classification(name):
    assert _kind(YI09F, name) == YI09F_EXPECTED[name]


def test_yi09f_display_light_number_spec():
    kind, spec = classify_capability("displayLight", YI09F["displayLight"])
    assert kind == EntityKind.NUMBER
    assert spec["min"] == 0
    assert spec["max"] == 100
    assert spec["step"] == 1


def test_yi09f_stop_time_number_spec():
    kind, spec = classify_capability("stopTime", YI09F["stopTime"])
    assert kind == EntityKind.NUMBER
    assert spec["min"] == 0
    assert spec["max"] == 86400
    assert spec["step"] == 3600


def test_yi09f_flap_position_select_spec():
    kind, spec = classify_capability("flapPosition", YI09F["flapPosition"])
    assert kind == EntityKind.SELECT
    assert spec["values"] == [
        "position_0",
        "position_1",
        "position_2",
        "position_3",
        "position_4",
        "position_5",
        "position_6",
    ]


def test_yi09f_current_energy_use_percent_sensor_spec():
    kind, spec = classify_capability(
        "currentEnergyUsePercent", YI09F["currentEnergyUsePercent"]
    )
    assert kind == EntityKind.SENSOR
    assert spec["min"] == 0
    assert spec["max"] == 100


def test_yi09f_sound_volume_switch_spec():
    kind, spec = classify_capability("soundVolume", YI09F["soundVolume"])
    assert kind == EntityKind.SWITCH
    assert spec["on"] == "1"
    assert spec["off"] == "0"


def test_yi09f_clean_air_mode_is_binary_sensor():
    # Same name as Frigidaire's SWITCH, but access=read here -> binary_sensor.
    kind, spec = classify_capability("cleanAirMode", YI09F["cleanAirMode"])
    assert kind == EntityKind.BINARY_SENSOR
    assert spec["on"] == "ON"
    assert spec["off"] == "OFF"


def test_same_name_diverges_on_access():
    """cleanAirMode & displayLight prove classification is structure/access driven."""
    assert _kind(FRIGIDAIRE, "cleanAirMode") == EntityKind.SWITCH
    assert _kind(YI09F, "cleanAirMode") == EntityKind.BINARY_SENSOR
    assert _kind(FRIGIDAIRE, "displayLight") == EntityKind.SWITCH
    assert _kind(YI09F, "displayLight") == EntityKind.NUMBER
