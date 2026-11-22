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
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:b[0-9]+)?", manifest["version"])
    assert manifest["config_flow"] is True
    assert manifest["documentation"].startswith("https://github.com/fherreror/")
    assert manifest["issue_tracker"].startswith("https://github.com/fherreror/")
    assert hacs["name"]
    assert hacs["homeassistant"] == "2026.11.0"


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


def test_spanish_translations_cover_source_keys():
    original = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    spanish = json.loads(
        (INTEGRATION / "translations" / "es.json").read_text(encoding="utf-8")
    )

    def assert_same_structure(source, translated):
        assert set(source) == set(translated)
        for key, value in source.items():
            if isinstance(value, dict):
                assert isinstance(translated[key], dict)
                assert_same_structure(value, translated[key])
            else:
                assert isinstance(translated[key], str) and translated[key].strip()
                assert set(re.findall(r"\{(\w+)\}", value)) == set(
                    re.findall(r"\{(\w+)\}", translated[key])
                )

    assert_same_structure(original, spanish)


def test_translatable_form_selectors_and_presence_dependencies():
    source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert 'translation_key="frame_action"' in source
    assert 'translation_key="frame_image_format"' in source
    assert source.count('visible={"field": "presence_entity_id", "operator": "exists"}') == 2
    assert 'visible={"field": "action", "operator": "in", "value": ["edit", "delete"]}' in source
