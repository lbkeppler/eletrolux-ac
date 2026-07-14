import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import UnitOfTemperature

from custom_components.electrolux_ac.climate import ElectroluxClimate
from custom_components.electrolux_ac.coordinator import parse_appliance

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _coord_with_data():
    data = parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.async_send_command = AsyncMock()
    return coord, data.appliance_id


def _coord_real_ac():
    """The real Electrolux YI09F: fan LOW/MIDDLE/HIGH/TURBO, swing flapOscillate."""
    data = parse_appliance(
        _load("real_ac_appliances.json")[0],
        _load("real_ac_info.json"),
        _load("real_ac_state.json"),
    )
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.async_send_command = AsyncMock()
    return coord, data.appliance_id


def test_hvac_modes_from_capabilities():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert HVACMode.OFF in entity.hvac_modes
    assert HVACMode.COOL in entity.hvac_modes
    assert HVACMode.AUTO in entity.hvac_modes
    assert HVACMode.DRY in entity.hvac_modes
    assert HVACMode.FAN_ONLY in entity.hvac_modes


def test_current_and_target_celsius():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert entity.temperature_unit == UnitOfTemperature.CELSIUS
    assert entity.current_temperature == 22
    assert entity.target_temperature == 21
    assert entity.min_temp == 15.56
    assert entity.max_temp == 32.22


def test_hvac_mode_reflects_running_state():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    # fixture has applianceState RUNNING, mode COOL
    assert entity.hvac_mode == HVACMode.COOL


async def test_set_hvac_mode_off_sends_execute_off():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_hvac_mode(HVACMode.OFF)
    coord.async_send_command.assert_awaited_once_with(aid, {"executeCommand": "OFF"})


async def test_set_hvac_mode_cool_sends_on_and_mode():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_hvac_mode(HVACMode.COOL)
    coord.async_send_command.assert_awaited_once_with(
        aid, {"executeCommand": "ON", "mode": "COOL"}
    )


async def test_set_temperature_celsius():
    from homeassistant.components.climate import ATTR_TEMPERATURE

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 24})
    coord.async_send_command.assert_awaited_once_with(aid, {"targetTemperatureC": 24})


async def test_set_fan_mode():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_fan_mode("medium")
    coord.async_send_command.assert_awaited_once_with(aid, {"fanSpeedSetting": "MIDDLE"})


def _coord_fahrenheit():
    """Same appliance but reporting Fahrenheit."""
    state = _load("state.json")
    reported = state["properties"]["reported"]
    reported["temperatureRepresentation"] = "FAHRENHEIT"
    reported["targetTemperatureF"] = 70
    reported["ambientTemperatureF"] = 72
    data = parse_appliance(_load("appliances.json")[0], _load("info.json"), state)
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.async_send_command = AsyncMock()
    return coord, data.appliance_id


def test_fahrenheit_unit_and_values():
    coord, aid = _coord_fahrenheit()
    entity = ElectroluxClimate(coord, aid)
    assert entity.temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert entity.current_temperature == 72
    assert entity.target_temperature == 70
    # F capability from fixture: min 60 / max 90
    assert entity.min_temp == 60
    assert entity.max_temp == 90


async def test_set_temperature_fahrenheit_sends_f_key():
    from homeassistant.components.climate import ATTR_TEMPERATURE

    coord, aid = _coord_fahrenheit()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 68})
    coord.async_send_command.assert_awaited_once_with(aid, {"targetTemperatureF": 68})


async def test_turn_on_off():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_turn_on()
    coord.async_send_command.assert_awaited_with(aid, {"executeCommand": "ON"})
    await entity.async_turn_off()
    coord.async_send_command.assert_awaited_with(aid, {"executeCommand": "OFF"})


async def test_set_swing_mode():
    from homeassistant.components.climate import SWING_ON, SWING_OFF

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_swing_mode(SWING_ON)
    coord.async_send_command.assert_awaited_with(aid, {"verticalSwing": "ON"})
    await entity.async_set_swing_mode(SWING_OFF)
    coord.async_send_command.assert_awaited_with(aid, {"verticalSwing": "OFF"})


def test_hvac_mode_off_when_appliance_off():
    state = _load("state.json")
    state["properties"]["reported"]["applianceState"] = "OFF"
    data = parse_appliance(_load("appliances.json")[0], _load("info.json"), state)
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    entity = ElectroluxClimate(coord, data.appliance_id)
    assert entity.hvac_mode == HVACMode.OFF


def test_hvac_mode_unmapped_but_running_is_not_off():
    """A running AC reporting a mode we don't map must not render as Off."""
    state = _load("state.json")
    state["properties"]["reported"]["applianceState"] = "RUNNING"
    state["properties"]["reported"]["mode"] = "SOME_BR_MODE"
    data = parse_appliance(_load("appliances.json")[0], _load("info.json"), state)
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    entity = ElectroluxClimate(coord, data.appliance_id)
    assert entity.hvac_mode != HVACMode.OFF
    assert entity.hvac_mode in entity.hvac_modes


def test_frigidaire_fan_modes_from_capabilities():
    """Frigidaire fan values AUTO/LOW/MIDDLE/HIGH map to HA fan modes."""
    from homeassistant.components.climate import (
        FAN_AUTO,
        FAN_HIGH,
        FAN_LOW,
        FAN_MEDIUM,
    )

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert set(entity.fan_modes) == {FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH}


def test_frigidaire_fan_mode_reports_auto():
    """Reported AUTO renders as HA FAN_AUTO."""
    from homeassistant.components.climate import FAN_AUTO

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    # fixture state reports fanSpeedSetting AUTO
    assert entity.fan_mode == FAN_AUTO


def test_frigidaire_swing_uses_vertical_swing():
    from homeassistant.components.climate import SWING_OFF, ClimateEntityFeature

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert entity.supported_features & ClimateEntityFeature.SWING_MODE
    # fixture reports verticalSwing OFF
    assert entity.swing_mode == SWING_OFF


async def test_frigidaire_set_swing_uses_vertical_swing():
    from homeassistant.components.climate import SWING_OFF, SWING_ON

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_swing_mode(SWING_ON)
    coord.async_send_command.assert_awaited_with(aid, {"verticalSwing": "ON"})
    await entity.async_set_swing_mode(SWING_OFF)
    coord.async_send_command.assert_awaited_with(aid, {"verticalSwing": "OFF"})


def test_frigidaire_hvac_modes_no_duplicate_off():
    """The mode value OFF flagged {"disabled": true} must not duplicate HVACMode.OFF."""
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert entity.hvac_modes.count(HVACMode.OFF) == 1


# --- Real Electrolux YI09F (fan TURBO, swing flapOscillate, mode AUTO/COOL/FANONLY) ---


def test_real_ac_fan_modes_include_turbo():
    """YI09F fan values LOW/MIDDLE/HIGH/TURBO; TURBO -> 'turbo', HIGH -> 'high'."""
    from homeassistant.components.climate import FAN_HIGH, FAN_LOW, FAN_MEDIUM

    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    assert "turbo" in entity.fan_modes
    assert set(entity.fan_modes) == {FAN_LOW, FAN_MEDIUM, FAN_HIGH, "turbo"}


def test_real_ac_reported_high_shows_as_high():
    from homeassistant.components.climate import FAN_HIGH

    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    # real_ac_state reports fanSpeedSetting HIGH
    assert entity.fan_mode == FAN_HIGH


async def test_real_ac_set_turbo_sends_turbo():
    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_fan_mode("turbo")
    coord.async_send_command.assert_awaited_once_with(
        aid, {"fanSpeedSetting": "TURBO"}
    )


async def test_real_ac_set_high_sends_high():
    from homeassistant.components.climate import FAN_HIGH

    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_fan_mode(FAN_HIGH)
    coord.async_send_command.assert_awaited_once_with(
        aid, {"fanSpeedSetting": "HIGH"}
    )


def test_real_ac_swing_uses_flap_oscillate():
    from homeassistant.components.climate import SWING_ON, ClimateEntityFeature

    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    assert entity.supported_features & ClimateEntityFeature.SWING_MODE
    # real_ac_state reports flapOscillate ON
    assert entity.swing_mode == SWING_ON


async def test_real_ac_set_swing_sends_flap_oscillate():
    from homeassistant.components.climate import SWING_OFF, SWING_ON

    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_swing_mode(SWING_ON)
    coord.async_send_command.assert_awaited_with(aid, {"flapOscillate": "ON"})
    await entity.async_set_swing_mode(SWING_OFF)
    coord.async_send_command.assert_awaited_with(aid, {"flapOscillate": "OFF"})


def test_real_ac_hvac_modes():
    """YI09F mode values AUTO/COOL/FANONLY -> HA modes plus OFF."""
    coord, aid = _coord_real_ac()
    entity = ElectroluxClimate(coord, aid)
    assert HVACMode.OFF in entity.hvac_modes
    assert HVACMode.AUTO in entity.hvac_modes
    assert HVACMode.COOL in entity.hvac_modes
    assert HVACMode.FAN_ONLY in entity.hvac_modes
    assert HVACMode.DRY not in entity.hvac_modes
