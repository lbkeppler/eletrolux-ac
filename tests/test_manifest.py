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
