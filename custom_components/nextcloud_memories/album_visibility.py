"""Helpers for showing user-created albums in the frame editor.

Memories can return synthetic public-link albums whose names or IDs start
with a dot (for example, ".link-..." and "admin/.link-..."). Keep them
available through the API but do not offer them as normal frame albums.
"""

from __future__ import annotations

from typing import Any, Mapping


def is_album_visible_in_picker(album: Mapping[str, Any]) -> bool:
    """Hide dot-prefixed albums, including public-link identifiers."""
    album_id = str(album.get("id") or "").strip()
    if not album_id:
        return False

    name = str(album.get("name") or album_id).strip()
    return not (name.startswith(".") or album_id.rsplit("/", 1)[-1].startswith("."))
