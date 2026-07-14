"""Base entity for Electrolux AC."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONNECTION_CONNECTED, DOMAIN
from .coordinator import ElectroluxCoordinator
from .models import ApplianceData


class ElectroluxEntity(CoordinatorEntity[ElectroluxCoordinator]):
    """Common base for all Electrolux entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ElectroluxCoordinator, appliance_id: str) -> None:
        super().__init__(coordinator)
        self._appliance_id = appliance_id
        appliance = coordinator.data[appliance_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance_id)},
            name=appliance.name,
            manufacturer=appliance.brand.title(),
            model=appliance.model,
            sw_version=appliance.sw_version,
        )

    @property
    def appliance(self) -> ApplianceData:
        return self.coordinator.data[self._appliance_id]

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance_id in self.coordinator.data
            and self.appliance.connection_state == CONNECTION_CONNECTED
        )
