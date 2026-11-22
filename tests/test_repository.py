"""Repository structure and metadata checks; no Home Assistant installation required."""

import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "nextcloud_memories"


def test_manifest_and_hacs_metadata():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert manifest["domain"] == INTEGRATION.name
    assert re.fullmatch("[0-9]+[.][0-9]+[.][0-9]+", manifest["version"])
    assert manifest["config_flow"] is True
    assert manifest["documentation"].startswith("https://github.com/fherreror/")
    assert manifest["issue_tracker"].startswith("https://github.com/fherreror/")
    assert hacs["name"]


def test_english_translations_match_source_strings():
    original = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    translation = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert translation == original


def test_service_definitions_are_present():
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text())
    assert set(services) == {
        "get_albums",
        "get_photo_list",
        "get_photo",
        "frame_refresh",
        "frame_reset",
        "frame_device_set",
        "frame_device_list",
        "frame_device_delete",
    }
