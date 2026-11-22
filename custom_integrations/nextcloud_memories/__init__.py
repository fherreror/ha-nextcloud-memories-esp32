"""The Nextcloud Memories integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import io
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
import re
from typing import Any
import logging
import random

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .api import NextcloudMemoriesClient
from .const import (
    CACHE_DIR_NAME,
    CONF_API_TOKEN,
    CONF_BASE_URL,
    CONF_ENTRY_ID,
    CONF_IMAGE_BASE_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_HEIGHT,
    DEFAULT_MAX_PHOTOS,
    DEFAULT_ROTATION_MINUTES,
    DEFAULT_WIDTH,
    DOMAIN,
    SIGNAL_FRAME_STATE_PREFIX,
    SERVICE_FRAME_REFRESH,
    SERVICE_FRAME_DEVICE_DELETE,
    SERVICE_FRAME_DEVICE_LIST,
    SERVICE_FRAME_DEVICE_SET,
    SERVICE_FRAME_RESET,
    SERVICE_GET_ALBUMS,
    SERVICE_GET_PHOTO,
    SERVICE_GET_PHOTO_LIST,
)

_LOGGER = logging.getLogger(__name__)
IMAGE_FORMATS = ("jpeg", "bmp24")
DEFAULT_IMAGE_FORMAT = "jpeg"

try:
    from PIL import Image, ImageFilter, ImageOps  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    Image = None

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.NUMBER]


@dataclass
class RuntimeEntry:
    """Runtime object per config entry."""

    client: NextcloudMemoriesClient
    frame_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    frame_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    frame_prefetch_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    frame_rotation_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    presence_unsubs: list[Callable[[], None]] = field(default_factory=list)
    frame_devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    frame_store: Store | None = None


type MemoriesConfigEntry = ConfigEntry[RuntimeEntry]


SERVICE_GET_ALBUMS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTRY_ID): str,
        vol.Optional("include_raw", default=False): bool,
    }
)

SERVICE_GET_PHOTO_LIST_SCHEMA = vol.Schema(
    {
        vol.Required("album_id"): str,
        vol.Optional("max_photos", default=DEFAULT_MAX_PHOTOS): vol.All(
            int, vol.Range(min=1, max=5000)
        ),
        vol.Optional("randomize", default=False): bool,
        vol.Optional(CONF_ENTRY_ID): str,
        vol.Optional("include_raw", default=False): bool,
    }
)

SERVICE_GET_PHOTO_SCHEMA = vol.Schema(
    {
        vol.Required("fileid"): int,
        vol.Optional("album_id"): str,
        vol.Optional("etag"): str,
        vol.Optional("width", default=DEFAULT_WIDTH): vol.All(
            int, vol.Range(min=16, max=4096)
        ),
        vol.Optional("height", default=DEFAULT_HEIGHT): vol.All(
            int, vol.Range(min=16, max=4096)
        ),
        vol.Optional("image_format", default=DEFAULT_IMAGE_FORMAT): vol.In(IMAGE_FORMATS),
        vol.Optional("filename"): str,
        vol.Optional(CONF_ENTRY_ID): str,
    }
)

SERVICE_FRAME_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Optional("device_key"): str,
        vol.Optional("esp_device_id"): str,
        vol.Optional("album_id"): str,
        vol.Optional("album_ids"): [str],
        vol.Optional("direction", default="next"): vol.In(("next", "prev", "stay")),
        vol.Optional("width", default=DEFAULT_WIDTH): vol.All(
            int, vol.Range(min=16, max=4096)
        ),
        vol.Optional("height", default=DEFAULT_HEIGHT): vol.All(
            int, vol.Range(min=16, max=4096)
        ),
        vol.Optional("image_format"): vol.In(IMAGE_FORMATS),
        vol.Optional("randomize", default=True): bool,
        vol.Optional("force_reload", default=False): bool,
        vol.Optional("max_photos", default=500): vol.All(
            int, vol.Range(min=1, max=5000)
        ),
        vol.Optional("max_cache_files", default=40): vol.All(
            int, vol.Range(min=5, max=500)
        ),
        vol.Optional("prefetch_each_side", default=5): vol.All(
            int, vol.Range(min=1, max=20)
        ),
        vol.Optional("target_current_text_entity"): str,
        vol.Optional("target_prev_text_entity"): str,
        vol.Optional("target_next_text_entity"): str,
        vol.Optional(CONF_ENTRY_ID): str,
    }
)

SERVICE_FRAME_RESET_SCHEMA = vol.Schema(
    {
        vol.Required("device_key"): str,
        vol.Optional(CONF_ENTRY_ID): str,
    }
)

SERVICE_FRAME_DEVICE_SET_SCHEMA = vol.Schema(
    {
        vol.Required("device_key"): str,
        vol.Optional("esp_device_id"): str,
        vol.Required("album_ids"): vol.All([str], vol.Length(min=1)),
        vol.Optional("name"): str,
        vol.Optional("width", default=DEFAULT_WIDTH): vol.All(
            int, vol.Range(min=16, max=4096)
        ),
        vol.Optional("height", default=DEFAULT_HEIGHT): vol.All(
            int, vol.Range(min=16, max=4096)
        ),
        vol.Optional("image_format", default=DEFAULT_IMAGE_FORMAT): vol.In(IMAGE_FORMATS),
        vol.Optional("randomize", default=True): bool,
        vol.Optional("max_photos", default=500): vol.All(
            int, vol.Range(min=1, max=5000)
        ),
        vol.Optional("max_cache_files", default=40): vol.All(
            int, vol.Range(min=5, max=500)
        ),
        vol.Optional("prefetch_each_side", default=5): vol.All(
            int, vol.Range(min=1, max=20)
        ),
        vol.Optional("rotation_minutes", default=DEFAULT_ROTATION_MINUTES): vol.All(
            int, vol.Range(min=1, max=30)
        ),
        vol.Optional("presence_entity_id"): str,
        vol.Optional("target_current_text_entity"): str,
        vol.Optional("target_prev_text_entity"): str,
        vol.Optional("target_next_text_entity"): str,
        vol.Optional(CONF_ENTRY_ID): str,
    }
)

SERVICE_FRAME_DEVICE_DELETE_SCHEMA = vol.Schema(
    {
        vol.Required("device_key"): str,
        vol.Optional(CONF_ENTRY_ID): str,
    }
)

SERVICE_FRAME_DEVICE_LIST_SCHEMA = vol.Schema({vol.Optional(CONF_ENTRY_ID): str})


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up from yaml (unused, but required by HA)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MemoriesConfigEntry) -> bool:
    """Set up a config entry."""
    session = async_get_clientsession(hass)
    client = NextcloudMemoriesClient(
        session=session,
        base_url=entry.data[CONF_BASE_URL],
        api_token=entry.data[CONF_API_TOKEN],
        username=entry.data.get(CONF_USERNAME),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
    )
    store = Store(hass, 1, f"{DOMAIN}.frame_devices.{entry.entry_id}")
    saved = await store.async_load() or {}
    frame_devices = saved.get("devices", {}) if isinstance(saved, dict) else {}
    if isinstance(frame_devices, dict):
        for profile in frame_devices.values():
            if isinstance(profile, dict):
                profile.setdefault("rotation_minutes", DEFAULT_ROTATION_MINUTES)
                profile.setdefault("image_format", DEFAULT_IMAGE_FORMAT)

    entry.runtime_data = RuntimeEntry(
        client=client,
        frame_devices=frame_devices if isinstance(frame_devices, dict) else {},
        frame_store=store,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry

    if CONF_IMAGE_BASE_URL not in entry.data:
        base = (
            (hass.config.internal_url or "").strip()
            or (hass.config.external_url or "").strip()
            or "http://homeassistant.local:8123"
        ).rstrip("/")
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_IMAGE_BASE_URL: base},
        )

    await _clear_device_cache_dirs(hass, list(entry.runtime_data.frame_devices.keys()))
    await _sync_frame_devices_registry(hass, entry)

    if not hass.services.has_service(DOMAIN, SERVICE_GET_ALBUMS):
        _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _migrate_frame_sensor_entity_ids(hass, entry)
    _bootstrap_frame_states(hass, entry)
    _sync_rotation_tasks(hass, entry)
    _sync_presence_listeners(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MemoriesConfigEntry) -> bool:
    """Unload one config entry."""
    for task in entry.runtime_data.frame_prefetch_tasks.values():
        if not task.done():
            task.cancel()
    entry.runtime_data.frame_prefetch_tasks.clear()
    for task in entry.runtime_data.frame_rotation_tasks.values():
        if not task.done():
            task.cancel()
    entry.runtime_data.frame_rotation_tasks.clear()
    for unsub in entry.runtime_data.presence_unsubs:
        unsub()
    entry.runtime_data.presence_unsubs.clear()

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if not hass.data.get(DOMAIN):
        for service_name in (
            SERVICE_GET_ALBUMS,
            SERVICE_GET_PHOTO_LIST,
            SERVICE_GET_PHOTO,
            SERVICE_FRAME_REFRESH,
            SERVICE_FRAME_RESET,
            SERVICE_FRAME_DEVICE_SET,
            SERVICE_FRAME_DEVICE_DELETE,
            SERVICE_FRAME_DEVICE_LIST,
        ):
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options/data change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    async def async_handle_get_albums(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        include_raw = bool(call.data.get("include_raw", False))

        albums = await entry.runtime_data.client.async_get_albums()
        if not include_raw:
            albums = [{"id": a["id"], "name": a["name"]} for a in albums]

        return {"count": len(albums), "albums": albums}

    async def async_handle_get_photo_list(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        album_id = str(call.data["album_id"]).strip()
        max_photos = int(call.data.get("max_photos", DEFAULT_MAX_PHOTOS))
        randomize = bool(call.data.get("randomize", False))
        include_raw = bool(call.data.get("include_raw", False))

        photos = await entry.runtime_data.client.async_get_photo_list(
            album_id=album_id,
            max_photos=max_photos,
            randomize=randomize,
        )
        if not include_raw:
            photos = [
                {
                    "fileid": p["fileid"],
                    "name": p.get("name"),
                    "path": p.get("path"),
                    "date": p.get("date"),
                    "etag": p.get("etag"),
                    "mimetype": p.get("mimetype"),
                    "width": p.get("w"),
                    "height": p.get("h"),
                }
                for p in photos
            ]

        return {
            "album_id": album_id,
            "count": len(photos),
            "randomize": randomize,
            "max_photos": max_photos,
            "photos": photos,
        }

    async def async_handle_get_photo(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        fileid = int(call.data["fileid"])
        album_id = call.data.get("album_id")
        etag = call.data.get("etag")
        width = int(call.data.get("width", DEFAULT_WIDTH))
        height = int(call.data.get("height", DEFAULT_HEIGHT))
        image_format = _normalize_image_format(call.data.get("image_format"))
        filename = call.data.get("filename")

        image_bytes = await entry.runtime_data.client.async_get_photo_preview(
            fileid=fileid,
            width=width,
            height=height,
            album_id=str(album_id).strip() if album_id else None,
            etag=str(etag).strip() if etag else None,
        )

        output_dir = Path(hass.config.path("www", CACHE_DIR_NAME))
        await hass.async_add_executor_job(
            partial(output_dir.mkdir, parents=True, exist_ok=True)
        )

        output_name = _build_output_name(
            entry_id=entry.entry_id,
            album_id=str(album_id or ""),
            fileid=fileid,
            width=width,
            height=height,
            image_format=image_format,
            filename=filename,
        )
        output_path = output_dir / output_name
        await hass.async_add_executor_job(
            partial(
                _write_processed_image_file,
                output_path,
                image_bytes,
                width,
                height,
                image_format,
            )
        )

        local_url = f"/local/{CACHE_DIR_NAME}/{output_name}"
        return {
            "fileid": fileid,
            "album_id": album_id,
            "width": width,
            "height": height,
            "local_url": local_url,
            "path": str(output_path),
        }

    async def async_handle_frame_refresh(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        device_key_value = call.data.get("device_key")
        esp_device_id = str(call.data.get("esp_device_id", "")).strip()
        if device_key_value:
            device_key = _sanitize_device_key(str(device_key_value))
        elif esp_device_id:
            device_key = _resolve_device_key_from_esp(entry, esp_device_id)
        else:
            raise ServiceValidationError("Pass device_key or esp_device_id")
        direction = str(call.data.get("direction", "next")).strip().lower()
        profile = entry.runtime_data.frame_devices.get(device_key, {})

        album_ids = _normalize_album_ids(call.data.get("album_ids"))
        if not album_ids:
            album_id_single = call.data.get("album_id")
            if album_id_single:
                album_ids = _normalize_album_ids([str(album_id_single)])
        if not album_ids:
            album_ids = _normalize_album_ids(profile.get("album_ids"))
        if not album_ids:
            raise ServiceValidationError(
                "No album configured. Pass album_id/album_ids or configure frame_device_set."
            )

        width = int(call.data.get("width", profile.get("width", DEFAULT_WIDTH)))
        height = int(call.data.get("height", profile.get("height", DEFAULT_HEIGHT)))
        image_format = _normalize_image_format(
            call.data.get("image_format", profile.get("image_format", DEFAULT_IMAGE_FORMAT))
        )
        randomize = bool(call.data.get("randomize", profile.get("randomize", True)))
        force_reload = bool(call.data.get("force_reload", False))
        max_photos = int(call.data.get("max_photos", profile.get("max_photos", 500)))
        max_cache_files = int(
            call.data.get("max_cache_files", profile.get("max_cache_files", 40))
        )
        prefetch_each_side = int(
            call.data.get("prefetch_each_side", profile.get("prefetch_each_side", 5))
        )

        target_current = call.data.get(
            "target_current_text_entity", profile.get("target_current_text_entity")
        )
        target_prev = call.data.get(
            "target_prev_text_entity", profile.get("target_prev_text_entity")
        )
        target_next = call.data.get(
            "target_next_text_entity", profile.get("target_next_text_entity")
        )

        lock = entry.runtime_data.frame_locks.setdefault(device_key, asyncio.Lock())
        async with lock:
            state = entry.runtime_data.frame_states.get(device_key, {})
            album_key = "|".join(album_ids)
            should_reload = (
                force_reload
                or state.get("album_key") != album_key
                or not state.get("photos")
                or state.get("randomize") != randomize
            )

            if should_reload:
                photos: list[dict[str, Any]] = []
                album_errors: list[dict[str, str]] = []
                for aid in album_ids:
                    try:
                        album_photos = await entry.runtime_data.client.async_get_photo_list(
                            album_id=aid,
                            max_photos=max_photos,
                            randomize=randomize,
                        )
                    except Exception as exc:  # pragma: no cover - runtime safety
                        _LOGGER.warning("frame_refresh album failed: device=%s album=%s err=%s", device_key, aid, exc)
                        album_errors.append({"album_id": aid, "error": str(exc)})
                        continue
                    for p in album_photos:
                        p2 = dict(p)
                        p2["_album_id"] = aid
                        photos.append(p2)
                if not photos:
                    msg = "No photos found for selected album(s)"
                    if album_errors:
                        msg = f"{msg}. Errors: {album_errors}"
                    raise ServiceValidationError(msg)
                # True global mix across all selected albums (not album-by-album blocks).
                if randomize and len(photos) > 1:
                    random.shuffle(photos)
                idx = 0
                if direction == "prev":
                    idx = len(photos) - 1
                state = {
                    "album_ids": album_ids,
                    "album_key": album_key,
                    "photos": photos,
                    "index": idx,
                    "randomize": randomize,
                    "album_errors": album_errors,
                }
            else:
                photos = state["photos"]
                if not photos:
                    raise ServiceValidationError("Photo state empty after reload")
                idx = int(state.get("index", 0))
                if direction == "next":
                    idx = (idx + 1) % len(photos)
                elif direction == "prev":
                    idx = (idx - 1) % len(photos)
                state["index"] = idx

            photos = state["photos"]
            idx = int(state["index"])
            current = photos[idx]
            prev_photo = photos[(idx - 1) % len(photos)]
            next_photo = photos[(idx + 1) % len(photos)]

            device_dir = Path(hass.config.path("www", CACHE_DIR_NAME, device_key))
            await hass.async_add_executor_job(
                partial(device_dir.mkdir, parents=True, exist_ok=True)
            )

            # Fast path for next/prev: return updated URLs immediately and prefetch in background.
            if not should_reload and direction in ("next", "prev", "stay"):
                current_url = _photo_local_url(device_key, current, width, height, image_format)
                prev_url = _photo_local_url(device_key, prev_photo, width, height, image_format)
                next_url = _photo_local_url(device_key, next_photo, width, height, image_format)
                prev_urls, next_urls = _window_urls(
                    device_key=device_key,
                    photos=photos,
                    idx=idx,
                    width=width,
                    height=height,
                    image_format=image_format,
                    prefetch_each_side=prefetch_each_side,
                )
                _schedule_prefetch_window(
                    hass=hass,
                    entry=entry,
                    device_key=device_key,
                    album_ids=album_ids,
                    photos=photos,
                    idx=idx,
                    width=width,
                    height=height,
                    image_format=image_format,
                    prefetch_each_side=prefetch_each_side,
                    max_cache_files=max_cache_files,
                )
            else:
                cache_map: dict[int, tuple[dict[str, Any], str, Path]] = {}
                dedup_indexes = _window_indexes(
                    idx=idx, count=len(photos), prefetch_each_side=prefetch_each_side
                )

                for widx in dedup_indexes:
                    wphoto = photos[widx]
                    wurl, wpath = await _cache_device_photo(
                        hass=hass,
                        entry=entry,
                        device_key=device_key,
                        album_id=str(wphoto.get("_album_id") or album_ids[0]),
                        photo=wphoto,
                        width=width,
                        height=height,
                        image_format=image_format,
                        device_dir=device_dir,
                    )
                    cache_map[widx] = (wphoto, wurl, wpath)

                _, current_url, _ = cache_map[idx]
                _, prev_url, _ = cache_map[(idx - 1) % len(photos)]
                _, next_url, _ = cache_map[(idx + 1) % len(photos)]

                prev_urls = []
                next_urls = []
                for step in range(1, prefetch_each_side + 1):
                    prev_idx = (idx - step) % len(photos)
                    next_idx = (idx + step) % len(photos)
                    if prev_idx in cache_map:
                        prev_urls.append(cache_map[prev_idx][1])
                    if next_idx in cache_map:
                        next_urls.append(cache_map[next_idx][1])

                await _cleanup_device_cache(
                    hass=hass,
                    device_dir=device_dir,
                    keep_paths={item[2] for item in cache_map.values()},
                    max_cache_files=max_cache_files,
                )

            entry.runtime_data.frame_states[device_key] = state
            async_dispatcher_send(hass, _frame_signal(entry.entry_id, device_key))

            for entity_id, value in (
                (target_current, current_url),
                (target_prev, prev_url),
                (target_next, next_url),
            ):
                if entity_id:
                    await hass.services.async_call(
                        "text",
                        "set_value",
                        {"entity_id": entity_id, "value": value},
                        blocking=True,
                    )

            return {
                "device_key": device_key,
                "album_ids": album_ids,
                "index": idx,
                "count": len(photos),
                "direction": direction,
                "prefetch_each_side": prefetch_each_side,
                "image_format": image_format,
                "current": {
                    "fileid": current.get("fileid"),
                    "etag": current.get("etag"),
                    "url": current_url,
                },
                "prev": {
                    "fileid": prev_photo.get("fileid"),
                    "etag": prev_photo.get("etag"),
                    "url": prev_url,
                },
                "next": {
                    "fileid": next_photo.get("fileid"),
                    "etag": next_photo.get("etag"),
                    "url": next_url,
                },
                "prev_urls": prev_urls,
                "next_urls": next_urls,
            }

    async def async_handle_frame_device_set(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        device_key = _sanitize_device_key(str(call.data["device_key"]))
        esp_device_id = _sanitize_esp_device_id(str(call.data.get("esp_device_id", "")).strip() or None)
        if esp_device_id:
            for key, profile in entry.runtime_data.frame_devices.items():
                if key == device_key:
                    continue
                if str(profile.get("esp_device_id", "")).strip() == esp_device_id:
                    raise ServiceValidationError(
                        f"esp_device_id '{esp_device_id}' already assigned to device_key '{key}'"
                    )
        album_ids = _normalize_album_ids(call.data.get("album_ids"))
        if not album_ids:
            raise ServiceValidationError("album_ids must contain at least one album")

        profile = {
            "device_key": device_key,
            "esp_device_id": esp_device_id,
            "name": str(call.data.get("name") or device_key),
            "album_ids": album_ids,
            "width": int(call.data.get("width", DEFAULT_WIDTH)),
            "height": int(call.data.get("height", DEFAULT_HEIGHT)),
            "image_format": _normalize_image_format(
                call.data.get("image_format", DEFAULT_IMAGE_FORMAT)
            ),
            "randomize": bool(call.data.get("randomize", True)),
            "max_photos": int(call.data.get("max_photos", 500)),
            "max_cache_files": int(call.data.get("max_cache_files", 40)),
            "prefetch_each_side": int(call.data.get("prefetch_each_side", 5)),
            "rotation_minutes": int(call.data.get("rotation_minutes", DEFAULT_ROTATION_MINUTES)),
            "presence_entity_id": str(call.data.get("presence_entity_id") or "").strip() or None,
            "target_current_text_entity": call.data.get("target_current_text_entity"),
            "target_prev_text_entity": call.data.get("target_prev_text_entity"),
            "target_next_text_entity": call.data.get("target_next_text_entity"),
        }

        entry.runtime_data.frame_devices[device_key] = profile
        await _save_frame_devices(entry)

        _sync_rotation_tasks(hass, entry)
        _sync_presence_listeners(hass, entry)
        await _sync_frame_devices_registry(hass, entry)
        return {"device": profile}

    async def async_handle_frame_device_delete(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        device_key = _sanitize_device_key(str(call.data["device_key"]))
        deleted = entry.runtime_data.frame_devices.pop(device_key, None) is not None
        entry.runtime_data.frame_states.pop(device_key, None)
        entry.runtime_data.frame_locks.pop(device_key, None)
        task = entry.runtime_data.frame_rotation_tasks.pop(device_key, None)
        if task and not task.done():
            task.cancel()
        if deleted:
            await _save_frame_devices(entry)
            _sync_presence_listeners(hass, entry)
            await _sync_frame_devices_registry(hass, entry)
        return {"device_key": device_key, "deleted": deleted}

    async def async_handle_frame_device_list(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        devices = [
            dict(v) for _, v in sorted(entry.runtime_data.frame_devices.items(), key=lambda x: x[0])
        ]
        return {"count": len(devices), "devices": devices}

    async def async_handle_frame_reset(call: ServiceCall) -> dict[str, Any]:
        entry = _resolve_entry(hass, call)
        device_key = _sanitize_device_key(str(call.data["device_key"]))
        entry.runtime_data.frame_states.pop(device_key, None)
        entry.runtime_data.frame_locks.pop(device_key, None)
        return {"device_key": device_key, "reset": True}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ALBUMS,
        async_handle_get_albums,
        schema=SERVICE_GET_ALBUMS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PHOTO_LIST,
        async_handle_get_photo_list,
        schema=SERVICE_GET_PHOTO_LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PHOTO,
        async_handle_get_photo,
        schema=SERVICE_GET_PHOTO_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FRAME_REFRESH,
        async_handle_frame_refresh,
        schema=SERVICE_FRAME_REFRESH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FRAME_RESET,
        async_handle_frame_reset,
        schema=SERVICE_FRAME_RESET_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FRAME_DEVICE_SET,
        async_handle_frame_device_set,
        schema=SERVICE_FRAME_DEVICE_SET_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FRAME_DEVICE_DELETE,
        async_handle_frame_device_delete,
        schema=SERVICE_FRAME_DEVICE_DELETE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FRAME_DEVICE_LIST,
        async_handle_frame_device_list,
        schema=SERVICE_FRAME_DEVICE_LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> MemoriesConfigEntry:
    entry_id = call.data.get(CONF_ENTRY_ID)
    entries: dict[str, MemoriesConfigEntry] = hass.data.get(DOMAIN, {})

    if not entries:
        raise ServiceValidationError("No Nextcloud Memories config entries loaded")

    if entry_id:
        if entry_id not in entries:
            raise ServiceValidationError(f"Unknown entry_id: {entry_id}")
        return entries[entry_id]

    if len(entries) > 1:
        raise ServiceValidationError(
            "Multiple config entries found. Pass entry_id in service data."
        )

    return next(iter(entries.values()))


def _frame_signal(entry_id: str, device_key: str) -> str:
    return f"{SIGNAL_FRAME_STATE_PREFIX}_{entry_id}_{device_key}"


async def _migrate_frame_sensor_entity_ids(
    hass: HomeAssistant, entry: MemoriesConfigEntry
) -> None:
    """Force canonical entity_id: sensor.nextcloud_memories_<slug>_photos."""
    ent_reg = er.async_get(hass)
    entries = list(er.async_entries_for_config_entry(ent_reg, entry.entry_id))

    for device_key, profile in entry.runtime_data.frame_devices.items():
        base = _slugify_entity(str(profile.get("esp_device_id") or device_key))
        unique_id = f"{entry.entry_id}_{base}_photos"
        expected = f"sensor.nextcloud_memories_{base}_photos"
        target = next(
            (e for e in entries if e.domain == "sensor" and e.unique_id == unique_id),
            None,
        )
        if target is None or target.entity_id == expected:
            continue
        if ent_reg.async_is_registered(expected):
            _LOGGER.debug(
                "Skipping entity_id migration for %s because %s already exists",
                unique_id,
                expected,
            )
            continue
        try:
            ent_reg.async_update_entity(target.entity_id, new_entity_id=expected)
        except Exception as exc:  # pragma: no cover - registry edge cases
            _LOGGER.debug("Entity id migration failed for %s: %s", target.entity_id, exc)


def _resolve_device_key_from_esp(entry: MemoriesConfigEntry, esp_device_id: str) -> str:
    target = _sanitize_esp_device_id(esp_device_id)
    if not target:
        raise ServiceValidationError("Invalid esp_device_id")
    for device_key, profile in entry.runtime_data.frame_devices.items():
        if str(profile.get("esp_device_id", "")).strip() == target:
            return device_key
    raise ServiceValidationError(f"No frame device mapped to esp_device_id '{target}'")


def _bootstrap_frame_states(hass: HomeAssistant, entry: MemoriesConfigEntry) -> None:
    """Populate frame state at startup so sensors are not empty."""
    for device_key in list(entry.runtime_data.frame_devices.keys()):
        hass.async_create_task(_bootstrap_one_frame_state(hass, entry, device_key))


async def _bootstrap_one_frame_state(
    hass: HomeAssistant, entry: MemoriesConfigEntry, device_key: str
) -> None:
    try:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_FRAME_REFRESH,
            {
                CONF_ENTRY_ID: entry.entry_id,
                "device_key": device_key,
                "direction": "stay",
                "force_reload": True,
            },
            blocking=True,
            return_response=True,
        )
    except Exception as exc:  # pragma: no cover - startup best effort
        _LOGGER.debug("bootstrap frame state failed for %s: %s", device_key, exc)


async def _sync_frame_devices_registry(
    hass: HomeAssistant, entry: MemoriesConfigEntry
) -> None:
    """Create/update/remove HA device registry entries for logical frame devices."""
    device_reg = dr.async_get(hass)
    profiles = entry.runtime_data.frame_devices

    # Upsert current profiles
    for device_key, profile in profiles.items():
        esp_device_id = str(profile.get("esp_device_id", "")).strip() or None
        esp_mac = resolve_esp_device_mac(hass, esp_device_id)
        kwargs: dict[str, Any] = {
            "config_entry_id": entry.entry_id,
            "identifiers": {(DOMAIN, device_key)},
            "manufacturer": "Nextcloud Memories",
            "model": "Photo Frame Backend",
            "name": str(profile.get("name") or device_key),
        }
        if esp_mac:
            kwargs["connections"] = {(dr.CONNECTION_NETWORK_MAC, esp_mac)}
        device_reg.async_get_or_create(
            **kwargs
        )

    # Remove stale registry devices for this config entry
    for dev in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        is_ours = any(ident[0] == DOMAIN for ident in dev.identifiers)
        if not is_ours:
            continue
        device_keys = [ident[1] for ident in dev.identifiers if ident[0] == DOMAIN]
        if any(key in profiles for key in device_keys):
            continue
        device_reg.async_remove_device(dev.id)


def _sanitize_device_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9._-]", "_", value.strip())
    if not key:
        raise ServiceValidationError("Invalid device_key")
    return key


def _sanitize_esp_device_id(value: str | None) -> str | None:
    if value is None:
        return None
    out = re.sub(r"[^a-zA-Z0-9._-]", "_", value.strip())
    return out or None


def _slugify_entity(value: str) -> str:
    out = "".join(
        c if (c.isalnum() or c == "_") else "_"
        for c in value.lower().replace("-", "_")
    )
    return out.strip("_") or "frame"


async def async_set_rotation_minutes(
    hass: HomeAssistant,
    entry: MemoriesConfigEntry,
    device_key: str,
    minutes: int,
) -> None:
    """Persist rotation period for one frame device and restart scheduler."""
    profile = entry.runtime_data.frame_devices.get(device_key)
    if not isinstance(profile, dict):
        raise ServiceValidationError(f"Unknown device_key '{device_key}'")
    val = max(1, min(30, int(minutes)))
    profile["rotation_minutes"] = val
    await _save_frame_devices(entry)
    _restart_rotation_task(hass, entry, device_key)
    async_dispatcher_send(hass, _frame_signal(entry.entry_id, device_key))


def _rotation_minutes(profile: dict[str, Any]) -> int:
    try:
        value = int(profile.get("rotation_minutes", DEFAULT_ROTATION_MINUTES))
    except (TypeError, ValueError):
        value = DEFAULT_ROTATION_MINUTES
    return max(1, min(30, value))


def _sync_rotation_tasks(hass: HomeAssistant, entry: MemoriesConfigEntry) -> None:
    runtime = entry.runtime_data
    wanted = set(runtime.frame_devices.keys())
    existing = set(runtime.frame_rotation_tasks.keys())
    for device_key in existing - wanted:
        task = runtime.frame_rotation_tasks.pop(device_key, None)
        if task and not task.done():
            task.cancel()
    for device_key in wanted:
        _restart_rotation_task(hass, entry, device_key)


def _sync_presence_listeners(hass: HomeAssistant, entry: MemoriesConfigEntry) -> None:
    """Link optional presence entities to the ESPHome LCD backlight."""
    runtime = entry.runtime_data
    for unsub in runtime.presence_unsubs:
        unsub()
    runtime.presence_unsubs.clear()

    for device_key, profile in runtime.frame_devices.items():
        presence_entity_id = str(profile.get("presence_entity_id") or "").strip()
        if not presence_entity_id:
            continue

        @callback
        def _presence_changed(event: Any, key: str = device_key) -> None:
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            hass.async_create_task(
                _async_apply_presence_backlight(hass, entry, key, new_state.state)
            )

        runtime.presence_unsubs.append(
            async_track_state_change_event(hass, [presence_entity_id], _presence_changed)
        )

        current = hass.states.get(presence_entity_id)
        if current is not None:
            hass.async_create_task(
                _async_apply_presence_backlight(hass, entry, device_key, current.state)
            )


async def _async_apply_presence_backlight(
    hass: HomeAssistant,
    entry: MemoriesConfigEntry,
    device_key: str,
    presence_state: str,
) -> None:
    """Apply an on/off presence state to the linked ESPHome backlight."""
    if presence_state not in (STATE_ON, STATE_OFF):
        return
    profile = entry.runtime_data.frame_devices.get(device_key, {})
    backlight_entity_id = _resolve_esp_backlight_entity(
        hass, str(profile.get("esp_device_id") or "").strip() or None
    )
    if not backlight_entity_id:
        _LOGGER.warning("No ESPHome backlight switch found for frame %s", device_key)
        return
    service = "turn_on" if presence_state == STATE_ON else "turn_off"
    try:
        await hass.services.async_call(
            "switch", service, {"entity_id": backlight_entity_id}, blocking=True
        )
    except Exception as exc:  # pragma: no cover - runtime safety
        _LOGGER.warning(
            "Unable to set backlight %s from presence %s: %s",
            backlight_entity_id,
            profile.get("presence_entity_id"),
            exc,
        )


def _resolve_esp_backlight_entity(
    hass: HomeAssistant, esp_device_id: str | None
) -> str | None:
    """Resolve the backlight switch belonging to the linked ESPHome device."""
    esp_mac = resolve_esp_device_mac(hass, esp_device_id)
    if not esp_mac:
        return None

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    candidates: list[str] = []
    for device in device_reg.devices.values():
        connections = {
            str(value).lower()
            for conn_type, value in device.connections
            if conn_type == dr.CONNECTION_NETWORK_MAC
        }
        if esp_mac.lower() not in connections:
            continue
        is_esphome = any(
            (
                (cfg := hass.config_entries.async_get_entry(entry_id)) is not None
                and cfg.domain == "esphome"
            )
            for entry_id in device.config_entries
        )
        if not is_esphome:
            continue
        for entity in er.async_entries_for_device(entity_reg, device.id):
            if entity.domain != "switch" or entity.platform != "esphome":
                continue
            label = " ".join(
                filter(None, (entity.original_name, entity.name, entity.entity_id))
            ).lower()
            if "backlight" in label:
                candidates.append(entity.entity_id)

    if not candidates:
        return None
    candidates.sort(key=lambda entity_id: ("lcd" not in entity_id.lower(), entity_id))
    return candidates[0]


def _restart_rotation_task(hass: HomeAssistant, entry: MemoriesConfigEntry, device_key: str) -> None:
    runtime = entry.runtime_data
    old = runtime.frame_rotation_tasks.pop(device_key, None)
    if old and not old.done():
        old.cancel()
    runtime.frame_rotation_tasks[device_key] = hass.async_create_background_task(
        _rotation_loop(hass, entry, device_key),
        f"{DOMAIN}_rotation_{device_key}",
    )


async def _rotation_loop(hass: HomeAssistant, entry: MemoriesConfigEntry, device_key: str) -> None:
    try:
        while True:
            profile = entry.runtime_data.frame_devices.get(device_key)
            if not isinstance(profile, dict):
                return
            wait_seconds = _rotation_minutes(profile) * 60
            await asyncio.sleep(wait_seconds)
            # Advance one photo; state-driven sensor update will propagate to ESP.
            await hass.services.async_call(
                DOMAIN,
                SERVICE_FRAME_REFRESH,
                {
                    CONF_ENTRY_ID: entry.entry_id,
                    "device_key": device_key,
                    "direction": "next",
                },
                blocking=True,
                return_response=True,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - runtime safety
        _LOGGER.debug("rotation loop failed for %s: %s", device_key, exc)


def resolve_esp_device_mac(hass: HomeAssistant, esp_device_id: str | None) -> str | None:
    """Resolve MAC address for the ESPHome device linked by `esp_device_id`."""
    target = _sanitize_esp_device_id(esp_device_id)
    if not target:
        return None

    def _canon(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    target_norm_dash = target.lower().replace("_", "-").strip()
    target_norm_us = target.lower().replace("-", "_").strip()
    target_canon = _canon(target)

    device_reg = dr.async_get(hass)
    for device in device_reg.devices.values():
        names: list[str] = []
        if device.name:
            names.append(device.name)
        if device.name_by_user:
            names.append(device.name_by_user)

        name_match = any(
            (
                n.lower().replace("_", "-").strip() == target_norm_dash
                or n.lower().replace("-", "_").strip() == target_norm_us
                or _canon(n) == target_canon
            )
            for n in names
        )

        identifier_values = {
            str(ident[1]).lower() for ident in (device.identifiers or set()) if len(ident) > 1
        }
        id_match = (
            target.lower() in identifier_values
            or target_norm_dash in identifier_values
            or target_norm_us in identifier_values
        )
        if not (name_match or id_match):
            continue

        # Prefer devices that truly belong to ESPHome integration.
        is_esphome = any(
            (
                (cfg := hass.config_entries.async_get_entry(entry_id)) is not None
                and cfg.domain == "esphome"
            )
            for entry_id in device.config_entries
        )
        if not (is_esphome or name_match):
            continue

        for conn_type, conn_value in device.connections:
            if conn_type == dr.CONNECTION_NETWORK_MAC and conn_value:
                return str(conn_value).lower()

    return None


def _normalize_album_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for v in value:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


async def _save_frame_devices(entry: MemoriesConfigEntry) -> None:
    if entry.runtime_data.frame_store is None:
        return
    await entry.runtime_data.frame_store.async_save(
        {"devices": entry.runtime_data.frame_devices}
    )


async def _clear_device_cache_dirs(hass: HomeAssistant, device_keys: list[str]) -> None:
    """Delete stale cached files for managed devices at startup/reload."""
    if not device_keys:
        return

    def _cleanup() -> None:
        root = Path(hass.config.path("www", CACHE_DIR_NAME))
        for device_key in device_keys:
            device_dir = root / device_key
            if not device_dir.exists() or not device_dir.is_dir():
                continue
            for p in device_dir.iterdir():
                if not p.is_file() or p.suffix.lower() not in {".jpg", ".bmp"}:
                    continue
                try:
                    p.unlink()
                except OSError:
                    pass

    await hass.async_add_executor_job(_cleanup)


def _window_indexes(idx: int, count: int, prefetch_each_side: int) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for offset in range(-prefetch_each_side, prefetch_each_side + 1):
        widx = (idx + offset) % count
        if widx in seen:
            continue
        seen.add(widx)
        out.append(widx)
    return out


def _image_extension(image_format: str) -> str:
    fmt = _normalize_image_format(image_format)
    return ".jpg" if fmt == "jpeg" else ".bmp"


def _normalize_image_format(value: Any) -> str:
    fmt = str(value or DEFAULT_IMAGE_FORMAT).strip().lower()
    if fmt == "bmp16":
        # ESPHome online_image BMP decoder currently does not support 16 bpp BMP.
        # Keep the option in UI but render/store as BMP24 to remain compatible.
        return "bmp24"
    if fmt in IMAGE_FORMATS:
        return fmt
    return DEFAULT_IMAGE_FORMAT


def _cached_filename(
    photo: dict[str, Any], width: int, height: int, image_format: str
) -> str:
    fileid = int(photo["fileid"])
    etag = str(photo.get("etag") or "noetag")
    safe_etag = re.sub(r"[^a-zA-Z0-9_-]", "", etag)[:16] or "noetag"
    return f"{fileid}_{safe_etag}_{width}x{height}{_image_extension(image_format)}"


def _photo_local_url(
    device_key: str, photo: dict[str, Any], width: int, height: int, image_format: str
) -> str:
    return f"/local/{CACHE_DIR_NAME}/{device_key}/{_cached_filename(photo, width, height, image_format)}"


def _window_urls(
    device_key: str,
    photos: list[dict[str, Any]],
    idx: int,
    width: int,
    height: int,
    image_format: str,
    prefetch_each_side: int,
) -> tuple[list[str], list[str]]:
    prev_urls: list[str] = []
    next_urls: list[str] = []
    for step in range(1, prefetch_each_side + 1):
        prev_urls.append(
            _photo_local_url(
                device_key, photos[(idx - step) % len(photos)], width, height, image_format
            )
        )
        next_urls.append(
            _photo_local_url(
                device_key, photos[(idx + step) % len(photos)], width, height, image_format
            )
        )
    return prev_urls, next_urls


def _schedule_prefetch_window(
    hass: HomeAssistant,
    entry: MemoriesConfigEntry,
    device_key: str,
    album_ids: list[str],
    photos: list[dict[str, Any]],
    idx: int,
    width: int,
    height: int,
    image_format: str,
    prefetch_each_side: int,
    max_cache_files: int,
) -> None:
    existing = entry.runtime_data.frame_prefetch_tasks.get(device_key)
    if existing and not existing.done():
        existing.cancel()

    async def _runner() -> None:
        try:
            device_dir = Path(hass.config.path("www", CACHE_DIR_NAME, device_key))
            await hass.async_add_executor_job(
                partial(device_dir.mkdir, parents=True, exist_ok=True)
            )
            keep_paths: set[Path] = set()
            for widx in _window_indexes(idx, len(photos), prefetch_each_side):
                wphoto = photos[widx]
                _, wpath = await _cache_device_photo(
                    hass=hass,
                    entry=entry,
                    device_key=device_key,
                    album_id=str(wphoto.get("_album_id") or album_ids[0]),
                    photo=wphoto,
                    width=width,
                    height=height,
                    image_format=image_format,
                    device_dir=device_dir,
                )
                keep_paths.add(wpath)

            await _cleanup_device_cache(
                hass=hass,
                device_dir=device_dir,
                keep_paths=keep_paths,
                max_cache_files=max_cache_files,
            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - runtime safety
            _LOGGER.debug("frame prefetch failed for %s: %s", device_key, exc)

    entry.runtime_data.frame_prefetch_tasks[device_key] = hass.async_create_task(_runner())


async def _cache_device_photo(
    hass: HomeAssistant,
    entry: MemoriesConfigEntry,
    device_key: str,
    album_id: str,
    photo: dict[str, Any],
    width: int,
    height: int,
    image_format: str,
    device_dir: Path,
) -> tuple[str, Path]:
    filename = _cached_filename(photo, width, height, image_format)
    output_path = device_dir / filename

    if not output_path.exists():
        fileid = int(photo["fileid"])
        etag = str(photo.get("etag") or "noetag")
        image_bytes = await entry.runtime_data.client.async_get_photo_preview(
            fileid=fileid,
            width=width,
            height=height,
            album_id=album_id,
            etag=etag if etag != "noetag" else None,
        )
        await hass.async_add_executor_job(
            partial(
                _write_processed_image_file,
                output_path,
                image_bytes,
                width,
                height,
                image_format,
            )
        )

    local_url = f"/local/{CACHE_DIR_NAME}/{device_key}/{filename}"
    return local_url, output_path


async def _cleanup_device_cache(
    hass: HomeAssistant,
    device_dir: Path,
    keep_paths: set[Path],
    max_cache_files: int,
) -> None:
    def _cleanup() -> None:
        files = [p for p in device_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".bmp"}]
        if len(files) <= max_cache_files:
            return
        keep_str = {str(p) for p in keep_paths}
        candidates = [p for p in files if str(p) not in keep_str]
        candidates.sort(key=lambda p: p.stat().st_mtime)
        to_delete = max(0, len(files) - max_cache_files)
        for p in candidates[:to_delete]:
            try:
                p.unlink()
            except OSError:
                pass

    await hass.async_add_executor_job(_cleanup)


def _write_bmp16_file(output_path: Path, img: Any) -> None:
    """Write RGB image as BMP 16-bit RGB565."""
    import struct

    rgb = img.convert("RGB")
    width, height = rgb.size
    data = rgb.tobytes()
    row_raw = width * 2
    row_stride = (row_raw + 3) & ~3
    image_size = row_stride * height
    offset = 14 + 40 + 12
    file_size = offset + image_size

    header = bytearray()
    header += b"BM"
    header += struct.pack("<IHHI", file_size, 0, 0, offset)
    header += struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height,
        1,
        16,
        3,  # BI_BITFIELDS
        image_size,
        0,
        0,
        0,
        0,
    )
    header += struct.pack("<III", 0xF800, 0x07E0, 0x001F)

    out = bytearray(image_size)
    for y in range(height):
        src_y = height - 1 - y  # BMP bottom-up
        src_row = src_y * width * 3
        dst_row = y * row_stride
        for x in range(width):
            i = src_row + x * 3
            r = data[i]
            g = data[i + 1]
            b = data[i + 2]
            px = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[dst_row + x * 2] = px & 0xFF
            out[dst_row + x * 2 + 1] = (px >> 8) & 0xFF

    output_path.write_bytes(bytes(header) + bytes(out))


def _write_processed_image_file(
    output_path: Path,
    image_bytes: bytes,
    width: int,
    height: int,
    image_format: str,
) -> None:
    """Write image for ESPHome using selected format."""
    if Image is None:
        output_path.write_bytes(image_bytes)
        return
    fmt = _normalize_image_format(image_format)
    try:
        with Image.open(io.BytesIO(image_bytes)) as src:
            img = ImageOps.exif_transpose(src)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Horizontal: fill full width; crop vertical center if needed.
            if img.width >= img.height:
                target_w = width
                target_h = max(1, round(img.height * target_w / img.width))
                fg = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                if fg.height > height:
                    top = (fg.height - height) // 2
                    img = fg.crop((0, top, width, top + height))
                elif fg.height < height:
                    canvas = Image.new("RGB", (width, height), (0, 0, 0))
                    oy = (height - fg.height) // 2
                    canvas.paste(fg, (0, oy))
                    img = canvas
                else:
                    img = fg
            # Vertical: blurred background + foreground at least 400 px wide.
            else:
                bg = ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=18))

                # First fit the full image height. If that would make the
                # foreground narrower than 400 px, zoom to 400 px and crop
                # only the excess height, centred vertically.
                full_height_w = max(1, round(img.width * height / img.height))
                fg_w = min(width, max(400, full_height_w))
                fg_h = max(1, round(img.height * fg_w / img.width))
                fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
                if fg.height > height:
                    top = (fg.height - height) // 2
                    fg = fg.crop((0, top, fg.width, top + height))

                ox = (width - fg.width) // 2
                oy = (height - fg.height) // 2
                bg.paste(fg, (ox, oy))
                img = bg

            if fmt == "jpeg":
                out = io.BytesIO()
                img.save(out, format="JPEG", progressive=False, quality=75, optimize=True)
                output_path.write_bytes(out.getvalue())
            elif fmt == "bmp24":
                out = io.BytesIO()
                img.convert("RGB").save(out, format="BMP")
                output_path.write_bytes(out.getvalue())
            else:  # bmp16
                _write_bmp16_file(output_path, img)
    except Exception as exc:  # pragma: no cover - runtime safety
        _LOGGER.debug("image conversion failed (%s), writing original bytes: %s", fmt, exc)
        output_path.write_bytes(image_bytes)


def _build_output_name(
    entry_id: str,
    album_id: str,
    fileid: int,
    width: int,
    height: int,
    image_format: str,
    filename: str | None,
) -> str:
    ext = _image_extension(image_format)
    if filename:
        clean = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.strip())
        if not clean:
            clean = "photo"
        if not clean.lower().endswith(ext):
            clean = f"{clean}{ext}"
        return clean

    safe_entry_id = re.sub(r"[^a-zA-Z0-9_-]", "_", entry_id)
    safe_album = re.sub(r"[^a-zA-Z0-9_-]", "_", album_id or "album")
    return f"{safe_entry_id}_{safe_album}_{fileid}_{width}x{height}{ext}"
