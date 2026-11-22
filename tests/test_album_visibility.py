"""Tests that public-link placeholder albums stay out of the frame selector."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "custom_components" / "nextcloud_memories" / "album_visibility.py"
spec = importlib.util.spec_from_file_location("album_visibility_test", HELPER)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_dot_prefixed_album_names_are_hidden():
    assert not mod.is_album_visible_in_picker({
        "id": "admin/.link-7oyuko084s", "name": ".link-7oyuko084s"
    })
    assert not mod.is_album_visible_in_picker({
        "id": "admin/other", "name": ".hidden-album"
    })


def test_public_links_hidden_even_when_display_name_differs():
    assert not mod.is_album_visible_in_picker({
        "id": "admin/.link-example", "name": "Shared photos"
    })


def test_regular_albums_remain_visible():
    assert mod.is_album_visible_in_picker({
        "id": "admin/Boda Esther", "name": "Boda Esther"
    })
    assert mod.is_album_visible_in_picker({
        "id": "admin/.archive/Family", "name": "Family"
    })
    assert not mod.is_album_visible_in_picker({"id": "", "name": "No ID"})


def test_picker_filters_without_deleting_saved_album_selections():
    source = (ROOT / "custom_components" / "nextcloud_memories" / "config_flow.py").read_text()
    assert "if not is_album_visible_in_picker(album):" in source
    assert "for aid in defaults.get(\"album_ids\", []) or []:" in source
