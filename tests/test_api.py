# tests/test_api.py
import asyncio
import json
from pathlib import Path

import pytest

from custom_components.electrolux_ac.api import (
    ElectroluxApiClient,
    ElectroluxApiError,
    ElectroluxAuthError,
    ElectroluxCommandError,
    Tokens,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.developer.electrolux.one"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def session(aioclient_mock):
    # Bind the session to aioclient_mock so requests are intercepted by the
    # mock rather than opening real sockets (which PHACC's socket guard blocks).
    s = aioclient_mock.create_session(asyncio.get_running_loop())
    yield s
    await s.close()


async def test_get_appliances(aioclient_mock, session):
    aioclient_mock.get(f"{BASE}/api/v1/appliances", json=_load("appliances.json"))
    client = ElectroluxApiClient(session, "key", "acc", "ref")
    result = await client.async_get_appliances()
    assert result[0]["applianceId"].startswith("999011524")
    # both auth headers were sent
    sent = aioclient_mock.mock_calls[0][3]
    assert sent["x-api-key"] == "key"
    assert sent["Authorization"] == "Bearer acc"


async def test_401_triggers_refresh_and_retry(aioclient_mock, session):
    """The real _request path: first GET 401s → refresh → retry returns data."""
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMockResponse,
    )

    captured = {}

    def on_update(tokens: Tokens):
        captured["tokens"] = tokens

    aioclient_mock.post(
        f"{BASE}/api/v1/token/refresh",
        json={"accessToken": "acc2", "refreshToken": "ref2", "expiresIn": 43200, "tokenType": "Bearer"},
    )

    calls = {"n": 0}

    async def seq(method, url, data):
        calls["n"] += 1
        if calls["n"] == 1:
            return AiohttpClientMockResponse("GET", url, status=401)
        return AiohttpClientMockResponse(
            "GET", url, status=200, json=_load("appliances.json")
        )

    aioclient_mock.get(f"{BASE}/api/v1/appliances", side_effect=seq)

    client = ElectroluxApiClient(session, "key", "acc", "ref", token_updated_cb=on_update)
    result = await client.async_get_appliances()
    assert result[0]["applianceId"].startswith("999011524")
    assert client.tokens == Tokens("acc2", "ref2")
    assert captured["tokens"] == Tokens("acc2", "ref2")


async def test_refresh_failure_raises_auth_error(aioclient_mock, session):
    aioclient_mock.post(f"{BASE}/api/v1/token/refresh", status=401)
    client = ElectroluxApiClient(session, "key", "acc", "ref")
    with pytest.raises(ElectroluxAuthError):
        await client._async_refresh()


async def test_send_command_406_raises_command_error(aioclient_mock, session):
    appliance = "999011524_00:94700001-443E070ABC12"
    aioclient_mock.put(
        f"{BASE}/api/v1/appliances/{appliance}/command",
        status=406,
        json={"error": "developers_0006", "message": "Command validation failed", "detail": "Appliance disconnected"},
    )
    client = ElectroluxApiClient(session, "key", "acc", "ref")
    with pytest.raises(ElectroluxCommandError) as exc:
        await client.async_send_command(appliance, {"mode": "COOL"})
    assert exc.value.detail == "Appliance disconnected"


async def test_send_command_202_is_success(aioclient_mock, session):
    appliance = "999011524_00:94700001-443E070ABC12"
    aioclient_mock.put(
        f"{BASE}/api/v1/appliances/{appliance}/command",
        status=202,
        json={"message": "Appliance already in desired state"},
    )
    client = ElectroluxApiClient(session, "key", "acc", "ref")
    await client.async_send_command(appliance, {"mode": "COOL"})  # no raise
