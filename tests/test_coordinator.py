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
