"""Select platform for Electrolux AC — generated from the capability classifier.

A capability with a multi-value (>2) ``readwrite`` value set that climate does
not consume classifies as :class:`EntityKind.SELECT`. YI09F exposes
``flapPosition`` (7 ``POSITION_*`` values); the Frigidaire fixture has none.

Two representation quirks are handled per entity:

* HA options must be slugs, so we expose the lowercased value keys
  (``position_0`` …). A map back to the original API token drives writes.
* ``flapPosition`` is declared ``type: number`` yet carries ``POSITION_N``
  tokens, and the device *reports* the bare int (``0``). So the read path
  coerces the reported value to an int and matches it against the coerced
  option index, and the write path sends the int index for numeric-typed caps
  (the raw token otherwise).
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .capabilities import EntityKind, classify_capability, coerce_value, snake_case
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


def build_selects(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[SelectEntity]:
    caps = coordinator.data[appliance_id].capabilities
    reported = coordinator.data[appliance_id].reported
    selects: list[SelectEntity] = []
    for name, cap in caps.items():
        kind, spec = classify_capability(name, cap)
        if kind is EntityKind.SELECT:
            # R3: a phantom control (classifies as a select but is never in the
            # reported state) has no valid read/write target — skip it.
            if name not in reported:
                continue
            selects.append(ElectroluxSelect(coordinator, appliance_id, name, cap, spec))
    return selects


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        e for aid in coordinator.data for e in build_selects(coordinator, aid)
    )


class ElectroluxSelect(ElectroluxEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, appliance_id, prop: str, cap: dict, spec: dict) -> None:
        super().__init__(coordinator, appliance_id)
        self._prop = prop
        key = snake_case(prop)
        self._attr_translation_key = key
        self._attr_unique_id = f"{appliance_id}_{key}"
        self._attr_options = spec["values"]
        # Map each lowercased option slug back to the raw API value key.
        self._option_to_token: dict[str, str] = {
            token.lower(): token for token in cap.get("values", {})
        }
        # A capability declared type=number (e.g. flapPosition) is written with
        # the int index; a plain string enum is written with the raw token.
        self._numeric = cap.get("type") == "number"

    @property
    def current_option(self) -> str | None:
        raw = self.appliance.reported.get(self._prop)
        if raw is None:
            return None
        # Direct token match (e.g. reported "POSITION_3").
        token = str(raw)
        if token.lower() in self._option_to_token:
            return token.lower()
        # Coerce-tolerant match: reported bare int 3 <-> POSITION_3.
        coerced = coerce_value(raw)
        if coerced is not None:
            for option, tok in self._option_to_token.items():
                if coerce_value(tok) == coerced:
                    return option
        return None

    async def async_select_option(self, option: str) -> None:
        token = self._option_to_token.get(option, option)
        if self._numeric:
            index = coerce_value(token)
            value = index if index is not None else token
        else:
            value = token
        await self.coordinator.async_send_command(
            self._appliance_id, {self._prop: value}
        )
