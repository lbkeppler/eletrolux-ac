"""Data models for the Electrolux AC integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import ElectroluxCoordinator

type ElectroluxConfigEntry = ConfigEntry["ElectroluxCoordinator"]


@dataclass
class ApplianceData:
    """Normalized snapshot of one appliance."""

    appliance_id: str
    name: str
    brand: str
    model: str
    sw_version: str | None
    capabilities: dict[str, Any]
    reported: dict[str, Any] = field(default_factory=dict)
    connection_state: str = "unknown"
