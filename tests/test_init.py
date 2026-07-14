"""Tests for the Electrolux AC entry setup/unload lifecycle."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electrolux_ac.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _patch_client():
    """Patch ElectroluxApiClient so no network happens; SSE never yields."""

    async def _never():
        # Yield nothing, then block forever so the background task stays alive
        # without events. Cancellable, so unload cleans it up with no warning.
        if False:
            yield {}
        await asyncio.sleep(3600)

    inst = AsyncMock()
    inst.async_get_appliances = AsyncMock(return_value=_load("appliances.json"))
    inst.async_get_info = AsyncMock(return_value=_load("info.json"))
    inst.async_get_state = AsyncMock(return_value=_load("state.json"))
    inst.async_iter_events = _never
    return patch(
        "custom_components.electrolux_ac.ElectroluxApiClient", return_value=inst
    )


async def test_setup_and_unload_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_ACCESS_TOKEN: "a", CONF_REFRESH_TOKEN: "r"},
    )
    entry.add_to_hass(hass)
    with _patch_client():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.async_entity_ids("climate")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
