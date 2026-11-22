"""Offline tests for presence prerequisites and 2026.11 conditional option forms."""

import ast
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "custom_components" / "nextcloud_memories"

spec = importlib.util.spec_from_file_location("presence_offline", SRC / "presence.py")
assert spec is not None and spec.loader is not None
presence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presence)


def test_absent_conditions_keep_existing_behaviour():
    assert presence.presence_conditions_met({}, lambda _: None)


def test_all_on_and_off_conditions():
    profile = {
        presence.PRESENCE_REQUIRE_ON: ["input_boolean.photos_enabled", "switch.power"],
        presence.PRESENCE_REQUIRE_OFF: ["input_boolean.sleeping"],
    }
    states = {
        "input_boolean.photos_enabled": "on",
        "switch.power": "on",
        "input_boolean.sleeping": "off",
    }
    assert presence.presence_conditions_met(profile, states.get)
    states["input_boolean.sleeping"] = "on"
    assert not presence.presence_conditions_met(profile, states.get)
    states["input_boolean.sleeping"] = "off"
    states["switch.power"] = "unavailable"
    assert not presence.presence_conditions_met(profile, states.get)
    states["switch.power"] = "unknown"
    assert not presence.presence_conditions_met(profile, states.get)
    del states["switch.power"]
    assert not presence.presence_conditions_met(profile, states.get)


def test_conflicting_on_off_requirements_fail_closed():
    profile = {
        presence.PRESENCE_REQUIRE_ON: ["switch.example"],
        presence.PRESENCE_REQUIRE_OFF: ["switch.example"],
    }
    assert not presence.presence_conditions_valid(profile)
    assert not presence.presence_conditions_met(profile, lambda _: "on")


def test_normalization_excludes_presence_itself_and_duplicates():
    values = [" switch.a ", "switch.a", "binary_sensor.presence", "", "switch.b"]
    assert presence.normalize_condition_entities(
        values, "binary_sensor.presence"
    ) == ["switch.a", "switch.b"]


def test_no_presence_discards_options():
    assert presence.normalize_condition_entities(["switch.a"], "") == []
    assert presence.normalize_condition_entities(["switch.a"], None) == ["switch.a"]


def test_options_schema_has_conditional_visibility():
    source = (SRC / "config_flow.py").read_text()
    assert 'visible={"field": "presence_entity_id", "operator": "exists"}' in source
    assert '"target_device_key"' in source
    assert '"value": ["edit", "delete"]' in source


def test_on_gate_is_independent_of_off():
    source = (SRC / "__init__.py").read_text()
    tree = ast.parse(source)
    function = next(
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "_async_apply_presence_backlight"
    )
    calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)]
    assert any(
        isinstance(n.func, ast.Name) and n.func.id == "presence_conditions_met"
        for n in calls
    )
    assert any(
        isinstance(n, ast.Attribute) and n.func.attr == "async_call"
        for n in calls
    )
