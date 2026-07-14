"""Switch platform for Electrolux AC."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    PROP_CLEAN_AIR_MODE,
    PROP_DISPLAY_LIGHT,
    PROP_SCHEDULER_MODE,
    PROP_SLEEP_MODE,
    PROP_UI_LOCK_MODE,
)
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


@dataclass(frozen=True)
class SwitchSpec:
    prop: str
    translation_key: str
    on_value: Any
    off_value: Any


SWITCHES: tuple[SwitchSpec, ...] = (
    SwitchSpec(PROP_SLEEP_MODE, "sleep_mode", "ON", "OFF"),
    SwitchSpec(PROP_CLEAN_AIR_MODE, "clean_air_mode", "ON", "OFF"),
    SwitchSpec(PROP_UI_LOCK_MODE, "ui_lock_mode", "ON", "OFF"),
    SwitchSpec(PROP_SCHEDULER_MODE, "scheduler_mode", "ON", "OFF"),
    SwitchSpec(PROP_DISPLAY_LIGHT, "display_light", "DISPLAY_LIGHT_1", "DISPLAY_LIGHT_0"),
)


def build_switches(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[SwitchEntity]:
    caps = coordinator.data[appliance_id].capabilities
    return [
        ElectroluxSwitch(coordinator, appliance_id, spec)
        for spec in SWITCHES
        if spec.prop in caps and caps[spec.prop].get("access") == "readwrite"
    ]


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

    def __init__(self, coordinator, appliance_id, spec: SwitchSpec) -> None:
        super().__init__(coordinator, appliance_id)
        self._spec = spec
        self._attr_translation_key = spec.translation_key
        self._attr_unique_id = f"{appliance_id}_{spec.translation_key}"

    @property
    def is_on(self) -> bool | None:
        val = self.appliance.reported.get(self._spec.prop)
        # uiLockMode reports a JSON bool; the others report "ON"/"OFF" (or
        # DISPLAY_LIGHT_0/1) strings — handle the bool case first.
        if isinstance(val, bool):
            return val
        return val == self._spec.on_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {self._spec.prop: self._spec.on_value}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {self._spec.prop: self._spec.off_value}
        )
