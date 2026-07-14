"""Select platform for Electrolux AC (no selects for the AC in v1; future-proof)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .models import ElectroluxConfigEntry

# No multi-value readwrite string capabilities that aren't covered by climate.
SELECT_CAPABILITIES: tuple = ()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([])
