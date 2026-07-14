# Electrolux AC — Home Assistant Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom component (`electrolux_ac`) that controls Electrolux air conditioners through the official Electrolux Group Developer API, with a full device (climate + sensors + switches + selects + connectivity) and real-time SSE updates.

**Architecture:** A thin `aiohttp` API client wraps the Electrolux REST endpoints and the SSE livestream, handling JWT refresh with rotation. A `DataUpdateCoordinator` holds per-appliance state, receiving instant updates via an SSE background task (`cloud_push`) and reconciling every 5 minutes via polling. Entities are generated dynamically from each appliance's reported `capabilities`, so only controls the device actually supports are created.

**Tech Stack:** Python 3.13+, Home Assistant custom component, `aiohttp` (bundled with HA), `PyJWT` (bundled with HA), `pytest` + `pytest-homeassistant-custom-component`, HACS + GitHub Actions (hassfest + HACS validate).

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec and the verified HA-API research.

- **Domain:** `electrolux_ac` — all files live under `custom_components/electrolux_ac/`.
- **API base URL:** `https://api.developer.electrolux.one`
- **Auth headers on EVERY request:** `x-api-key: <api_key>` and `Authorization: Bearer <access_token>`.
- **Token refresh:** `POST /api/v1/token/refresh` with body `{"refreshToken": "<refresh_token>"}` → `{accessToken, refreshToken, expiresIn, tokenType}`. The refresh token **rotates** — always persist the new pair. On `401`, refresh once and retry; if refresh fails, raise `ConfigEntryAuthFailed`.
- **SSE:** GET the URL from `GET /api/v1/configurations/livestream` with the two auth headers; stream lines, parse `data: <json>`; each event is `{"applianceId", "property", "value"}`. `property == "connectionState"` or `"connectivityState"` → connection status; other properties apply at the `/`-split path inside `properties.reported`. Reconnect with a 10 s backoff; one SSE channel per API key (API limit).
- **API limits (free tier):** 10 calls/s, 5 concurrent calls, 5000 calls/day, 1 concurrent SSE channel. Poll interval = 5 min.
- **`manifest.json` MUST include** (custom-component requirements verified in research): `domain`, `name`, `codeowners: ["@lbkeppler"]`, `config_flow: true`, `dependencies: []`, `documentation`, `issue_tracker`, `integration_type: "hub"`, `iot_class: "cloud_push"`, `requirements: []` (aiohttp + PyJWT ship with HA), and `version` (mandatory for custom integrations, AwesomeVersion-parseable, start at `"0.1.0"`).
- **Translations:** custom components use `translations/en.json` (and `translations/pt-BR.json`), **NOT** `strings.json`. Entity/state translation keys are snake_case.
- **Naming:** `_attr_has_entity_name = True` on all entities; the climate entity (main feature) uses `_attr_name = None`; every secondary entity uses `_attr_translation_key`.
- **Config entry storage:** use `entry.runtime_data` (type alias **must** be suffixed `ConfigEntry`: `ElectroluxConfigEntry = ConfigEntry[ElectroluxCoordinator]`). Never mutate `entry.data` directly — use `hass.config_entries.async_update_entry(...)`.
- **Coordinator:** always pass `config_entry=entry` to `DataUpdateCoordinator.__init__`; use `always_update=False`.
- **Repo secrets:** `.env` and `*.har` are already in `.gitignore` (they contain real tokens) — never stage or commit them.
- **TDD:** every task writes the failing test first, watches it fail, implements minimally, watches it pass, commits. Commit after every green task.
- **GitHub repo:** `https://github.com/lbkeppler/eletrolux-ac`.

---

## File Structure

```
eletrolux-ac/
├── custom_components/electrolux_ac/
│   ├── __init__.py          # entry setup: client, coordinator, SSE task, forward platforms; unload; reload-on-token-update guard
│   ├── manifest.json        # metadata (see Global Constraints)
│   ├── const.py             # DOMAIN, PLATFORMS, config keys, API<->HA mode/fan maps, capability property names
│   ├── models.py            # ElectroluxConfigEntry type alias, ApplianceData dataclass
│   ├── api.py               # ElectroluxApiClient: REST + token refresh + SSE listen loop
│   ├── coordinator.py       # ElectroluxCoordinator (DataUpdateCoordinator) + SSE event application
│   ├── config_flow.py       # user step + reauth step
│   ├── entity.py            # ElectroluxEntity base (CoordinatorEntity: device_info, availability)
│   ├── climate.py           # ElectroluxClimate (main feature)
│   ├── sensor.py            # ambient temp, filter state, link quality
│   ├── switch.py            # binary readwrite capabilities (sleep, clean air, ui lock, scheduler, display light)
│   ├── select.py            # multi-value readwrite string capabilities not covered by climate
│   ├── binary_sensor.py     # connectivity
│   ├── translations/en.json
│   └── translations/pt-BR.json
├── tests/
│   ├── conftest.py          # auto_enable_custom_integrations, fixtures, mock entry, sample payloads
│   ├── fixtures/            # appliances.json, info.json, state.json (from openapi.json examples)
│   ├── test_api.py
│   ├── test_coordinator.py
│   ├── test_config_flow.py
│   ├── test_climate.py
│   └── test_platforms.py    # sensor/switch/select/binary_sensor generation
├── hacs.json
├── openapi.json             # already committed (API reference)
├── pyproject.toml           # pytest config (asyncio_mode=auto), dev deps
├── .github/workflows/validate.yml
└── README.md
```

---

### Task 1: Project scaffolding, constants, and data models

**Files:**
- Create: `custom_components/electrolux_ac/__init__.py` (empty placeholder for now — real content in Task 5)
- Create: `custom_components/electrolux_ac/const.py`
- Create: `custom_components/electrolux_ac/models.py`
- Create: `custom_components/electrolux_ac/manifest.json`
- Create: `pyproject.toml`
- Create: `tests/__init__.py` (empty), `tests/conftest.py`
- Test: `tests/test_const.py`

**Interfaces:**
- Produces:
  - `const.DOMAIN = "electrolux_ac"`, `const.PLATFORMS: list[Platform]`
  - Config keys: `const.CONF_API_KEY = "api_key"`, `const.CONF_ACCESS_TOKEN = "access_token"`, `const.CONF_REFRESH_TOKEN = "refresh_token"`
  - `const.HVAC_MODE_MAP: dict[str, HVACMode]` (API mode string → HA HVACMode) and `const.HVAC_MODE_MAP_REVERSE`
  - `const.FAN_MODE_MAP: dict[str, str]` and `const.FAN_MODE_MAP_REVERSE`
  - `const.PROP_*` capability property-name constants (e.g. `PROP_MODE = "mode"`)
  - `models.ApplianceData` dataclass: `appliance_id: str`, `name: str`, `brand: str`, `model: str`, `sw_version: str | None`, `capabilities: dict[str, Any]`, `reported: dict[str, Any]`, `connection_state: str`
  - `models.ElectroluxConfigEntry` type alias (forward-declared; concretely `ConfigEntry[ElectroluxCoordinator]` — use a `TYPE_CHECKING` import of the coordinator to avoid a circular import at runtime)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_const.py
from homeassistant.components.climate import HVACMode
from homeassistant.const import Platform

from custom_components.electrolux_ac import const


def test_domain_and_platforms():
    assert const.DOMAIN == "electrolux_ac"
    assert Platform.CLIMATE in const.PLATFORMS
    assert Platform.SENSOR in const.PLATFORMS
    assert Platform.SWITCH in const.PLATFORMS
    assert Platform.SELECT in const.PLATFORMS
    assert Platform.BINARY_SENSOR in const.PLATFORMS


def test_hvac_mode_map_round_trips():
    assert const.HVAC_MODE_MAP["COOL"] is HVACMode.COOL
    assert const.HVAC_MODE_MAP["AUTO"] is HVACMode.AUTO
    assert const.HVAC_MODE_MAP["DRY"] is HVACMode.DRY
    assert const.HVAC_MODE_MAP["FANONLY"] is HVACMode.FAN_ONLY
    # reverse map turns a HA mode back into the API string
    assert const.HVAC_MODE_MAP_REVERSE[HVACMode.COOL] == "COOL"
    assert const.HVAC_MODE_MAP_REVERSE[HVACMode.FAN_ONLY] == "FANONLY"


def test_fan_mode_map():
    assert const.FAN_MODE_MAP["MIDDLE"] == "medium"
    assert const.FAN_MODE_MAP_REVERSE["medium"] == "MIDDLE"
    assert const.FAN_MODE_MAP["AUTO"] == "auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_const.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError` (const not defined). If you get a collection error about custom integrations, that means `tests/conftest.py` (below) is not in place yet — create it in Step 3.

- [ ] **Step 3: Create the scaffolding files**

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`tests/__init__.py`: empty file.

`tests/conftest.py`:
```python
"""Shared fixtures for electrolux_ac tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom_components/ in every test."""
    yield
```

`custom_components/electrolux_ac/__init__.py`: empty file for now (real content lands in Task 5).

`custom_components/electrolux_ac/manifest.json`:
```json
{
  "domain": "electrolux_ac",
  "name": "Electrolux AC",
  "codeowners": ["@lbkeppler"],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/lbkeppler/eletrolux-ac",
  "integration_type": "hub",
  "iot_class": "cloud_push",
  "issue_tracker": "https://github.com/lbkeppler/eletrolux-ac/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

`custom_components/electrolux_ac/const.py`:
```python
"""Constants for the Electrolux AC integration."""
from __future__ import annotations

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    HVACMode,
)
from homeassistant.const import Platform

DOMAIN = "electrolux_ac"

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BINARY_SENSOR,
]

# Config entry keys
CONF_API_KEY = "api_key"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

# API network limits
POLL_INTERVAL_MINUTES = 5
SSE_RECONNECT_SECONDS = 10

# Capability / reported-state property names (from openapi.json)
PROP_MODE = "mode"
PROP_TARGET_TEMP_C = "targetTemperatureC"
PROP_TARGET_TEMP_F = "targetTemperatureF"
PROP_AMBIENT_TEMP_C = "ambientTemperatureC"
PROP_AMBIENT_TEMP_F = "ambientTemperatureF"
PROP_FAN_SPEED = "fanSpeedSetting"
PROP_VERTICAL_SWING = "verticalSwing"
PROP_TEMP_REPRESENTATION = "temperatureRepresentation"
PROP_EXECUTE_COMMAND = "executeCommand"
PROP_APPLIANCE_STATE = "applianceState"
PROP_FILTER_STATE = "filterState"
PROP_SLEEP_MODE = "sleepMode"
PROP_CLEAN_AIR_MODE = "cleanAirMode"
PROP_DISPLAY_LIGHT = "displayLight"
PROP_UI_LOCK_MODE = "uiLockMode"
PROP_SCHEDULER_MODE = "schedulerMode"
PROP_NETWORK_INTERFACE = "networkInterface"

# Values
UNIT_FAHRENHEIT = "FAHRENHEIT"
UNIT_CELSIUS = "CELSIUS"
STATE_RUNNING = "RUNNING"
STATE_OFF = "OFF"
CONNECTION_CONNECTED = "connected"

# API mode string <-> HA HVACMode
HVAC_MODE_MAP: dict[str, HVACMode] = {
    "COOL": HVACMode.COOL,
    "AUTO": HVACMode.AUTO,
    "DRY": HVACMode.DRY,
    "FANONLY": HVACMode.FAN_ONLY,
    "HEAT": HVACMode.HEAT,
}
HVAC_MODE_MAP_REVERSE: dict[HVACMode, str] = {
    v: k for k, v in HVAC_MODE_MAP.items()
}

# API fan-speed string <-> HA fan mode
FAN_MODE_MAP: dict[str, str] = {
    "AUTO": FAN_AUTO,
    "LOW": FAN_LOW,
    "MIDDLE": FAN_MEDIUM,
    "HIGH": FAN_HIGH,
}
FAN_MODE_MAP_REVERSE: dict[str, str] = {v: k for k, v in FAN_MODE_MAP.items()}
```

`custom_components/electrolux_ac/models.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_const.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/ tests/ pyproject.toml
git commit -m "feat: scaffold electrolux_ac (const, models, manifest, test harness)"
```

---

### Task 2: API client — REST calls, token refresh with rotation

**Execution note:** complex (auth/refresh concurrency, retry-on-401) → run on Opus.

**Files:**
- Create: `custom_components/electrolux_ac/api.py`
- Test: `tests/test_api.py`
- Test fixtures: `tests/fixtures/appliances.json`, `tests/fixtures/info.json`, `tests/fixtures/state.json`

**Interfaces:**
- Consumes: `const` (base URL is defined here in `api.py`), nothing from other tasks.
- Produces:
  - `api.ElectroluxAuthError(Exception)` — raised when credentials are invalid / refresh failed.
  - `api.ElectroluxApiError(Exception)` — raised for other API failures; carries `.status: int | None`.
  - `api.ElectroluxCommandError(ElectroluxApiError)` — raised specifically on `406` command-validation failures (carries `.detail: str | None`).
  - `api.Tokens` dataclass: `access_token: str`, `refresh_token: str`.
  - `api.ElectroluxApiClient` with:
    - `__init__(self, session: aiohttp.ClientSession, api_key: str, access_token: str, refresh_token: str, token_updated_cb: Callable[[Tokens], None] | None = None)`
    - `async def async_get_appliances(self) -> list[dict[str, Any]]`
    - `async def async_get_info(self, appliance_id: str) -> dict[str, Any]`
    - `async def async_get_state(self, appliance_id: str) -> dict[str, Any]`
    - `async def async_send_command(self, appliance_id: str, command: dict[str, Any]) -> None`
    - `async def async_get_livestream_config(self) -> dict[str, Any]`
    - `async def async_iter_events(self) -> AsyncIterator[dict[str, Any]]` — async generator yielding one parsed SSE event dict per `data:` line (a single connection; the reconnect loop lives in the coordinator's SSE task, Task 4).
    - property `tokens -> Tokens` (current pair, so the coordinator can persist after a refresh).

**Design notes for the implementer:**
- Base URL constant `BASE_URL = "https://api.developer.electrolux.one"` lives in `api.py`.
- Build headers per request: `{"x-api-key": self._api_key, "Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}`.
- `_request(method, url, *, json_body=None, allow_retry=True)`: on a `401` response and `allow_retry`, call `_async_refresh()` under an `asyncio.Lock` (so concurrent 401s refresh once), then retry the request with `allow_retry=False`. Any other non-2xx → raise `ElectroluxApiError(status=resp.status)`, except `406` on the command endpoint → `ElectroluxCommandError`.
- `_async_refresh()`: `POST {BASE_URL}/api/v1/token/refresh` with `{"refreshToken": self._refresh_token}` and header `x-api-key` (no bearer needed, but harmless to include). On success, update `self._access_token` / `self._refresh_token` and call `token_updated_cb(Tokens(...))` if set. On failure (non-2xx or network) → raise `ElectroluxAuthError`.
- `202` responses ("already in desired state") are treated as success for commands.
- The SSE `async_iter_events` uses `session.get(url, headers=..., timeout=ClientTimeout(total=None, sock_connect=10, sock_read=120))` — the 120 s `sock_read` is the keepalive guard so a stalled stream raises and the coordinator reconnects. Read `resp.content` line by line (`async for line in resp.content`), decode, collect `data:` payloads, and on a blank line `yield json.loads(payload)`. Do not put the reconnect/backoff here — raise/propagate on stream end so the coordinator loop reconnects.

- [ ] **Step 1: Create test fixtures**

`tests/fixtures/appliances.json`:
```json
[
  {
    "applianceId": "999011524_00:94700001-443E070ABC12",
    "applianceName": "Ar Escritorio",
    "applianceType": "AC",
    "created": "2022-07-20T08:19:06.521Z"
  }
]
```

`tests/fixtures/info.json` — trimmed real AC capabilities from `openapi.json` (mode, temp, fan, swing, sleep, cleanAir, display, uiLock, scheduler, executeCommand, applianceState, filterState, ambient, temperatureRepresentation):
```json
{
  "applianceInfo": {
    "serialNumber": "94700001",
    "pnc": "999011524",
    "brand": "FRIGIDAIRE",
    "deviceType": "PORTABLE_AIR_CONDITIONER",
    "model": "GHPC132AB1",
    "variant": "13KBTU",
    "colour": "WHITE"
  },
  "capabilities": {
    "ambientTemperatureC": {"access": "read", "type": "temperature"},
    "applianceState": {"access": "read", "type": "string", "values": {"OFF": {}, "RUNNING": {}}},
    "cleanAirMode": {"access": "readwrite", "type": "string", "values": {"OFF": {}, "ON": {}}},
    "displayLight": {"access": "readwrite", "type": "string", "values": {"DISPLAY_LIGHT_0": {}, "DISPLAY_LIGHT_1": {}}},
    "executeCommand": {"access": "write", "type": "string", "values": {"OFF": {}, "ON": {}}},
    "fanSpeedSetting": {"access": "readwrite", "type": "string", "values": {"AUTO": {}, "HIGH": {}, "LOW": {}, "MIDDLE": {}}},
    "filterState": {"access": "read", "type": "string", "values": {"BUY": {}, "CHANGE": {}, "CLEAN": {}, "GOOD": {}}},
    "mode": {"access": "readwrite", "type": "string", "values": {"AUTO": {}, "COOL": {}, "DRY": {}, "FANONLY": {}, "OFF": {"disabled": true}}},
    "schedulerMode": {"access": "readwrite", "type": "string", "values": {"OFF": {}, "ON": {}}},
    "sleepMode": {"access": "readwrite", "type": "string", "values": {"OFF": {}, "ON": {}}},
    "targetTemperatureC": {"access": "readwrite", "default": 15.56, "max": 32.22, "min": 15.56, "step": 1, "type": "temperature"},
    "targetTemperatureF": {"access": "readwrite", "default": 60, "max": 90, "min": 60, "step": 1, "type": "temperature"},
    "temperatureRepresentation": {"access": "readwrite", "type": "string", "values": {"CELSIUS": {}, "FAHRENHEIT": {}}},
    "uiLockMode": {"access": "readwrite", "type": "boolean", "values": {"OFF": {}, "ON": {}}},
    "verticalSwing": {"access": "readwrite", "type": "string", "values": {"OFF": {}, "ON": {}}}
  }
}
```

`tests/fixtures/state.json`:
```json
{
  "applianceId": "999011524_00:94700001-443E070ABC12",
  "connectionState": "connected",
  "status": "enabled",
  "properties": {
    "reported": {
      "mode": "COOL",
      "targetTemperatureC": 21,
      "ambientTemperatureC": 22,
      "fanSpeedSetting": "AUTO",
      "verticalSwing": "OFF",
      "sleepMode": "OFF",
      "cleanAirMode": "OFF",
      "displayLight": "DISPLAY_LIGHT_1",
      "uiLockMode": false,
      "schedulerMode": "OFF",
      "filterState": "GOOD",
      "applianceState": "RUNNING",
      "temperatureRepresentation": "CELSIUS",
      "networkInterface": {"linkQualityIndicator": "VERY_GOOD", "swVersion": "v1.9.1_srac"}
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_api.py
import json
from pathlib import Path

import pytest
from aiohttp import ClientSession

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
async def session():
    async with ClientSession() as s:
        yield s


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

    def seq(method, url, data):
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
```

> **Implementer note on the 401-retry test:** `test_401_triggers_refresh_and_retry` above uses `aioclient_mock`'s **callable** `side_effect` (a function `seq(method, url, data)` returning `AiohttpClientMockResponse` objects) to sequence "401 then 200" on the same URL — this is the supported way to sequence responses. If your installed PHACC version raises on the callable form, fall back to monkeypatching `session.request` to an async function returning a fake 401 response then a 200. Keep the three assertions (data returned, tokens rotated, callback fired) regardless.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: custom_components.electrolux_ac.api`.

- [ ] **Step 4: Implement `api.py`**

```python
"""Electrolux Group Developer API client."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientTimeout

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.developer.electrolux.one"
_APPLIANCES = f"{BASE_URL}/api/v1/appliances"
_INFO = f"{BASE_URL}/api/v1/appliances/{{id}}/info"
_STATE = f"{BASE_URL}/api/v1/appliances/{{id}}/state"
_COMMAND = f"{BASE_URL}/api/v1/appliances/{{id}}/command"
_LIVESTREAM = f"{BASE_URL}/api/v1/configurations/livestream"
_REFRESH = f"{BASE_URL}/api/v1/token/refresh"


@dataclass(frozen=True)
class Tokens:
    """A JWT access/refresh pair."""

    access_token: str
    refresh_token: str


class ElectroluxApiError(Exception):
    """Generic API failure."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ElectroluxAuthError(ElectroluxApiError):
    """Credentials are invalid or the refresh failed."""


class ElectroluxCommandError(ElectroluxApiError):
    """A command was rejected (HTTP 406)."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message, status=406)
        self.detail = detail


class ElectroluxApiClient:
    """Thin async client over the Electrolux Developer API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        access_token: str,
        refresh_token: str,
        token_updated_cb: Callable[[Tokens], None] | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_updated_cb = token_updated_cb
        self._refresh_lock = asyncio.Lock()

    @property
    def tokens(self) -> Tokens:
        return Tokens(self._access_token, self._refresh_token)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_retry: bool = True,
    ) -> Any:
        try:
            async with self._session.request(
                method, url, headers=self._headers(), json=json_body,
                timeout=ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401 and allow_retry:
                    await self._async_refresh()
                    return await self._request(
                        method, url, json_body=json_body, allow_retry=False
                    )
                if resp.status in (200, 202, 204):
                    if resp.status == 204:
                        return None
                    # Do not read resp.content_length — the test mock lacks it
                    # and real aiohttp reports None for chunked/unset bodies.
                    text = await resp.text()
                    return json.loads(text) if text else None
                if resp.status == 406:
                    body = await _safe_json(resp)
                    raise ElectroluxCommandError(
                        "Command validation failed",
                        detail=(body or {}).get("detail"),
                    )
                if resp.status == 401:
                    # 401 that survived the retry above → credentials are dead.
                    raise ElectroluxAuthError(
                        "Unauthorized (401)", status=401
                    )
                # 403 is a per-resource forbidden, NOT an auth failure — let it
                # become UpdateFailed in the coordinator, not a reauth flow.
                raise ElectroluxApiError(
                    f"API error {resp.status} for {url}", status=resp.status
                )
        except ClientError as err:
            raise ElectroluxApiError(f"Connection error: {err}") from err

    async def _async_refresh(self) -> None:
        # Double-checked locking: if two concurrent requests both 401, only the
        # first refreshes; the second sees the token already rotated and returns,
        # then retries with the fresh token (headers are re-read on retry).
        snapshot = self._access_token
        async with self._refresh_lock:
            if self._access_token != snapshot:
                return
            try:
                async with self._session.post(
                    _REFRESH,
                    headers={"x-api-key": self._api_key, "Accept": "application/json"},
                    json={"refreshToken": self._refresh_token},
                    timeout=ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise ElectroluxAuthError(
                            f"Token refresh failed ({resp.status})", status=resp.status
                        )
                    data = await resp.json()
            except ClientError as err:
                raise ElectroluxAuthError(f"Token refresh error: {err}") from err

            self._access_token = data["accessToken"]
            self._refresh_token = data["refreshToken"]
            if self._token_updated_cb is not None:
                self._token_updated_cb(Tokens(self._access_token, self._refresh_token))

    async def async_get_appliances(self) -> list[dict[str, Any]]:
        return await self._request("GET", _APPLIANCES)

    async def async_get_info(self, appliance_id: str) -> dict[str, Any]:
        return await self._request("GET", _INFO.format(id=appliance_id))

    async def async_get_state(self, appliance_id: str) -> dict[str, Any]:
        return await self._request("GET", _STATE.format(id=appliance_id))

    async def async_send_command(
        self, appliance_id: str, command: dict[str, Any]
    ) -> None:
        await self._request(
            "PUT", _COMMAND.format(id=appliance_id), json_body=command
        )

    async def async_get_livestream_config(self) -> dict[str, Any]:
        return await self._request("GET", _LIVESTREAM)

    async def async_iter_events(self) -> AsyncIterator[dict[str, Any]]:
        config = await self.async_get_livestream_config()
        url = config["url"]
        async with self._session.get(
            url,
            headers=self._headers(),
            # sock_read=120 is the keepalive guard: a half-open/stalled stream
            # raises ServerTimeoutError after 120s so the coordinator reconnects.
            timeout=ClientTimeout(total=None, sock_connect=10, sock_read=120),
        ) as resp:
            if resp.status == 401:
                await self._async_refresh()
                raise ElectroluxApiError("SSE auth expired; reconnect")
            if resp.status != 200:
                raise ElectroluxApiError(
                    f"SSE connect failed ({resp.status})", status=resp.status
                )
            data_buf: list[str] = []
            async for raw in resp.content:
                line = raw.decode(errors="replace").strip()
                if line.startswith("data:"):
                    data_buf.append(line[len("data:"):].strip())
                elif line == "":
                    if not data_buf:
                        continue
                    payload = "".join(data_buf)
                    data_buf = []
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        _LOGGER.debug("Bad SSE payload: %s", payload)


async def _safe_json(resp: aiohttp.ClientResponse) -> dict[str, Any] | None:
    try:
        return await resp.json()
    except (ClientError, ValueError):
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS. If the 401-retry test can't sequence responses with the installed mock, implement the variant described in the implementer note and confirm the refresh-mechanism assertions pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/electrolux_ac/api.py tests/test_api.py tests/fixtures/
git commit -m "feat: Electrolux API client with token refresh and SSE iterator"
```

---

### Task 3: SSE event application + appliance parsing (pure functions)

**Execution note:** complex (nested-path merge logic) → run on Opus.

These are pure, HA-free helpers so they can be unit-tested trivially and reused by the coordinator.

**Files:**
- Modify: `custom_components/electrolux_ac/coordinator.py` (create file with only the pure helpers for now; the coordinator class is added in Task 4)
- Test: `tests/test_coordinator.py` (create; only the pure-helper tests for now)

**Interfaces:**
- Produces (module-level functions in `coordinator.py`):
  - `def parse_appliance(appliance: dict, info: dict, state: dict) -> ApplianceData` — builds an `ApplianceData` from the three API payloads. `name` = `appliance["applianceName"]`; `brand` = `info["applianceInfo"]["brand"]`; `model` = `info["applianceInfo"]["model"]` (+ `variant` if present, space-joined); `sw_version` = `state["properties"]["reported"].get("networkInterface", {}).get("swVersion")`; `capabilities` = `info["capabilities"]`; `reported` = `state["properties"]["reported"]`; `connection_state` = `state.get("connectionState", "unknown")`.
  - `def apply_sse_event(data: ApplianceData, event: dict) -> ApplianceData` — returns a NEW `ApplianceData` with the event applied. If `event["property"]` is `"connectionState"` or `"connectivityState"`, set `connection_state`. Otherwise split the property on `/` and set the value at that nested path inside a copied `reported` dict (creating intermediate dicts as needed). Missing `property` or `value` → return `data` unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coordinator.py
import json
from pathlib import Path

from custom_components.electrolux_ac.coordinator import (
    apply_sse_event,
    parse_appliance,
)
from custom_components.electrolux_ac.models import ApplianceData

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_appliance():
    data = parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )
    assert data.appliance_id == "999011524_00:94700001-443E070ABC12"
    assert data.name == "Ar Escritorio"
    assert data.brand == "FRIGIDAIRE"
    assert "GHPC132AB1" in data.model
    assert data.sw_version == "v1.9.1_srac"
    assert data.connection_state == "connected"
    assert data.reported["mode"] == "COOL"
    assert "mode" in data.capabilities


def _base():
    return parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )


def test_apply_sse_simple_property():
    data = _base()
    updated = apply_sse_event(data, {"applianceId": "x", "property": "mode", "value": "AUTO"})
    assert updated.reported["mode"] == "AUTO"
    # original unchanged (returns a new object)
    assert data.reported["mode"] == "COOL"


def test_apply_sse_nested_path():
    data = _base()
    updated = apply_sse_event(
        data,
        {"applianceId": "x", "property": "networkInterface/linkQualityIndicator", "value": "GOOD"},
    )
    assert updated.reported["networkInterface"]["linkQualityIndicator"] == "GOOD"
    # sibling key preserved
    assert updated.reported["networkInterface"]["swVersion"] == "v1.9.1_srac"


def test_apply_sse_connection_state():
    data = _base()
    updated = apply_sse_event(data, {"applianceId": "x", "property": "connectivityState", "value": "disconnected"})
    assert updated.connection_state == "disconnected"


def test_apply_sse_missing_fields_noop():
    data = _base()
    assert apply_sse_event(data, {"applianceId": "x"}) is data
    assert apply_sse_event(data, {"property": "mode"}) is data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coordinator.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` (coordinator not defined).

- [ ] **Step 3: Create `coordinator.py` with the pure helpers**

```python
"""Coordinator and pure helpers for Electrolux AC."""
from __future__ import annotations

import copy
from typing import Any

from .const import CONNECTION_CONNECTED  # noqa: F401  (used by coordinator class later)
from .models import ApplianceData


def parse_appliance(
    appliance: dict[str, Any], info: dict[str, Any], state: dict[str, Any]
) -> ApplianceData:
    """Build an ApplianceData snapshot from the three API payloads."""
    appliance_info = info.get("applianceInfo", {})
    model = appliance_info.get("model", "")
    variant = appliance_info.get("variant")
    if variant:
        model = f"{model} {variant}".strip()
    reported = state.get("properties", {}).get("reported", {})
    sw_version = reported.get("networkInterface", {}).get("swVersion")
    return ApplianceData(
        appliance_id=appliance["applianceId"],
        name=appliance.get("applianceName", appliance["applianceId"]),
        brand=appliance_info.get("brand", "Electrolux"),
        model=model,
        sw_version=sw_version,
        capabilities=info.get("capabilities", {}),
        reported=reported,
        connection_state=state.get("connectionState", "unknown"),
    )


def apply_sse_event(data: ApplianceData, event: dict[str, Any]) -> ApplianceData:
    """Return a new ApplianceData with one SSE event applied."""
    prop = event.get("property")
    value = event.get("value")
    if prop is None or value is None:
        return data

    if prop in ("connectionState", "connectivityState"):
        return ApplianceData(
            appliance_id=data.appliance_id,
            name=data.name,
            brand=data.brand,
            model=data.model,
            sw_version=data.sw_version,
            capabilities=data.capabilities,
            reported=data.reported,
            connection_state=value,
        )

    new_reported = copy.deepcopy(data.reported)
    path = prop.split("/")
    target = new_reported
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value

    return ApplianceData(
        appliance_id=data.appliance_id,
        name=data.name,
        brand=data.brand,
        model=data.model,
        sw_version=data.sw_version,
        capabilities=data.capabilities,
        reported=new_reported,
        connection_state=data.connection_state,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_coordinator.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/coordinator.py tests/test_coordinator.py
git commit -m "feat: pure helpers to parse appliances and apply SSE events"
```

---

### Task 4: Coordinator class — polling, SSE loop, optimistic commands

**Execution note:** complex (async lifecycle, error mapping, push+poll) → run on Opus.

**Files:**
- Modify: `custom_components/electrolux_ac/coordinator.py` (add the class below the helpers)
- Modify: `tests/test_coordinator.py` (add coordinator tests)

**Interfaces:**
- Consumes: `ElectroluxApiClient`, `ElectroluxAuthError`, `ElectroluxApiError` (Task 2); `parse_appliance`, `apply_sse_event` (Task 3); `ApplianceData`, `ElectroluxConfigEntry` (Task 1).
- Produces: `coordinator.ElectroluxCoordinator(DataUpdateCoordinator[dict[str, ApplianceData]])` with:
  - `__init__(self, hass, entry: ElectroluxConfigEntry, client: ElectroluxApiClient)`
  - `async def _async_update_data(self) -> dict[str, ApplianceData]` — first run lists appliances, filters to AC (`applianceType == "AC"`), fetches info+state, caches capabilities; subsequent runs re-fetch state only and merge into cached `ApplianceData`. Maps `ElectroluxAuthError` → `ConfigEntryAuthFailed`, other errors → `UpdateFailed`.
  - `async def async_run_sse(self) -> None` — the reconnect loop: `async for event in self.client.async_iter_events()` → apply to the right appliance via `_handle_event` (which sets `self.data` and calls `async_update_listeners()` — NOT `async_set_updated_data`, to avoid resetting the poll timer); on any exception, sleep `SSE_RECONNECT_SECONDS` and reconnect; exits cleanly on `asyncio.CancelledError`.
  - `async def async_send_command(self, appliance_id, command) -> None` — sends via client, then optimistically applies the command keys into the cached `ApplianceData.reported`, sets `self.data` and calls `async_update_listeners()`. Wraps `ElectroluxCommandError` into `HomeAssistantError` with the detail message.

**Design notes:**
- The AC filter (spec section 3.2 requires `applianceType == "AC"` OR `deviceType` containing `AIR_CONDITIONER`): the list endpoint only carries `applianceType`, and `deviceType` lives in `/info`. So: fetch `/info` for **every** listed appliance, then keep it if `appliance.get("applianceType") == "AC"` OR `"AIR_CONDITIONER" in (info["applianceInfo"].get("deviceType") or "")`. If discovery yields **zero** ACs, `_LOGGER.warning(...)` the appliance types found so the empty-device outcome is diagnosable.
- Store `self._appliance_ids: list[str]` and `self._info: dict[str, dict]` after the first refresh to avoid re-fetching info every poll (info/capabilities are static).
- Optimistic apply: for each `(k, v)` in the command dict, set `data.reported[k] = v`; but if the command is `{"executeCommand": "OFF"}`, also set `applianceState = "OFF"`, and `"ON"` → `applianceState = "RUNNING"` (so the climate entity flips immediately).

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_coordinator.py
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electrolux_ac.api import ElectroluxAuthError, ElectroluxCommandError, ElectroluxApiError
from custom_components.electrolux_ac.const import DOMAIN
from custom_components.electrolux_ac.coordinator import ElectroluxCoordinator


def _mock_client():
    client = MagicMock()
    client.async_get_appliances = AsyncMock(return_value=_load("appliances.json"))
    client.async_get_info = AsyncMock(return_value=_load("info.json"))
    client.async_get_state = AsyncMock(return_value=_load("state.json"))
    client.async_send_command = AsyncMock()
    return client


def _entry():
    return MockConfigEntry(domain=DOMAIN, data={"api_key": "k", "access_token": "a", "refresh_token": "r"})


async def test_first_refresh_builds_ac_map(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    coord = ElectroluxCoordinator(hass, entry, _mock_client())
    data = await coord._async_update_data()
    aid = "999011524_00:94700001-443E070ABC12"
    assert aid in data
    assert data[aid].reported["mode"] == "COOL"


async def test_discovery_falls_back_to_device_type(hass):
    """An appliance not typed 'AC' in the list is kept if info.deviceType is an AC."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    aid = "999011524_00:94700001-443E070ABC12"
    # list entry reports a non-"AC" applianceType, but /info says AIR_CONDITIONER
    listing = [{**_load("appliances.json")[0], "applianceType": "OTHER"}]
    client.async_get_appliances = AsyncMock(return_value=listing)
    coord = ElectroluxCoordinator(hass, entry, client)
    data = await coord._async_update_data()
    assert aid in data  # kept via deviceType fallback (PORTABLE_AIR_CONDITIONER)


async def test_discovery_no_ac_logs_warning(hass, caplog):
    """Zero ACs discovered → warning logged, empty data returned."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    listing = [{**_load("appliances.json")[0], "applianceType": "WM"}]
    client.async_get_appliances = AsyncMock(return_value=listing)
    # info without an AC deviceType
    client.async_get_info = AsyncMock(
        return_value={"applianceInfo": {"deviceType": "WASHING_MACHINE", "brand": "AEG", "model": "X"}, "capabilities": {}}
    )
    coord = ElectroluxCoordinator(hass, entry, client)
    data = await coord._async_update_data()
    assert data == {}
    assert "No AC appliances found" in caplog.text


async def test_auth_error_maps_to_config_entry_auth_failed(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    client.async_get_appliances = AsyncMock(side_effect=ElectroluxAuthError("bad"))
    coord = ElectroluxCoordinator(hass, entry, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_api_error_maps_to_update_failed(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    client.async_get_appliances = AsyncMock(side_effect=ElectroluxApiError("boom"))
    coord = ElectroluxCoordinator(hass, entry, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_send_command_optimistic_update(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    coord = ElectroluxCoordinator(hass, entry, _mock_client())
    coord.data = await coord._async_update_data()
    aid = "999011524_00:94700001-443E070ABC12"
    await coord.async_send_command(aid, {"mode": "AUTO"})
    assert coord.data[aid].reported["mode"] == "AUTO"


async def test_send_command_406_raises_home_assistant_error(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    client.async_send_command = AsyncMock(
        side_effect=ElectroluxCommandError("rejected", detail="Appliance disconnected")
    )
    coord = ElectroluxCoordinator(hass, entry, client)
    coord.data = await coord._async_update_data()
    aid = "999011524_00:94700001-443E070ABC12"
    with pytest.raises(HomeAssistantError):
        await coord.async_send_command(aid, {"mode": "COOL"})


async def test_sse_loop_applies_event(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    client = _mock_client()
    aid = "999011524_00:94700001-443E070ABC12"

    async def one_event():
        yield {"applianceId": aid, "property": "mode", "value": "DRY"}
        # end the stream so the loop would reconnect; we cancel before that.
        await asyncio.sleep(3600)
        yield {}

    client.async_iter_events = one_event
    coord = ElectroluxCoordinator(hass, entry, client)
    coord.data = await coord._async_update_data()
    task = asyncio.create_task(coord.async_run_sse())
    await asyncio.sleep(0.05)
    assert coord.data[aid].reported["mode"] == "DRY"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coordinator.py -v -k "refresh or auth or api_error or command or sse_loop"`
Expected: FAIL — `AttributeError`/`ImportError` (ElectroluxCoordinator not defined).

- [ ] **Step 3: Add the coordinator class to `coordinator.py`**

Add these imports at the top of `coordinator.py`:
```python
import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ElectroluxApiClient,
    ElectroluxApiError,
    ElectroluxAuthError,
    ElectroluxCommandError,
)
from .const import (
    DOMAIN,
    POLL_INTERVAL_MINUTES,
    PROP_APPLIANCE_STATE,
    PROP_EXECUTE_COMMAND,
    SSE_RECONNECT_SECONDS,
    STATE_OFF,
    STATE_RUNNING,
)
from .models import ApplianceData, ElectroluxConfigEntry

_LOGGER = logging.getLogger(__name__)
```

Add the class:
```python
class ElectroluxCoordinator(DataUpdateCoordinator[dict[str, ApplianceData]]):
    """Coordinates polling + SSE push for Electrolux ACs."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ElectroluxConfigEntry,
        client: ElectroluxApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=POLL_INTERVAL_MINUTES),
            always_update=False,
        )
        self.client = client
        self._appliance_ids: list[str] = []
        self._info: dict[str, dict] = {}

    async def _async_update_data(self) -> dict[str, ApplianceData]:
        try:
            if not self._appliance_ids:
                await self._async_discover()
            result: dict[str, ApplianceData] = {}
            for aid in self._appliance_ids:
                appliance = self._appliance_by_id[aid]
                state = await self.client.async_get_state(aid)
                result[aid] = parse_appliance(appliance, self._info[aid], state)
            return result
        except ElectroluxAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ElectroluxApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_discover(self) -> None:
        appliances = await self.client.async_get_appliances()
        self._appliance_by_id = {}
        for appliance in appliances:
            aid = appliance["applianceId"]
            info = await self.client.async_get_info(aid)
            device_type = info.get("applianceInfo", {}).get("deviceType") or ""
            is_ac = (
                appliance.get("applianceType") == "AC"
                or "AIR_CONDITIONER" in device_type
            )
            if not is_ac:
                continue
            self._appliance_by_id[aid] = appliance
            self._info[aid] = info
        self._appliance_ids = list(self._appliance_by_id)
        if not self._appliance_ids:
            _LOGGER.warning(
                "No AC appliances found among %d appliances; types=%s",
                len(appliances),
                [a.get("applianceType") for a in appliances],
            )

    async def async_run_sse(self) -> None:
        """Long-lived SSE listen loop with reconnect."""
        while True:
            try:
                async for event in self.client.async_iter_events():
                    self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 — reconnect on anything
                _LOGGER.debug("SSE stream error, reconnecting: %s", err)
            try:
                await asyncio.sleep(SSE_RECONNECT_SECONDS)
            except asyncio.CancelledError:
                raise

    @callback
    def _handle_event(self, event: dict) -> None:
        aid = event.get("applianceId")
        if not aid or self.data is None or aid not in self.data:
            return
        new_data = dict(self.data)
        new_data[aid] = apply_sse_event(self.data[aid], event)
        # Update state and notify entities WITHOUT rescheduling the poll —
        # async_set_updated_data would reset the 5-min timer, and a chatty SSE
        # stream would then starve the reconciliation poll forever. See the
        # spec's reconciliation requirement (section 3.2).
        self.data = new_data
        self.async_update_listeners()

    async def async_send_command(
        self, appliance_id: str, command: dict
    ) -> None:
        try:
            await self.client.async_send_command(appliance_id, command)
        except ElectroluxCommandError as err:
            raise HomeAssistantError(
                f"Command rejected: {err.detail or err}"
            ) from err
        except ElectroluxApiError as err:
            raise HomeAssistantError(str(err)) from err

        if self.data is None or appliance_id not in self.data:
            return
        current = self.data[appliance_id]
        new_reported = dict(current.reported)
        for key, value in command.items():
            new_reported[key] = value
            if key == PROP_EXECUTE_COMMAND:
                new_reported[PROP_APPLIANCE_STATE] = (
                    STATE_RUNNING if value == "ON" else STATE_OFF
                )
        updated = ApplianceData(
            appliance_id=current.appliance_id,
            name=current.name,
            brand=current.brand,
            model=current.model,
            sw_version=current.sw_version,
            capabilities=current.capabilities,
            reported=new_reported,
            connection_state=current.connection_state,
        )
        new_data = dict(self.data)
        new_data[appliance_id] = updated
        # Same as _handle_event: push optimistically without resetting the poll.
        self.data = new_data
        self.async_update_listeners()
```

> **Implementer note:** `_async_discover` sets `self._appliance_by_id`; declare it in `__init__` as `self._appliance_by_id: dict[str, dict] = {}` to satisfy type checkers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_coordinator.py -v`
Expected: PASS (all coordinator tests + the 5 helper tests from Task 3).

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/coordinator.py tests/test_coordinator.py
git commit -m "feat: ElectroluxCoordinator with poll, SSE reconnect loop, optimistic commands"
```

---

### Task 5: Entry setup/unload (`__init__.py`) with token persistence

**Execution note:** complex (entry lifecycle, background task, token persistence) → run on Opus.

**Files:**
- Modify: `custom_components/electrolux_ac/__init__.py` (replace the empty placeholder)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `ElectroluxApiClient`, `Tokens` (Task 2); `ElectroluxCoordinator` (Task 4); `ElectroluxConfigEntry`, `const` (Task 1).
- Produces:
  - `async def async_setup_entry(hass, entry: ElectroluxConfigEntry) -> bool`
  - `async def async_unload_entry(hass, entry: ElectroluxConfigEntry) -> bool`

**Design notes:**
- Build the client with `async_get_clientsession(hass)`. Wire `token_updated_cb` to a closure that persists the rotated pair:
  `hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_ACCESS_TOKEN: t.access_token, CONF_REFRESH_TOKEN: t.refresh_token})`.
  Do **not** register an update listener that reloads on data change (that would kill the SSE task on every token refresh — see research gotcha).
- Create coordinator, `await coordinator.async_config_entry_first_refresh()`, assign `entry.runtime_data = coordinator`, forward platforms, then start the SSE task with `entry.async_create_background_task(hass, coordinator.async_run_sse(), name=f"{DOMAIN}_sse_{entry.entry_id}")`.
- Unload: `await hass.config_entries.async_unload_platforms(entry, PLATFORMS)` (the background task is auto-cancelled by core on unload).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_init.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electrolux_ac.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _patch_client():
    """Patch ElectroluxApiClient so no network happens; SSE never yields."""
    async def _never():
        if False:
            yield {}
        # block forever so the background task stays alive without events
        import asyncio
        await asyncio.sleep(3600)

    inst = AsyncMock()
    inst.async_get_appliances = AsyncMock(return_value=_load("appliances.json"))
    inst.async_get_info = AsyncMock(return_value=_load("info.json"))
    inst.async_get_state = AsyncMock(return_value=_load("state.json"))
    inst.async_iter_events = _never
    return patch(
        "custom_components.electrolux_ac.ElectroluxApiClient", return_value=inst
    )


async def test_setup_and_unload_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_ACCESS_TOKEN: "a", CONF_REFRESH_TOKEN: "r"},
    )
    entry.add_to_hass(hass)
    with _patch_client():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # a climate entity for the AC was created
    assert hass.states.async_entity_ids("climate")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_init.py -v`
Expected: FAIL — `async_setup_entry` not defined (empty `__init__.py`), or no climate entity. (Climate platform doesn't exist until Task 7 — this test will fully pass only after Task 7. Until then, expect the climate-entity assertion to fail; that's acceptable, but to keep the task independently green, temporarily assert only `entry.state is ConfigEntryState.LOADED` and add the climate assertion in Task 7. **Choose:** implement `__init__` now, assert LOADED/NOT_LOADED only, and defer the `climate` state assertion to Task 7's test.)

- [ ] **Step 3: Implement `__init__.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_init.py -v`
Expected: PASS for the LOADED/NOT_LOADED assertions. (Add/enable the `climate` state assertion in Task 7.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/__init__.py tests/test_init.py
git commit -m "feat: entry setup/unload with SSE task and rotated-token persistence"
```

---

### Task 6: Config flow — user step + reauth

**Execution note:** complex (flow states, unique_id, reauth) → run on Opus.

**Files:**
- Create: `custom_components/electrolux_ac/config_flow.py`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `ElectroluxApiClient`, `ElectroluxAuthError`, `ElectroluxApiError` (Task 2); `const` (Task 1).
- Produces: `config_flow.ElectroluxConfigFlow(ConfigFlow, domain=DOMAIN)`.

**Design notes:**
- Data schema: three required text fields — `CONF_API_KEY`, `CONF_ACCESS_TOKEN`, `CONF_REFRESH_TOKEN` (use `vol.Schema` with `str`).
- Validation: build a client with a throwaway session (`async_get_clientsession(self.hass)`) and call `async_get_appliances()`. `ElectroluxAuthError` → `errors["base"] = "invalid_auth"`; `ElectroluxApiError` → `errors["base"] = "cannot_connect"`.
- `unique_id`: derive a stable account id. The access token is a JWT — decode its `sub` claim without verification (`jwt.decode(token, options={"verify_signature": False})["sub"]`). Use that as `unique_id` so the same account can't be added twice and reauth can detect a mismatched account. `PyJWT` ships with HA; import `jwt`.
- Reauth: `async_step_reauth` → `async_step_reauth_confirm`; on success, set unique_id, `self._abort_if_unique_id_mismatch("wrong_account")`, then `self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates={...three fields...})`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_flow.py
from unittest.mock import AsyncMock, patch

import pytest
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
```

> **Implementer note:** `FAKE_JWT` above is a real HS256 token whose payload is `{"sub": "acct-123"}`, already verified to decode correctly with `verify_signature=False`. The config flow reads only the `sub` claim, so the signing key is irrelevant. No need to regenerate it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config_flow.py -v`
Expected: FAIL — config flow module/class not found.

- [ ] **Step 3: Implement `config_flow.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config_flow.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/config_flow.py tests/test_config_flow.py
git commit -m "feat: config flow with credential validation, unique account id, reauth"
```

---

### Task 7: Entity base + climate entity

**Execution note:** complex (capability-driven feature flags, unit handling, command mapping) → run on Opus.

**Files:**
- Create: `custom_components/electrolux_ac/entity.py`
- Create: `custom_components/electrolux_ac/climate.py`
- Test: `tests/test_climate.py`
- Modify: `tests/test_init.py` (enable the deferred `climate` state assertion from Task 5)

**Interfaces:**
- Consumes: `ElectroluxCoordinator` (Task 4); `ApplianceData`, `const` (Task 1).
- Produces:
  - `entity.ElectroluxEntity(CoordinatorEntity[ElectroluxCoordinator])` base with `__init__(self, coordinator, appliance_id)`, sets `_attr_device_info` and `_attr_has_entity_name = True`; provides `self.appliance -> ApplianceData` property (reads `coordinator.data[appliance_id]`), overrides `available`.
  - `climate.async_setup_entry(hass, entry, async_add_entities)` creating one `ElectroluxClimate` per appliance in `coordinator.data`.
  - `climate.ElectroluxClimate(ElectroluxEntity, ClimateEntity)`.

**Design notes for climate:**
- `_attr_name = None` (main feature). Unique id = `appliance_id` (the climate is the device's primary entity).
- Build `_attr_hvac_modes` from `capabilities["mode"]["values"]`: map each API mode via `HVAC_MODE_MAP` (skip `OFF` — it's `disabled` and represented by `HVACMode.OFF`), always append `HVACMode.OFF`.
- `_attr_supported_features`: always `TURN_ON | TURN_OFF`; add `TARGET_TEMPERATURE` if `targetTemperatureC` capability exists, `FAN_MODE` if `fanSpeedSetting` exists, `SWING_MODE` if `verticalSwing` exists.
- Current unit: read `reported["temperatureRepresentation"]`; if `FAHRENHEIT` → `_attr_temperature_unit = UnitOfTemperature.FAHRENHEIT` and use `targetTemperatureF`/`ambientTemperatureF` + the F capability min/max/step; else Celsius. Compute these in properties (read live from `self.appliance`), not cached in `__init__`, since the user can change the unit.
- `hvac_mode` property: if `applianceState == "OFF"` (or `mode == "OFF"`) → `HVACMode.OFF`; else map `reported["mode"]` via `HVAC_MODE_MAP`, defaulting to `HVACMode.OFF` if unknown.
- `async_set_hvac_mode`: `OFF` → send `{"executeCommand": "OFF"}`; any other → send `{"executeCommand": "ON", "mode": HVAC_MODE_MAP_REVERSE[mode]}`.
- `async_turn_on`/`async_turn_off`: send `{"executeCommand": "ON"}` / `{"executeCommand": "OFF"}`.
- `async_set_temperature`: read `kwargs[ATTR_TEMPERATURE]`; pick `targetTemperatureC` or `targetTemperatureF` per current unit; also honor `kwargs.get(ATTR_HVAC_MODE)` if present (set mode in the same command). Values are already in the entity's unit.
- `async_set_fan_mode`: send `{"fanSpeedSetting": FAN_MODE_MAP_REVERSE[fan_mode]}`.
- `async_set_swing_mode`: HA swing is `on`/`off`; send `{"verticalSwing": "ON" if swing_mode == SWING_ON else "OFF"}`.
- All command methods call `self.coordinator.async_send_command(self._appliance_id, cmd)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_climate.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import UnitOfTemperature

from custom_components.electrolux_ac.climate import ElectroluxClimate
from custom_components.electrolux_ac.coordinator import parse_appliance

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _coord_with_data():
    data = parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.async_send_command = AsyncMock()
    return coord, data.appliance_id


def test_hvac_modes_from_capabilities():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert HVACMode.OFF in entity.hvac_modes
    assert HVACMode.COOL in entity.hvac_modes
    assert HVACMode.AUTO in entity.hvac_modes
    assert HVACMode.DRY in entity.hvac_modes
    assert HVACMode.FAN_ONLY in entity.hvac_modes


def test_current_and_target_celsius():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    assert entity.temperature_unit == UnitOfTemperature.CELSIUS
    assert entity.current_temperature == 22
    assert entity.target_temperature == 21
    assert entity.min_temp == 15.56
    assert entity.max_temp == 32.22


def test_hvac_mode_reflects_running_state():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    # fixture has applianceState RUNNING, mode COOL
    assert entity.hvac_mode == HVACMode.COOL


async def test_set_hvac_mode_off_sends_execute_off():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_hvac_mode(HVACMode.OFF)
    coord.async_send_command.assert_awaited_once_with(aid, {"executeCommand": "OFF"})


async def test_set_hvac_mode_cool_sends_on_and_mode():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_hvac_mode(HVACMode.COOL)
    coord.async_send_command.assert_awaited_once_with(
        aid, {"executeCommand": "ON", "mode": "COOL"}
    )


async def test_set_temperature_celsius():
    from homeassistant.components.climate import ATTR_TEMPERATURE

    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 24})
    coord.async_send_command.assert_awaited_once_with(aid, {"targetTemperatureC": 24})


async def test_set_fan_mode():
    coord, aid = _coord_with_data()
    entity = ElectroluxClimate(coord, aid)
    await entity.async_set_fan_mode("medium")
    coord.async_send_command.assert_awaited_once_with(aid, {"fanSpeedSetting": "MIDDLE"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_climate.py -v`
Expected: FAIL — climate module/class not found.

- [ ] **Step 3: Implement `entity.py`**

```python
"""Base entity for Electrolux AC."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONNECTION_CONNECTED, DOMAIN
from .coordinator import ElectroluxCoordinator
from .models import ApplianceData


class ElectroluxEntity(CoordinatorEntity[ElectroluxCoordinator]):
    """Common base for all Electrolux entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ElectroluxCoordinator, appliance_id: str) -> None:
        super().__init__(coordinator)
        self._appliance_id = appliance_id
        appliance = coordinator.data[appliance_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance_id)},
            name=appliance.name,
            manufacturer=appliance.brand.title(),
            model=appliance.model,
            sw_version=appliance.sw_version,
        )

    @property
    def appliance(self) -> ApplianceData:
        return self.coordinator.data[self._appliance_id]

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._appliance_id in self.coordinator.data
            and self.appliance.connection_state == CONNECTION_CONNECTED
        )
```

- [ ] **Step 4: Implement `climate.py`**

```python
"""Climate platform for Electrolux AC."""
from __future__ import annotations

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

from .const import (
    FAN_MODE_MAP,
    FAN_MODE_MAP_REVERSE,
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
    PROP_VERTICAL_SWING,
    STATE_OFF,
    UNIT_FAHRENHEIT,
)
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


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
        for api_mode in caps.get(PROP_MODE, {}).get("values", {}):
            if api_mode in HVAC_MODE_MAP:
                modes.append(HVAC_MODE_MAP[api_mode])
        modes.append(HVACMode.OFF)
        self._attr_hvac_modes = list(dict.fromkeys(modes))

        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if PROP_TARGET_TEMP_C in caps:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if PROP_FAN_SPEED in caps:
            features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = [
                FAN_MODE_MAP[v]
                for v in caps[PROP_FAN_SPEED].get("values", {})
                if v in FAN_MODE_MAP
            ]
        if PROP_VERTICAL_SWING in caps:
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
        return HVAC_MODE_MAP.get(api_mode, HVACMode.OFF)

    @property
    def fan_mode(self) -> str | None:
        return FAN_MODE_MAP.get(self.appliance.reported.get(PROP_FAN_SPEED))

    @property
    def swing_mode(self) -> str | None:
        val = self.appliance.reported.get(PROP_VERTICAL_SWING)
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
        await self.coordinator.async_send_command(
            self._appliance_id, {"fanSpeedSetting": FAN_MODE_MAP_REVERSE[fan_mode]}
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self.coordinator.async_send_command(
            self._appliance_id,
            {"verticalSwing": "ON" if swing_mode == SWING_ON else "OFF"},
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_climate.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Enable the deferred assertion in `tests/test_init.py`**

Add to `test_setup_and_unload_entry`, after `assert entry.state is ConfigEntryState.LOADED`:
```python
    assert hass.states.async_entity_ids("climate")
```
Run: `pytest tests/test_init.py -v` → Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/electrolux_ac/entity.py custom_components/electrolux_ac/climate.py tests/test_climate.py tests/test_init.py
git commit -m "feat: climate entity (capability-driven modes, temp units, commands)"
```

---

### Task 8: Sensor, switch, select, binary_sensor platforms

**Execution note:** mostly mechanical (repetitive entity descriptions) → run on Sonnet.

**Files:**
- Create: `custom_components/electrolux_ac/sensor.py`
- Create: `custom_components/electrolux_ac/switch.py`
- Create: `custom_components/electrolux_ac/select.py`
- Create: `custom_components/electrolux_ac/binary_sensor.py`
- Test: `tests/test_platforms.py`

**Interfaces:**
- Consumes: `ElectroluxEntity` (Task 7), `ElectroluxCoordinator`, `const`, `ElectroluxConfigEntry`.
- Produces four `async_setup_entry` functions + their entity classes. Each entity is created only if the driving capability/property exists.

**Design notes:**
- **sensor.py** — three sensor types, each gated on presence:
  - Ambient temp: created if `ambientTemperatureC` in reported; `SensorDeviceClass.TEMPERATURE`, `SensorStateClass.MEASUREMENT`, `native_unit_of_measurement = °C`, `translation_key="ambient_temperature"`, `native_value = reported["ambientTemperatureC"]`.
  - Filter state: created if `filterState` capability exists; `SensorDeviceClass.ENUM`, `options = list(capabilities["filterState"]["values"])` lowercased, `translation_key="filter_state"`, `native_value = reported["filterState"].lower()`. (ENUM must NOT set state_class/unit.)
  - Link quality: created if `networkInterface` in reported; `translation_key="link_quality"`, `EntityCategory.DIAGNOSTIC`, `native_value = reported["networkInterface"].get("linkQualityIndicator")` (plain string, no device_class).
- **switch.py** — one switch per binary readwrite capability present, from a table: `sleepMode`, `cleanAirMode`, `uiLockMode`, `schedulerMode` (values ON/OFF) and `displayLight` (values DISPLAY_LIGHT_0=off / DISPLAY_LIGHT_1=on). Each: `_attr_translation_key`, `EntityCategory.CONFIG`, `is_on` from reported value, `async_turn_on/off` send the ON/OFF (or DISPLAY_LIGHT_1/0) value. `uiLockMode` is boolean in reported (`true`/`false`) — handle both bool and "ON"/"OFF".
- **select.py** — v1 has no multi-value readwrite string capability that isn't already covered by climate (mode→hvac, fanSpeed→fan). So `select.py` provides `async_setup_entry` that creates **no** entities for the current AC (the file exists so the platform is registered and future-proof). Keep it minimal: iterate a `SELECT_CAPABILITIES` table (empty for now) — the test asserts zero select entities are created. *(Do not invent selects; YAGNI.)*
- **binary_sensor.py** — one connectivity binary sensor per appliance: `BinarySensorDeviceClass.CONNECTIVITY`, `EntityCategory.DIAGNOSTIC`, `translation_key="connectivity"`, `is_on = appliance.connection_state == "connected"`. **Override `available` to return `super(CoordinatorEntity)` availability** — i.e. this entity must stay available even when disconnected (otherwise it can never report "disconnected"). Implement by NOT inheriting the connection check: subclass `CoordinatorEntity` directly or override `available` to `self.coordinator.last_update_success and self._appliance_id in self.coordinator.data`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_platforms.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.electrolux_ac.binary_sensor import ElectroluxConnectivity
from custom_components.electrolux_ac.coordinator import parse_appliance
from custom_components.electrolux_ac.sensor import build_sensors
from custom_components.electrolux_ac.switch import build_switches

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _coord():
    data = parse_appliance(
        _load("appliances.json")[0], _load("info.json"), _load("state.json")
    )
    coord = MagicMock()
    coord.data = {data.appliance_id: data}
    coord.last_update_success = True
    return coord, data.appliance_id


def test_sensors_created_for_ac():
    coord, aid = _coord()
    sensors = build_sensors(coord, aid)
    keys = {s._attr_translation_key for s in sensors}
    assert "ambient_temperature" in keys
    assert "filter_state" in keys
    assert "link_quality" in keys
    filt = next(s for s in sensors if s._attr_translation_key == "filter_state")
    assert filt._attr_device_class == SensorDeviceClass.ENUM
    assert "good" in filt.options
    assert filt.native_value == "good"


def test_switches_created_for_ac():
    coord, aid = _coord()
    switches = build_switches(coord, aid)
    keys = {s._attr_translation_key for s in switches}
    assert {"sleep_mode", "clean_air_mode", "ui_lock_mode", "scheduler_mode", "display_light"} <= keys
    display = next(s for s in switches if s._attr_translation_key == "display_light")
    # fixture reports DISPLAY_LIGHT_1 -> on
    assert display.is_on is True


def test_connectivity_binary_sensor():
    coord, aid = _coord()
    ent = ElectroluxConnectivity(coord, aid)
    assert ent._attr_device_class == BinarySensorDeviceClass.CONNECTIVITY
    assert ent.is_on is True  # fixture connection_state == connected
    # available even if disconnected
    coord.data[aid].connection_state = "disconnected"
    assert ent.available is True
    assert ent.is_on is False
```

> **Implementer note:** the plan asks each platform module to expose a small pure builder (`build_sensors(coordinator, appliance_id) -> list`, `build_switches(...) -> list`) that `async_setup_entry` calls with a flat list over all appliances. This keeps the entity-generation logic unit-testable without spinning up HA. `async_setup_entry` becomes: `async_add_entities(e for aid in coordinator.data for e in build_sensors(coordinator, aid))`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_platforms.py -v`
Expected: FAIL — platform modules not found.

- [ ] **Step 3: Implement the four platform files**

`sensor.py`:
```python
"""Sensor platform for Electrolux AC."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    PROP_AMBIENT_TEMP_C,
    PROP_FILTER_STATE,
    PROP_NETWORK_INTERFACE,
)
from .coordinator import ElectroluxCoordinator
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


def build_sensors(
    coordinator: ElectroluxCoordinator, appliance_id: str
) -> list[SensorEntity]:
    appliance = coordinator.data[appliance_id]
    sensors: list[SensorEntity] = []
    if PROP_AMBIENT_TEMP_C in appliance.reported:
        sensors.append(AmbientTemperatureSensor(coordinator, appliance_id))
    if PROP_FILTER_STATE in appliance.capabilities:
        sensors.append(FilterStateSensor(coordinator, appliance_id))
    if PROP_NETWORK_INTERFACE in appliance.reported:
        sensors.append(LinkQualitySensor(coordinator, appliance_id))
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        e for aid in coordinator.data for e in build_sensors(coordinator, aid)
    )


class AmbientTemperatureSensor(ElectroluxEntity, SensorEntity):
    _attr_translation_key = "ambient_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_ambient_temperature"

    @property
    def native_value(self) -> float | None:
        return self.appliance.reported.get(PROP_AMBIENT_TEMP_C)


class FilterStateSensor(ElectroluxEntity, SensorEntity):
    _attr_translation_key = "filter_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_filter_state"
        values = self.appliance.capabilities[PROP_FILTER_STATE].get("values", {})
        self._attr_options = [v.lower() for v in values]

    @property
    def native_value(self) -> str | None:
        val = self.appliance.reported.get(PROP_FILTER_STATE)
        return val.lower() if isinstance(val, str) else None


class LinkQualitySensor(ElectroluxEntity, SensorEntity):
    _attr_translation_key = "link_quality"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_link_quality"

    @property
    def native_value(self) -> str | None:
        return self.appliance.reported.get(PROP_NETWORK_INTERFACE, {}).get(
            "linkQualityIndicator"
        )
```

`switch.py`:
```python
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
```

`select.py`:
```python
"""Select platform for Electrolux AC (no selects for the AC in v1; future-proof)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .models import ElectroluxConfigEntry

# No multi-value readwrite string capabilities that aren't covered by climate.
SELECT_CAPABILITIES: tuple = ()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([])
```

`binary_sensor.py`:
```python
"""Binary sensor platform for Electrolux AC."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONNECTION_CONNECTED
from .entity import ElectroluxEntity
from .models import ElectroluxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ElectroluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ElectroluxConnectivity(coordinator, aid) for aid in coordinator.data
    )


class ElectroluxConnectivity(ElectroluxEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator, appliance_id) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}_connectivity"

    @property
    def available(self) -> bool:
        # Stay available even when the appliance is disconnected, so this
        # sensor can actually report "disconnected".
        return (
            self.coordinator.last_update_success
            and self._appliance_id in self.coordinator.data
        )

    @property
    def is_on(self) -> bool:
        return self.appliance.connection_state == CONNECTION_CONNECTED
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_platforms.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/sensor.py custom_components/electrolux_ac/switch.py custom_components/electrolux_ac/select.py custom_components/electrolux_ac/binary_sensor.py tests/test_platforms.py
git commit -m "feat: sensor, switch, select, binary_sensor platforms (capability-driven)"
```

---

### Task 9: Translations + icons

**Execution note:** mechanical (static JSON) → run on Sonnet.

**Files:**
- Create: `custom_components/electrolux_ac/translations/en.json`
- Create: `custom_components/electrolux_ac/translations/pt-BR.json`
- Create: `custom_components/electrolux_ac/icons.json`
- Test: `tests/test_translations.py`

**Interfaces:**
- Consumes: the translation_keys used in Tasks 6–8 (config flow steps/errors; entity keys `ambient_temperature`, `filter_state`, `link_quality`, `sleep_mode`, `clean_air_mode`, `ui_lock_mode`, `scheduler_mode`, `display_light`, `connectivity`).
- Produces: valid translation + icons JSON. Every translation_key and config error key referenced in code must have an entry.

**Design notes:**
- `config.step.user.data` labels the three fields; `config.step.reauth_confirm.data` too. `config.error.invalid_auth`, `config.error.cannot_connect`. `config.abort.already_configured`, `config.abort.reauth_successful`, `config.abort.wrong_account`.
- Entity section: `sensor.filter_state.state` maps snake_case option keys (`good`, `clean`, `change`, `buy`) to display text; `sensor.link_quality` name only.
- State keys must exactly match the values produced by the entities (filter states are lowercased in Task 8, so keys are lowercase).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_translations.py
import json
from pathlib import Path

BASE = Path(__file__).parent.parent / "custom_components" / "electrolux_ac"


def test_en_translations_cover_keys():
    data = json.loads((BASE / "translations" / "en.json").read_text(encoding="utf-8"))
    # config flow
    assert "user" in data["config"]["step"]
    assert "reauth_confirm" in data["config"]["step"]
    assert data["config"]["error"]["invalid_auth"]
    assert data["config"]["error"]["cannot_connect"]
    assert data["config"]["abort"]["already_configured"]
    assert data["config"]["abort"]["reauth_successful"]
    assert data["config"]["abort"]["wrong_account"]
    # entities
    ent = data["entity"]
    assert ent["sensor"]["ambient_temperature"]["name"]
    assert ent["sensor"]["filter_state"]["state"]["good"]
    assert ent["switch"]["sleep_mode"]["name"]
    assert ent["switch"]["display_light"]["name"]
    assert ent["binary_sensor"]["connectivity"]["name"]


def test_ptbr_translations_valid_json():
    data = json.loads((BASE / "translations" / "pt-BR.json").read_text(encoding="utf-8"))
    assert "config" in data and "entity" in data


def test_icons_valid_json():
    data = json.loads((BASE / "icons.json").read_text(encoding="utf-8"))
    assert "entity" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_translations.py -v`
Expected: FAIL — files don't exist.

- [ ] **Step 3: Create the JSON files**

`translations/en.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Electrolux AC",
        "description": "Enter the API key and JWT tokens from the Electrolux developer portal (developer.electrolux.one).",
        "data": {
          "api_key": "API key",
          "access_token": "Access token (JWT)",
          "refresh_token": "Refresh token"
        }
      },
      "reauth_confirm": {
        "title": "Re-authenticate Electrolux AC",
        "description": "Your tokens expired. Paste fresh tokens from the developer portal.",
        "data": {
          "api_key": "API key",
          "access_token": "Access token (JWT)",
          "refresh_token": "Refresh token"
        }
      }
    },
    "error": {
      "invalid_auth": "Invalid credentials. Check your API key and tokens.",
      "cannot_connect": "Failed to connect to the Electrolux API."
    },
    "abort": {
      "already_configured": "This Electrolux account is already configured.",
      "reauth_successful": "Re-authentication was successful.",
      "wrong_account": "The tokens belong to a different Electrolux account."
    }
  },
  "entity": {
    "sensor": {
      "ambient_temperature": {"name": "Ambient temperature"},
      "filter_state": {
        "name": "Filter",
        "state": {
          "good": "Good",
          "clean": "Clean",
          "change": "Change",
          "buy": "Buy new"
        }
      },
      "link_quality": {"name": "Wi-Fi signal"}
    },
    "switch": {
      "sleep_mode": {"name": "Sleep mode"},
      "clean_air_mode": {"name": "Clean air"},
      "ui_lock_mode": {"name": "Panel lock"},
      "scheduler_mode": {"name": "Scheduler"},
      "display_light": {"name": "Display light"}
    },
    "binary_sensor": {
      "connectivity": {"name": "Connectivity"}
    }
  }
}
```

`translations/pt-BR.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Electrolux AC",
        "description": "Informe a chave de API e os tokens JWT do portal de desenvolvedor da Electrolux (developer.electrolux.one).",
        "data": {
          "api_key": "Chave de API",
          "access_token": "Token de acesso (JWT)",
          "refresh_token": "Token de atualização"
        }
      },
      "reauth_confirm": {
        "title": "Reautenticar Electrolux AC",
        "description": "Seus tokens expiraram. Cole tokens novos do portal de desenvolvedor.",
        "data": {
          "api_key": "Chave de API",
          "access_token": "Token de acesso (JWT)",
          "refresh_token": "Token de atualização"
        }
      }
    },
    "error": {
      "invalid_auth": "Credenciais inválidas. Verifique a chave de API e os tokens.",
      "cannot_connect": "Falha ao conectar à API da Electrolux."
    },
    "abort": {
      "already_configured": "Esta conta Electrolux já está configurada.",
      "reauth_successful": "Reautenticação concluída com sucesso.",
      "wrong_account": "Os tokens pertencem a outra conta Electrolux."
    }
  },
  "entity": {
    "sensor": {
      "ambient_temperature": {"name": "Temperatura ambiente"},
      "filter_state": {
        "name": "Filtro",
        "state": {
          "good": "Bom",
          "clean": "Limpar",
          "change": "Trocar",
          "buy": "Comprar novo"
        }
      },
      "link_quality": {"name": "Sinal Wi-Fi"}
    },
    "switch": {
      "sleep_mode": {"name": "Modo noturno"},
      "clean_air_mode": {"name": "Ar limpo"},
      "ui_lock_mode": {"name": "Trava do painel"},
      "scheduler_mode": {"name": "Agendador"},
      "display_light": {"name": "Luz do display"}
    },
    "binary_sensor": {
      "connectivity": {"name": "Conectividade"}
    }
  }
}
```

`icons.json`:
```json
{
  "entity": {
    "switch": {
      "sleep_mode": {"default": "mdi:power-sleep"},
      "clean_air_mode": {"default": "mdi:air-purifier"},
      "ui_lock_mode": {"default": "mdi:lock"},
      "scheduler_mode": {"default": "mdi:calendar-clock"},
      "display_light": {"default": "mdi:television-ambient-light"}
    },
    "sensor": {
      "filter_state": {"default": "mdi:air-filter"},
      "link_quality": {"default": "mdi:wifi"}
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_translations.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/electrolux_ac/translations/ custom_components/electrolux_ac/icons.json tests/test_translations.py
git commit -m "feat: en/pt-BR translations and entity icons"
```

---

### Task 10: HACS metadata, CI workflow, README, dev deps

**Execution note:** mechanical (config files + prose) → run on Sonnet.

**Files:**
- Create: `hacs.json`
- Create: `.github/workflows/validate.yml`
- Create: `README.md`
- Modify: `pyproject.toml` (add dev dependency note)
- Test: `tests/test_manifest.py`

**Interfaces:**
- Produces: HACS-valid repo metadata + CI that runs hassfest, HACS validate, and pytest.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest.py
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_manifest_has_hacs_required_keys():
    manifest = json.loads(
        (ROOT / "custom_components" / "electrolux_ac" / "manifest.json").read_text()
    )
    for key in ("domain", "name", "version", "documentation", "issue_tracker", "codeowners"):
        assert key in manifest, f"manifest missing {key}"
    assert manifest["domain"] == "electrolux_ac"
    assert manifest["config_flow"] is True


def test_hacs_json_has_name():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL — `hacs.json` not found.

- [ ] **Step 3: Create the files**

`hacs.json`:
```json
{
  "name": "Electrolux AC",
  "homeassistant": "2025.3.0",
  "render_readme": true
}
```

> **Why 2025.3.0:** the platforms import `AddConfigEntryEntitiesCallback`, which first ships in HA 2025.3.0 (absent in 2025.2.x). Declaring a lower floor would let HACS install on a version where the platform import raises `ImportError` and no entities load.

`.github/workflows/validate.yml`:
```yaml
name: Validate

on:
  push:
  pull_request:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

jobs:
  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master

  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: HACS validation
        uses: hacs/action@main
        with:
          category: integration
          ignore: brands

  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -r requirements_test.txt
      - run: pytest -v
```

`requirements_test.txt`:
```
pytest-homeassistant-custom-component==0.13.346
```

> **Environment note (already provisioned locally):** the test environment uses **Python 3.14 + `pytest-homeassistant-custom-component==0.13.346`, which bundles Home Assistant 2026.7.2** — the exact HA version running on the user's HAOS server, and one that ships `AddConfigEntryEntitiesCallback`. Run all `pytest` commands with the repo's `.venv` interpreter (`.venv/Scripts/python.exe -m pytest ...`). Do not downgrade PHACC — an older one bundles an HA too old for `AddConfigEntryEntitiesCallback`.

`README.md`:
```markdown
# Electrolux AC — Home Assistant integration

Control Electrolux (and Electrolux-brand, e.g. Frigidaire) air conditioners in
Home Assistant through the official Electrolux Group Developer API, with
real-time updates over SSE.

> Not affiliated with, developed, or supported by Electrolux.

## Features

- `climate` entity: on/off, modes (cool/auto/dry/fan-only), target temperature,
  fan speed, vertical swing — all driven by what your unit reports as supported.
- Sensors: ambient temperature, filter state, Wi-Fi signal.
- Switches: sleep mode, clean air, panel lock, scheduler, display light.
- Connectivity binary sensor.
- Real-time push via the Electrolux livestream (SSE) with a 5-minute
  reconciliation poll.

## Requirements

An Electrolux developer API key and JWT tokens. Get them at
[developer.electrolux.one](https://developer.electrolux.one):

1. Sign in with your Electrolux app account.
2. Create an API key on the dashboard.
3. Generate an access token + refresh token.

## Installation (HACS)

1. In HACS → Integrations → three-dot menu → **Custom repositories**.
2. Add `https://github.com/lbkeppler/eletrolux-ac` with category **Integration**.
3. Install **Electrolux AC**, then restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → **Electrolux AC**.
5. Paste your API key, access token, and refresh token.

## Notes

- Free tier limits: 10 req/s, 5000 req/day, one SSE channel. The integration
  uses a single SSE connection plus a 5-minute poll, well within the quota.
- Tokens are stored in Home Assistant and refreshed automatically; if refresh
  fails you'll be prompted to re-authenticate.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: ALL tests pass across every module.

- [ ] **Step 6: Commit**

```bash
git add hacs.json .github/ README.md requirements_test.txt tests/test_manifest.py pyproject.toml
git commit -m "chore: HACS metadata, CI (hassfest + HACS + pytest), README"
```

---

## Self-Review (completed by plan author)

**Spec coverage** — every spec section maps to a task:
- API facts / endpoints → Task 2 (client), Task 3 (parsing).
- SSE format + reconnect → Task 2 (`async_iter_events`), Task 4 (`async_run_sse`).
- Token refresh + rotation + persistence → Task 2 (`_async_refresh`), Task 5 (`_persist_tokens`).
- Coordinator push + 5-min poll → Task 4.
- Config flow + reauth → Task 6.
- Capability-driven entities (climate/sensor/switch/select/binary_sensor) → Tasks 7–8.
- Device registry grouping → Task 7 (`entity.py` `DeviceInfo`).
- Error handling (401/406/UpdateFailed/reauth) → Tasks 2, 4, 6.
- Translations → Task 9.
- HACS + CI + security (.gitignore already done) → Task 10.
- Out-of-scope items (triggers, other appliance types, scheduler UI, HACS default store) → correctly omitted.

**Placeholder scan** — the only intentional deferrals are the two implementer notes with explicit resolution paths: (a) the 401-retry test's mock sequencing, and (b) the PHACC/Python-version pin. Both give the engineer a concrete decision procedure, not a blank "TODO". `FAKE_JWT` has a generation snippet.

**Type consistency** — verified: `ApplianceData` fields, `ElectroluxConfigEntry` alias, `Tokens`, coordinator method names (`async_send_command`, `async_run_sse`, `_async_update_data`), `build_sensors`/`build_switches` builders, and `const` map names (`HVAC_MODE_MAP`, `FAN_MODE_MAP`, `PROP_*`) are used consistently across tasks.

## Adversarial review — defects fixed before execution

A 5-lens multi-agent review (HA-API correctness, Electrolux API contract, async/lifecycle, test validity, completeness), each finding adversarially re-verified, surfaced 8 confirmed defects. All are already corrected inline above:

1. **[critical, Task 2]** `_request` read `resp.content_length`, which the test mock (`AiohttpClientMockResponse`) doesn't define — every 200/202 would `AttributeError`. Fixed: branch on `resp.status == 204` then read `resp.text()`.
2. **[high, Task 4]** `_handle_event`/`async_send_command` used `async_set_updated_data`, which resets the 5-min poll timer — a chatty SSE stream would starve the reconciliation poll forever. Fixed: `self.data = new_data; self.async_update_listeners()`.
3. **[high, Task 2]** SSE `sock_read=None` gave no keepalive guard — a half-open stream would hang indefinitely. Fixed: `sock_read=120`.
4. **[medium, Task 2]** `403` mapped to `ElectroluxAuthError` → spurious reauth flow on a per-resource forbidden. Fixed: only `401` → auth error; `403` → `ElectroluxApiError` → `UpdateFailed`.
5. **[medium, Task 4]** AC filter dropped the spec's `deviceType`/`AIR_CONDITIONER` fallback → an appliance not typed exactly `"AC"` yielded zero entities silently. Fixed: fetch `/info` for all, filter on `applianceType == "AC"` OR `deviceType` containing `AIR_CONDITIONER`, warn on zero ACs. Added two coordinator tests.
6. **[low, Task 2]** Concurrent 401s could double-refresh (double token rotation). Fixed: double-checked locking in `_async_refresh`.
7. **[low, Task 6]** `FAKE_JWT = "GENERATE_ME"` isn't a decodable JWT — config-flow tests would error. Fixed: real HS256 token with `sub=acct-123` (verified to decode).
8. **[low, Task 10]** `hacs.json` floor `2025.1.0` < the `2025.3.0` that first ships `AddConfigEntryEntitiesCallback` → `ImportError` on a permitted install. Fixed: floor raised to `2025.3.0`.

One finding was verified UNCERTAIN (the AC-filter "no-op install" premise couldn't be demonstrated on known fixtures) but its spec-conformance fix was applied anyway (item 5).

