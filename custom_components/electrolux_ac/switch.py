"""Switch platform for Electrolux AC — generated from the capability classifier.

Every capability an appliance exposes is routed by ``classify_capability``; the
ones that come back :class:`EntityKind.SWITCH` (readwrite, boolean-like value
set, not consumed by climate) become an :class:`ElectroluxSwitch` here. On/off
API values come from the classifier's spec, so a switch works whether the
device speaks ``{ON,OFF}``, ``{0,1}`` or ``{DISPLAY_LIGHT_0,DISPLAY_LIGHT_1}``.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .capabilities import EntityKind, classify_capability, snake_case
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


def build_switches(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[SwitchEntity]:
    caps = coordinator.data[appliance_id].capabilities
    reported = coordinator.data[appliance_id].reported
    switches: list[SwitchEntity] = []
    for name, cap in caps.items():
        kind, spec = classify_capability(name, cap)
        if kind is EntityKind.SWITCH:
            # R3: a phantom control (classifies as a switch but is never in the
            # reported state, e.g. YI09F batchSchedulerMode) has no valid
            # read/write target — skip it.
            if name not in reported:
                continue
            switches.append(ElectroluxSwitch(coordinator, appliance_id, name, spec))
    return switches


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        e for aid in coordinator.data for e in build_switches(coordinator, aid)
    )


class ElectroluxSwitch(ElectroluxEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, appliance_id, prop: str, spec: dict) -> None:
        super().__init__(coordinator, appliance_id)
        self._prop = prop
        self._on_value = spec["on"]
        self._off_value = spec["off"]
        key = snake_case(prop)
        self._attr_translation_key = key
        self._attr_unique_id = f"{appliance_id}_{key}"

    @property
    def is_on(self) -> bool | None:
        val = self.appliance.reported.get(self._prop)
        # uiLockMode reports a JSON bool; the others report "ON"/"OFF" (or
        # DISPLAY_LIGHT_0/1, "0"/"1") strings — handle the bool case first.
        if isinstance(val, bool):
            return val
        # Some numeric-token caps report the int (soundVolume -> 1) while the
        # on/off spec keys are strings ("1"/"0"); compare as strings so both
        # representations match.
        if val is None:
            return None
        return str(val) == str(self._on_value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {self._prop: self._on_value}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {self._prop: self._off_value}
        )
