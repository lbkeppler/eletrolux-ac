"""Binary sensor platform for Electrolux AC."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONNECTION_CONNECTED
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ElectroluxConnectivity(coordinator, aid) for aid in coordinator.data
    )


class ElectroluxConnectivity(ElectroluxEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_connectivity"

    @property
    def available(self) -> bool:
        # Stay available even when the appliance is disconnected, so this
        # sensor can actually report "disconnected".
        return (
            self.coordinator.last_update_success
            and self._appliance_id in self.coordinator.data
        )

    @property
    def is_on(self) -> bool:
        return self.appliance.connection_state == CONNECTION_CONNECTED
