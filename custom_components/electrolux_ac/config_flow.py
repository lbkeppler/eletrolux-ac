"""Config flow for Electrolux AC."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import jwt
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ElectroluxApiClient, ElectroluxApiError, ElectroluxAuthError
from .const import CONF_ACCESS_TOKEN, CONF_API_KEY, CONF_REFRESH_TOKEN, DOMAIN

STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_ACCESS_TOKEN): str,
        vol.Required(CONF_REFRESH_TOKEN): str,
    }
)


def _account_id(access_token: str) -> str:
    payload = jwt.decode(access_token, options={"verify_signature": False})
    return str(payload["sub"])


class ElectroluxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Electrolux AC."""

    VERSION = 1

    async def _validate(self, user_input: dict[str, Any]) -> tuple[str | None, dict]:
        """Return (account_id, errors)."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)
        client = ElectroluxApiClient(
            session,
            user_input[CONF_API_KEY],
            user_input[CONF_ACCESS_TOKEN],
            user_input[CONF_REFRESH_TOKEN],
        )
        try:
            await client.async_get_appliances()
        except ElectroluxAuthError:
            errors["base"] = "invalid_auth"
            return None, errors
        except ElectroluxApiError:
            errors["base"] = "cannot_connect"
            return None, errors
        try:
            return _account_id(user_input[CONF_ACCESS_TOKEN]), errors
        except Exception:  # noqa: BLE001 — malformed token
            errors["base"] = "invalid_auth"
            return None, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account_id, errors = await self._validate(user_input)
            if account_id is not None:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Electrolux AC", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=STEP_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account_id, errors = await self._validate(user_input)
            if account_id is not None:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_mismatch("wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=STEP_SCHEMA, errors=errors
        )
