"""Binary sensor platform for Electrolux AC.

The connectivity sensor is bespoke (it must stay available while the appliance
is disconnected so it can report "disconnected"). Every read-only boolean-like
capability the classifier routes to :class:`EntityKind.BINARY_SENSOR` (YI09F's
``cleanAirMode``, which is ``access: read`` here) is generated as a generic
binary sensor, disabled by default to avoid entity sprawl.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .capabilities import EntityKind, classify_capability, snake_case
from .const import CONNECTION_CONNECTED
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


def build_binary_sensors(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[BinarySensorEntity]:
    caps = coordinator.data[appliance_id].capabilities
    sensors: list[BinarySensorEntity] = []
    for name, cap in caps.items():
        kind, spec = classify_capability(name, cap)
        if kind is EntityKind.BINARY_SENSOR:
            sensors.append(
                GenericBinarySensor(coordinator, appliance_id, name, spec)
            )
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for aid in coordinator.data:
        entities.append(ElectroluxConnectivity(coordinator, aid))
        entities.extend(build_binary_sensors(coordinator, aid))
    async_add_entities(entities)


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


class GenericBinarySensor(ElectroluxEntity, BinarySensorEntity):
    """A read-only boolean-like capability surfaced generically."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, appliance_id, prop: str, spec: dict) -> None:
        super().__init__(coordinator, appliance_id)
        self._prop = prop
        self._on_value = spec["on"]
        key = snake_case(prop)
        self._attr_translation_key = key
        self._attr_unique_id = f"{appliance_id}_{key}"

    @property
    def is_on(self) -> bool | None:
        val = self.appliance.reported.get(self._prop)
        if isinstance(val, bool):
            return val
        if val is None:
            return None
        return str(val) == str(self._on_value)
