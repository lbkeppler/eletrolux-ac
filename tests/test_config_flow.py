from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electrolux_ac.api import ElectroluxApiError, ElectroluxAuthError
from custom_components.electrolux_ac.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

# A real HS256 JWT whose payload is {"sub": "acct-123"} — decoded with
# verify_signature=False, so the signing key is irrelevant.
# Regenerate with: jwt.encode({"sub": "acct-123"}, "secret", algorithm="HS256")
FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJhY2N0LTEyMyJ9"
    ".8ezfcH2uNBhzSc96Ivqt5i3wqh3hCmFqzCCe6kAHaOY"
)

USER_INPUT = {
    CONF_API_KEY: "k",
    CONF_ACCESS_TOKEN: FAKE_JWT,
    CONF_REFRESH_TOKEN: "r",
}


def _patch_ok():
    inst = AsyncMock()
    inst.async_get_appliances = AsyncMock(return_value=[])
    return patch(
        "custom_components.electrolux_ac.config_flow.ElectroluxApiClient",
        return_value=inst,
    )


async def test_user_flow_success(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with _patch_ok(), patch(
        "custom_components.electrolux_ac.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT


async def test_user_flow_invalid_auth(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    inst = AsyncMock()
    inst.async_get_appliances = AsyncMock(side_effect=ElectroluxAuthError("bad"))
    with patch(
        "custom_components.electrolux_ac.config_flow.ElectroluxApiClient",
        return_value=inst,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    inst = AsyncMock()
    inst.async_get_appliances = AsyncMock(side_effect=ElectroluxApiError("net"))
    with patch(
        "custom_components.electrolux_ac.config_flow.ElectroluxApiClient",
        return_value=inst,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_account_aborts(hass):
    existing = MockConfigEntry(domain=DOMAIN, unique_id="acct-123", data=USER_INPUT)
    existing.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_ok():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
