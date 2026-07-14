"""Sensor platform for Electrolux AC.

Three sensors stay BESPOKE because they need shaping the generic classifier
can't do: the ambient temperature (unit + measurement state class), the filter
state (a curated diagnostic enum with icons/translations), and the Wi-Fi link
quality (read from the nested ``networkInterface`` container the classifier
ignores). Every OTHER read-only capability the classifier routes to
:class:`EntityKind.SENSOR` is generated here as an enum or measurement sensor,
with the noisy informational ones disabled by default to avoid entity sprawl.
"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .capabilities import EntityKind, classify_capability, coerce_value, snake_case
from .const import (
    PROP_AMBIENT_TEMP_C,
    PROP_FILTER_STATE,
    PROP_NETWORK_INTERFACE,
)
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry

# Capabilities already surfaced by a bespoke sensor above; the generic pass must
# not double-create them.
_BESPOKE_NAMES = frozenset({PROP_AMBIENT_TEMP_C, PROP_FILTER_STATE, PROP_NETWORK_INTERFACE})

# Informational read sensors that are useful but noisy — created disabled so the
# user can opt in rather than have the device page cluttered by default.
_DISABLED_BY_DEFAULT = frozenset(
    {"applianceState", "currentEnergyUsePercent", "evaporatorDefrostState"}
)


def build_sensors(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[SensorEntity]:
    appliance = coordinator.data[appliance_id]
    sensors: list[SensorEntity] = []
    # --- bespoke ---
    if PROP_AMBIENT_TEMP_C in appliance.reported:
        sensors.append(AmbientTemperatureSensor(coordinator, appliance_id))
    if PROP_FILTER_STATE in appliance.capabilities:
        sensors.append(FilterStateSensor(coordinator, appliance_id))
    if PROP_NETWORK_INTERFACE in appliance.reported:
        sensors.append(LinkQualitySensor(coordinator, appliance_id))
    # --- generic read sensors from the classifier ---
    for name, cap in appliance.capabilities.items():
        if name in _BESPOKE_NAMES:
            continue
        kind, spec = classify_capability(name, cap)
        if kind is not EntityKind.SENSOR:
            continue
        sensors.append(GenericSensor(coordinator, appliance_id, name, spec))
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


class GenericSensor(ElectroluxEntity, SensorEntity):
    """A read-only capability surfaced generically.

    Enum caps (spec has ``values``) become an ENUM sensor whose state is the
    lowercased token; numeric caps (spec has ``min``/``max``) become a
    measurement sensor whose state is the coerced number.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, appliance_id, prop: str, spec: dict) -> None:
        super().__init__(coordinator, appliance_id)
        self._prop = prop
        key = snake_case(prop)
        self._attr_translation_key = key
        self._attr_unique_id = f"{appliance_id}_{key}"
        self._is_enum = "values" in spec
        if self._is_enum:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = spec["values"]
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if prop in _DISABLED_BY_DEFAULT:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        raw = self.appliance.reported.get(self._prop)
        if raw is None:
            return None
        if self._is_enum:
            return str(raw).lower()
        return coerce_value(raw)
