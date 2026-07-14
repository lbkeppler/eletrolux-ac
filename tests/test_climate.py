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
