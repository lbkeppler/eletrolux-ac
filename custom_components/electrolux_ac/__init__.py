"""The Electrolux AC integration."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ElectroluxApiClient, Tokens
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import ElectroluxCoordinator
from .models import ElectroluxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: ElectroluxConfigEntry
) -> bool:
    """Set up Electrolux AC from a config entry."""
    session = async_get_clientsession(hass)

    def _persist_tokens(tokens: Tokens) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: tokens.access_token,
                CONF_REFRESH_TOKEN: tokens.refresh_token,
            },
        )

    client = ElectroluxApiClient(
        session,
        entry.data[CONF_API_KEY],
        entry.data[CONF_ACCESS_TOKEN],
        entry.data[CONF_REFRESH_TOKEN],
        token_updated_cb=_persist_tokens,
    )

    coordinator = ElectroluxCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass,
        coordinator.async_run_sse(),
        name=f"{DOMAIN}_sse_{entry.entry_id}",
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ElectroluxConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
