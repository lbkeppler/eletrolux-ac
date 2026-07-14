import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electrolux_ac.api import (
    ElectroluxApiError,
    ElectroluxAuthError,
    ElectroluxCommandError,
)
from custom_components.electrolux_ac.const import DOMAIN
from custom_components.electrolux_ac.coordinator import (
    ElectroluxCoordinator,
    apply_sse_event,
    parse_appliance,
)
from custom_components.electrolux_ac.models import ApplianceData

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_appliance():
    data = parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )
    assert data.appliance_id == "999011524_00:94700001-443E070ABC12"
    assert data.name == "Ar Escritorio"
    assert data.brand == "FRIGIDAIRE"
    assert "GHPC132AB1" in data.model
    assert data.sw_version == "v1.9.1_srac"
    assert data.connection_state == "connected"
    assert data.reported["mode"] == "COOL"
    assert "mode" in data.capabilities


def _base():
    return parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )


def test_apply_sse_simple_property():
    data = _base()
    updated = apply_sse_event(data, {"applianceId": "x", "property": "mode", "value": "AUTO"})
    assert updated.reported["mode"] == "AUTO"
    # original unchanged (returns a new object)
    assert data.reported["mode"] == "COOL"


def test_apply_sse_nested_path():
    data = _base()
    updated = apply_sse_event(
        data,
        {"applianceId": "x", "property": "networkInterface/linkQualityIndicator", "value": "GOOD"},
    )
    assert updated.reported["networkInterface"]["linkQualityIndicator"] == "GOOD"
    # sibling key preserved
    assert updated.reported["networkInterface"]["swVersion"] == "v1.9.1_srac"


def test_apply_sse_connection_state():
    data = _base()
    updated = apply_sse_event(data, {"applianceId": "x", "property": "connectivityState", "value": "disconnected"})
    assert updated.connection_state == "disconnected"


def test_apply_sse_missing_fields_noop():
    data = _base()
    assert apply_sse_event(data, {"applianceId": "x"}) is data
    assert apply_sse_event(data, {"property": "mode"}) is data


def _mock_client():
    client = MagicMock()
    client.async_get_appliances = AsyncMock(return_value=_load("appliances.json"))
    client.async_get_info = AsyncMock(return_value=_load("info.json"))
    client.async_get_state = AsyncMock(return_value=_load("state.json"))
    client.async_send_command = AsyncMock()
    return client


def _entry():
    return MockConfigEntry(domain=DOMAIN, data={"api_key": "k", "access_token": "a", "refresh_token": "r"})


async def test_first_refresh_builds_ac_map(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    coord = ElectroluxCoordinator(hass, entry, _mock_client())
    data = await coord._async_update_data()
    aid = "999011524_00:94700001-443E070ABC12"
    assert aid in data
    assert data[aid].reported["mode"] == "COOL"


async def test_discovery_falls_back_to_device_type(hass):
    """An appliance not typed 'AC' in the list is kept if info.deviceType is an AC."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    aid = "999011524_00:94700001-443E070ABC12"
    # list entry reports a non-"AC" applianceType, but /info says AIR_CONDITIONER
    listing = [{**_load("appliances.json")[0], "applianceType": "OTHER"}]
    client.async_get_appliances = AsyncMock(return_value=listing)
    coord = ElectroluxCoordinator(hass, entry, client)
    data = await coord._async_update_data()
    assert aid in data  # kept via deviceType fallback (PORTABLE_AIR_CONDITIONER)


async def test_discovery_no_ac_logs_warning(hass, caplog):
    """Zero ACs discovered → warning logged, empty data returned."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    listing = [{**_load("appliances.json")[0], "applianceType": "WM"}]
    client.async_get_appliances = AsyncMock(return_value=listing)
    # info without an AC deviceType
    client.async_get_info = AsyncMock(
        return_value={"applianceInfo": {"deviceType": "WASHING_MACHINE", "brand": "AEG", "model": "X"}, "capabilities": {}}
    )
    coord = ElectroluxCoordinator(hass, entry, client)
    data = await coord._async_update_data()
    assert data == {}
    assert "No AC appliances found" in caplog.text


async def test_auth_error_maps_to_config_entry_auth_failed(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    client.async_get_appliances = AsyncMock(side_effect=ElectroluxAuthError("bad"))
    coord = ElectroluxCoordinator(hass, entry, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_api_error_maps_to_update_failed(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    client.async_get_appliances = AsyncMock(side_effect=ElectroluxApiError("boom"))
    coord = ElectroluxCoordinator(hass, entry, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_send_command_optimistic_update(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    coord = ElectroluxCoordinator(hass, entry, _mock_client())
    coord.data = await coord._async_update_data()
    aid = "999011524_00:94700001-443E070ABC12"
    await coord.async_send_command(aid, {"mode": "AUTO"})
    assert coord.data[aid].reported["mode"] == "AUTO"


async def test_send_command_406_raises_home_assistant_error(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    client.async_send_command = AsyncMock(
        side_effect=ElectroluxCommandError("rejected", detail="Appliance disconnected")
    )
    coord = ElectroluxCoordinator(hass, entry, client)
    coord.data = await coord._async_update_data()
    aid = "999011524_00:94700001-443E070ABC12"
    with pytest.raises(HomeAssistantError):
        await coord.async_send_command(aid, {"mode": "COOL"})


async def test_sse_loop_applies_event(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    aid = "999011524_00:94700001-443E070ABC12"

    async def one_event():
        yield {"applianceId": aid, "property": "mode", "value": "DRY"}
        # end the stream so the loop would reconnect; we cancel before that.
        await asyncio.sleep(3600)
        yield {}

    client.async_iter_events = one_event
    coord = ElectroluxCoordinator(hass, entry, client)
    coord.data = await coord._async_update_data()
    task = asyncio.create_task(coord.async_run_sse())
    await asyncio.sleep(0.05)
    assert coord.data[aid].reported["mode"] == "DRY"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
