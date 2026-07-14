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
