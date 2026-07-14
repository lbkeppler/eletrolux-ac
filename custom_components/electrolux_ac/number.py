"""Number platform for Electrolux AC — generated from the capability classifier.

A capability with a numeric ``min``/``max`` range and ``readwrite`` access (and
NO ``values`` set — those route to a select) classifies as
:class:`EntityKind.NUMBER`. YI09F exposes two: ``displayLight`` (0-100) and
``stopTime`` (0-86400). The reported value can be either a raw number or an
enum token like ``"DISPLAY_LIGHT_0"``, so ``native_value`` runs it through the
tolerant ``coerce_value`` helper.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .capabilities import EntityKind, classify_capability, coerce_value, snake_case
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


def build_numbers(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[NumberEntity]:
    caps = coordinator.data[appliance_id].capabilities
    numbers: list[NumberEntity] = []
    for name, cap in caps.items():
        kind, spec = classify_capability(name, cap)
        if kind is EntityKind.NUMBER:
            numbers.append(ElectroluxNumber(coordinator, appliance_id, name, spec))
    return numbers


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        e for aid in coordinator.data for e in build_numbers(coordinator, aid)
    )


class ElectroluxNumber(ElectroluxEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, appliance_id, prop: str, spec: dict) -> None:
        super().__init__(coordinator, appliance_id)
        self._prop = prop
        key = snake_case(prop)
        self._attr_translation_key = key
        self._attr_unique_id = f"{appliance_id}_{key}"
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]

    @property
    def native_value(self) -> float | None:
        return coerce_value(self.appliance.reported.get(self._prop))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {self._prop: int(value)}
        )
