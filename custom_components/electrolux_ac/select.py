"""Select platform for Electrolux AC (no selects for the AC in v1; future-proof)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .models import ElectroluxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    # The AC exposes no multi-value readwrite string capability that isn't
    # already covered by the climate entity (mode → HVAC, fanSpeed → fan), so
    # this platform intentionally creates no entities. It exists so the select
    # platform is registered and future appliances can add selects here.
    async_add_entities([])
