"""Sensor platform for Electrolux AC."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    PROP_AMBIENT_TEMP_C,
    PROP_FILTER_STATE,
    PROP_NETWORK_INTERFACE,
)
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


def build_sensors(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[SensorEntity]:
    appliance = coordinator.data[appliance_id]
    sensors: list[SensorEntity] = []
    if PROP_AMBIENT_TEMP_C in appliance.reported:
        sensors.append(AmbientTemperatureSensor(coordinator, appliance_id))
    if PROP_FILTER_STATE in appliance.capabilities:
        sensors.append(FilterStateSensor(coordinator, appliance_id))
    if PROP_NETWORK_INTERFACE in appliance.reported:
        sensors.append(LinkQualitySensor(coordinator, appliance_id))
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        e for aid in coordinator.data for e in build_sensors(coordinator, aid)
    )


class AmbientTemperatureSensor(ElectroluxEntity, SensorEntity):
    _attr_translation_key = "ambient_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_ambient_temperature"

    @property
    def native_value(self) -> float | None:
        return self.appliance.reported.get(PROP_AMBIENT_TEMP_C)


class FilterStateSensor(ElectroluxEntity, SensorEntity):
    _attr_translation_key = "filter_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_filter_state"
        values = self.appliance.capabilities[PROP_FILTER_STATE].get("values", {})
        self._attr_options = [v.lower() for v in values]

    @property
    def native_value(self) -> str | None:
        val = self.appliance.reported.get(PROP_FILTER_STATE)
        return val.lower() if isinstance(val, str) else None


class LinkQualitySensor(ElectroluxEntity, SensorEntity):
    _attr_translation_key = "link_quality"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_link_quality"

    @property
    def native_value(self) -> str | None:
        return self.appliance.reported.get(PROP_NETWORK_INTERFACE, {}).get(
            "linkQualityIndicator"
        )
