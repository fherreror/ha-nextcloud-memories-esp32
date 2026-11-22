"""Offline regression tests for ESPHome device registry lookups.

Extract only the two pure resolver functions so the tests can run without
Home Assistant, an ESP32, or a Nextcloud server.
"""

import ast
from pathlib import Path
import re
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "nextcloud_memories" / "__init__.py"


class IterableDevices:
    """Current HA registry style: devices are iterable DeviceEntry objects."""

    def __init__(self, entries):
        self.entries = entries

    def __iter__(self):
        return iter(self.entries)

    def values(self):
        raise AssertionError("Deprecated registry.devices.values() called")


class Device:
    def __init__(self, name, config_entry_id, mac, identifiers=()):
        self.name = name
        self.name_by_user = None
        self.config_entry_id = config_entry_id
        self.connections = {("mac", mac)}
        self.identifiers = set(identifiers)
        self.id = "device-123"

    @property
    def config_entries(self):
        raise AssertionError("Deprecated DeviceEntry.config_entries accessed")


def load_resolvers(devices, entities=()):
    """Load resolver functions with fake Home Assistant registry modules."""
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [
        node for node in parsed.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"resolve_esp_device_mac", "_resolve_esp_backlight_entity"}
    ]
    assert len(selected) == 2
    module = ast.Module(
        body=[ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0
        ), *selected],
        type_ignores=[],
    )
    registry = SimpleNamespace(devices=IterableDevices(devices))
    entity_registry = SimpleNamespace()
    dr = SimpleNamespace(async_get=lambda hass: registry, CONNECTION_NETWORK_MAC="mac")
    er = SimpleNamespace(
        async_get=lambda hass: entity_registry,
        async_entries_for_device=lambda registry, device_id: entities,
    )
    scope = {
        "re": re,
        "dr": dr,
        "er": er,
        "_sanitize_esp_device_id": lambda value: value,
    }
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), scope)
    return scope


def fake_hass(domains):
    return SimpleNamespace(config_entries=SimpleNamespace(
        async_get_entry=lambda entry_id: (
            SimpleNamespace(domain=domains[entry_id]) if entry_id in domains else None
        )
    ))


def test_mac_resolver_reads_iterable_devices_and_single_entry():
    devices = [
        Device("not-the-target", "entry-a", "AA:AA:AA:AA:AA:AA"),
        Device("Living Room Frame", "entry-esp", "BB:BB:BB:BB:BB:BB"),
    ]
    namespace = load_resolvers(devices)
    result = namespace["resolve_esp_device_mac"](
        fake_hass({"entry-a": "other", "entry-esp": "esphome"}),
        "living_room_frame",
    )
    assert result == "bb:bb:bb:bb:bb:bb"


def test_identifier_matching_uses_esphome_entry():
    devices = [
        Device("Unrelated", "entry-other", "AA:AA:AA:AA:AA:AA",
               {("esphome", "frame_one")}),
        Device("Unrelated", "entry-esp", "BB:BB:BB:BB:BB:BB",
               {("esphome", "frame_one")}),
    ]
    namespace = load_resolvers(devices)
    result = namespace["resolve_esp_device_mac"](
        fake_hass({"entry-other": "other", "entry-esp": "esphome"}),
        "frame_one",
    )
    assert result == "bb:bb:bb:bb:bb:bb"


def test_backlight_resolver_filters_esphome_and_prefers_lcd():
    devices = [
        Device("Frame", "entry-other", "BB:BB:BB:BB:BB:BB"),
        Device("Frame", "entry-esp", "BB:BB:BB:BB:BB:BB"),
    ]
    entities = [
        SimpleNamespace(
            domain="switch", platform="esphome", original_name="Backlight",
            name=None, entity_id="switch.frame_backlight"
        ),
        SimpleNamespace(
            domain="switch", platform="esphome", original_name="LCD Backlight",
            name=None, entity_id="switch.frame_lcd_backlight"
        ),
    ]
    ns = load_resolvers(devices, entities)
    # The MAC resolver chooses the first matching name. For this call both
    # matching devices share the MAC, but only ESPHome entries are inspected
    # for the backlight switch.
    result = ns["_resolve_esp_backlight_entity"](
        fake_hass({"entry-other": "other", "entry-esp": "esphome"}), "Frame"
    )
    assert result == "switch.frame_lcd_backlight"


def test_no_device_or_missing_config_entry():
    ns = load_resolvers([Device("Frame", None, "BB:BB:BB:BB:BB:BB")])
    assert ns["resolve_esp_device_mac"](fake_hass({}), "unknown") is None
    assert ns["_resolve_esp_backlight_entity"](fake_hass({}), "Frame") is None


def test_no_deprecated_registry_usage():
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"resolve_esp_device_mac", "_resolve_esp_backlight_entity"}
    ]
    for function in functions:
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == "device":
                    assert node.attr != "config_entries"
                if node.attr == "values":
                    assert not (
                        isinstance(node.value, ast.Attribute)
                        and node.value.attr == "devices"
                    )
