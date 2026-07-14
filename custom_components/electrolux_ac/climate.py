"""Climate platform for Electrolux AC."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TEMPERATURE,
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .capabilities import SWING_KEYS
from .const import (
    FAN_DISPLAY,
    HVAC_MODE_MAP,
    HVAC_MODE_MAP_REVERSE,
    PROP_AMBIENT_TEMP_C,
    PROP_AMBIENT_TEMP_F,
    PROP_APPLIANCE_STATE,
    PROP_FAN_SPEED,
    PROP_MODE,
    PROP_TARGET_TEMP_C,
    PROP_TARGET_TEMP_F,
    PROP_TEMP_REPRESENTATION,
    STATE_OFF,
    UNIT_FAHRENHEIT,
)
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ElectroluxClimate(coordinator, aid) for aid in coordinator.data
    )


class ElectroluxClimate(ElectroluxEntity, ClimateEntity):
    """An Electrolux air conditioner."""

    _attr_name = None
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = appliance_id
        caps = self.appliance.capabilities

        modes: list[HVACMode] = []
        for api_mode, spec in caps.get(PROP_MODE, {}).get("values", {}).items():
            # Skip pseudo-values the appliance flags as disabled (e.g.
            # Frigidaire's OFF: {"disabled": true}) — HVACMode.OFF is added
            # separately, so honouring it would only duplicate it.
            if isinstance(spec, dict) and spec.get("disabled"):
                continue
            if api_mode in HVAC_MODE_MAP:
                modes.append(HVAC_MODE_MAP[api_mode])
        modes.append(HVACMode.OFF)
        self._attr_hvac_modes = list(dict.fromkeys(modes))

        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if PROP_TARGET_TEMP_C in caps:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE

        # Fan: build per-appliance forward/reverse maps from the appliance's own
        # fanSpeedSetting values, in API order. Known tokens (AUTO/LOW/MIDDLE/
        # HIGH) use the HA canonical fan strings via FAN_DISPLAY; unknown tokens
        # (TURBO, and anything future) fall back to the lowercased token so they
        # are never dropped. We never use the lossy module-level FAN_MODE_MAP.
        self._fan_forward: dict[str, str] = {}
        self._fan_reverse: dict[str, str] = {}
        if PROP_FAN_SPEED in caps:
            for token in caps[PROP_FAN_SPEED].get("values", {}):
                ha_mode = FAN_DISPLAY.get(token, token.lower())
                self._fan_forward[token] = ha_mode
                self._fan_reverse[ha_mode] = token
            if self._fan_forward:
                features |= ClimateEntityFeature.FAN_MODE
                self._attr_fan_modes = list(self._fan_forward.values())

        # Swing: pick the first swing key the appliance actually exposes as a
        # readwrite {ON,OFF} control (Frigidaire: verticalSwing; YI09F:
        # flapOscillate). Only enable SWING_MODE if one is found.
        self._swing_prop: str | None = None
        for key in SWING_KEYS:
            cap = caps.get(key)
            if not isinstance(cap, dict):
                continue
            if cap.get("access") != "readwrite":
                continue
            if set(cap.get("values", {})) != {"ON", "OFF"}:
                continue
            self._swing_prop = key
            break
        if self._swing_prop is not None:
            features |= ClimateEntityFeature.SWING_MODE
            self._attr_swing_modes = [SWING_ON, SWING_OFF]

        self._attr_supported_features = features

    @property
    def _fahrenheit(self) -> bool:
        return self.appliance.reported.get(PROP_TEMP_REPRESENTATION) == UNIT_FAHRENHEIT

    @property
    def temperature_unit(self) -> str:
        return (
            UnitOfTemperature.FAHRENHEIT
            if self._fahrenheit
            else UnitOfTemperature.CELSIUS
        )

    @property
    def _temp_cap(self) -> dict:
        key = PROP_TARGET_TEMP_F if self._fahrenheit else PROP_TARGET_TEMP_C
        return self.appliance.capabilities.get(key, {})

    @property
    def min_temp(self) -> float:
        return self._temp_cap.get("min", super().min_temp)

    @property
    def max_temp(self) -> float:
        return self._temp_cap.get("max", super().max_temp)

    @property
    def target_temperature_step(self) -> float | None:
        return self._temp_cap.get("step")

    @property
    def current_temperature(self) -> float | None:
        key = PROP_AMBIENT_TEMP_F if self._fahrenheit else PROP_AMBIENT_TEMP_C
        return self.appliance.reported.get(key)

    @property
    def target_temperature(self) -> float | None:
        key = PROP_TARGET_TEMP_F if self._fahrenheit else PROP_TARGET_TEMP_C
        return self.appliance.reported.get(key)

    @property
    def hvac_mode(self) -> HVACMode:
        reported = self.appliance.reported
        if reported.get(PROP_APPLIANCE_STATE) == STATE_OFF:
            return HVACMode.OFF
        api_mode = reported.get(PROP_MODE)
        if api_mode in (None, STATE_OFF):
            return HVACMode.OFF
        mapped = HVAC_MODE_MAP.get(api_mode)
        if mapped is not None:
            return mapped
        # Running with a mode we don't map (e.g. a region-specific value):
        # don't render an on AC as Off. Prefer any non-OFF mode we support.
        _LOGGER.debug("Unmapped AC mode %r while running", api_mode)
        for mode in self.hvac_modes:
            if mode != HVACMode.OFF:
                return mode
        return HVACMode.OFF

    @property
    def fan_mode(self) -> str | None:
        token = self.appliance.reported.get(PROP_FAN_SPEED)
        if token is None:
            return None
        # Per-appliance map; unknown reported tokens fall back to lowercased so
        # a value outside the capability list is still shown, never dropped.
        return self._fan_forward.get(token, str(token).lower())

    @property
    def swing_mode(self) -> str | None:
        if self._swing_prop is None:
            return None
        val = self.appliance.reported.get(self._swing_prop)
        if val is None:
            return None
        return SWING_ON if val == "ON" else SWING_OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_command(
                self._appliance_id, {"executeCommand": "OFF"}
            )
            return
        await self.coordinator.async_send_command(
            self._appliance_id,
            {"executeCommand": "ON", "mode": HVAC_MODE_MAP_REVERSE[hvac_mode]},
        )

    async def async_turn_on(self) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {"executeCommand": "ON"}
        )

    async def async_turn_off(self) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id, {"executeCommand": "OFF"}
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        command: dict[str, Any] = {}
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            if hvac_mode == HVACMode.OFF:
                command["executeCommand"] = "OFF"
            else:
                command["executeCommand"] = "ON"
                command["mode"] = HVAC_MODE_MAP_REVERSE[hvac_mode]
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            key = PROP_TARGET_TEMP_F if self._fahrenheit else PROP_TARGET_TEMP_C
            command[key] = temp
        if command:
            await self.coordinator.async_send_command(self._appliance_id, command)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        token = self._fan_reverse.get(fan_mode)
        if token is None:
            _LOGGER.warning("Unknown fan mode %r for %s", fan_mode, self._appliance_id)
            return
        await self.coordinator.async_send_command(
            self._appliance_id, {PROP_FAN_SPEED: token}
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if self._swing_prop is None:
            return
        await self.coordinator.async_send_command(
            self._appliance_id,
            {self._swing_prop: "ON" if swing_mode == SWING_ON else "OFF"},
        )
