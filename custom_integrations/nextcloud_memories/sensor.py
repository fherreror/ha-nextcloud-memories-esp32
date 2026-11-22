"""Sensors for Nextcloud Memories frame devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RuntimeEntry, _frame_signal, resolve_esp_device_mac
from .const import CONF_IMAGE_BASE_URL, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up frame sensors for one config entry."""
    runtime: RuntimeEntry = entry.runtime_data
    entities: list[SensorEntity] = []
    for device_key in sorted(runtime.frame_devices.keys()):
        profile = runtime.frame_devices.get(device_key, {})
        esp_device_id = str(profile.get("esp_device_id", "")).strip() or None
        entities.append(FrameStatusSensor(hass, entry, device_key, esp_device_id))
    async_add_entities(entities)


class FrameBaseSensor(SensorEntity):
    """Base class for frame sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_key: str,
        esp_device_id: str | None = None,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_key = device_key
        self._esp_device_id = esp_device_id
        self._esp_mac = resolve_esp_device_mac(hass, esp_device_id)

    @property
    def _runtime(self) -> RuntimeEntry:
        return self._entry.runtime_data

    @property
    def _profile(self) -> dict[str, Any]:
        return self._runtime.frame_devices.get(self._device_key, {})

    @property
    def _state_data(self) -> dict[str, Any]:
        return self._runtime.frame_states.get(self._device_key, {})

    @property
    def device_info(self) -> DeviceInfo:
        info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, self._device_key)},
            name=str(self._profile.get("name") or self._device_key),
            manufacturer="Nextcloud Memories",
            model="Photo Frame Backend",
        )
        if self._esp_mac:
            info["connections"] = {(dr.CONNECTION_NETWORK_MAC, self._esp_mac)}
        return info

    async def async_added_to_hass(self) -> None:
        """Subscribe to frame state updates for this device."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                _frame_signal(self._entry.entry_id, self._device_key),
                self._handle_refresh,
            )
        )

    @callback
    def _handle_refresh(self) -> None:
        self.async_write_ha_state()


class FrameStatusSensor(FrameBaseSensor):
    """Sensor exposing frame queue and profile state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_key: str,
        esp_device_id: str | None,
    ) -> None:
        super().__init__(hass, entry, device_key, esp_device_id)
        base = _slugify(esp_device_id or device_key)
        self._attr_unique_id = f"{entry.entry_id}_{base}_photos"
        self._attr_name = f"{(esp_device_id or device_key).replace('_', ' ')} Photos"
        self._attr_icon = "mdi:image-multiple"
        self._attr_object_id = f"nextcloud_memories_{base}_photos"

    @property
    def native_value(self) -> str:
        state = self._state_data or {}
        current = state.get("photos", []) if isinstance(state, dict) else []
        if not current:
            return "idle"
        idx = _safe_int(state.get("index"), 0)
        photos: list[dict[str, Any]] = state["photos"]
        photo = photos[idx % len(photos)]
        return str(photo.get("fileid", "unknown"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profile = self._profile or {}
        state = self._state_data or {}
        photos: list[dict[str, Any]] = state.get("photos", []) if isinstance(state, dict) else []
        idx = _safe_int(state.get("index"), 0) if photos else 0
        current = photos[idx % len(photos)] if photos else {}
        prev_photo = photos[(idx - 1) % len(photos)] if photos else {}
        next_photo = photos[(idx + 1) % len(photos)] if photos else {}

        current_url = None
        prev_url = None
        next_url = None
        prev_urls: list[str] = []
        next_urls: list[str] = []
        if photos:
            width = _safe_int(profile.get("width"), 800)
            height = _safe_int(profile.get("height"), 480)
            image_format = str(profile.get("image_format", "jpeg"))
            prefetch = _safe_int(profile.get("prefetch_each_side"), 5)
            image_base_url = str(
                self._entry.data.get(CONF_IMAGE_BASE_URL, "http://homeassistant.local:8123")
            ).rstrip("/")
            current_url = _photo_url(
                self._device_key, current, width, height, image_format, image_base_url
            )
            prev_url = _photo_url(
                self._device_key, prev_photo, width, height, image_format, image_base_url
            )
            next_url = _photo_url(
                self._device_key, next_photo, width, height, image_format, image_base_url
            )
            for step in range(1, prefetch + 1):
                p = photos[(idx - step) % len(photos)]
                n = photos[(idx + step) % len(photos)]
                prev_urls.append(
                    _photo_url(self._device_key, p, width, height, image_format, image_base_url)
                )
                next_urls.append(
                    _photo_url(self._device_key, n, width, height, image_format, image_base_url)
                )

        return {
            "device_key": self._device_key,
            "esp_device_id": self._esp_device_id,
            "name": profile.get("name"),
            "album_ids": profile.get("album_ids", []),
            "width": profile.get("width"),
            "height": profile.get("height"),
            "image_format": profile.get("image_format", "jpeg"),
            "randomize": profile.get("randomize"),
            "max_photos": profile.get("max_photos"),
            "max_cache_files": profile.get("max_cache_files"),
            "prefetch_each_side": profile.get("prefetch_each_side"),
            "rotation_minutes": profile.get("rotation_minutes"),
            "presence_entity_id": profile.get("presence_entity_id"),
            "count": len(photos),
            "index": idx,
            "album_errors": state.get("album_errors", []),
            "current_fileid": current.get("fileid"),
            "prev_fileid": prev_photo.get("fileid"),
            "next_fileid": next_photo.get("fileid"),
            "current_url": current_url,
            "prev_url": prev_url,
            "next_url": next_url,
            "prev_urls": prev_urls,
            "next_urls": next_urls,
        }


def _photo_url(
    device_key: str,
    photo: dict[str, Any],
    width: int,
    height: int,
    image_format: str,
    image_base_url: str,
) -> str | None:
    fileid = photo.get("fileid")
    if fileid is None:
        return None
    etag = str(photo.get("etag") or "noetag")
    safe_etag = "".join(c for c in etag if c.isalnum() or c in "_-")[:16] or "noetag"
    fmt = str(image_format or "jpeg").lower()
    ext = ".jpg" if fmt == "jpeg" else ".bmp"
    filename = f"{int(fileid)}_{safe_etag}_{width}x{height}{ext}"
    return f"{image_base_url}/local/nextcloud_memories/{device_key}/{filename}"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify(value: str) -> str:
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in value.lower().replace("-", "_"))
    return out.strip("_") or "frame"
