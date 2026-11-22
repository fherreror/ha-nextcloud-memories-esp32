"""Buttons for Nextcloud Memories frame devices."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RuntimeEntry, resolve_esp_device_mac
from .const import DOMAIN, SERVICE_FRAME_REFRESH


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up frame buttons for one config entry."""
    runtime: RuntimeEntry = entry.runtime_data
    entities: list[ButtonEntity] = []
    for device_key in sorted(runtime.frame_devices.keys()):
        entities.extend(
            [
                FrameActionButton(hass, entry, device_key, "next", "Next Photo", "mdi:skip-next"),
                FrameActionButton(hass, entry, device_key, "prev", "Previous Photo", "mdi:skip-previous"),
                FrameActionButton(hass, entry, device_key, "shuffle", "Regenerate Random", "mdi:shuffle-variant"),
            ]
        )
    async_add_entities(entities)


class FrameActionButton(ButtonEntity):
    """Button that triggers frame refresh actions."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_key: str,
        action: str,
        name: str,
        icon: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._device_key = device_key
        self._action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{device_key}_btn_{action}"
        self._esp_mac: str | None = None

    @property
    def _runtime(self) -> RuntimeEntry:
        return self._entry.runtime_data

    @property
    def _profile_name(self) -> str:
        profile = self._runtime.frame_devices.get(self._device_key, {})
        return str(profile.get("name") or self._device_key)

    @property
    def _profile_esp_device_id(self) -> str | None:
        profile = self._runtime.frame_devices.get(self._device_key, {})
        value = str(profile.get("esp_device_id", "")).strip()
        return value or None

    @property
    def device_info(self) -> DeviceInfo:
        if self._esp_mac is None:
            self._esp_mac = resolve_esp_device_mac(self.hass, self._profile_esp_device_id)

        info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, self._device_key)},
            name=self._profile_name,
            manufacturer="Nextcloud Memories",
            model="Photo Frame Backend",
        )
        if self._esp_mac:
            info["connections"] = {(dr.CONNECTION_NETWORK_MAC, self._esp_mac)}
        return info

    async def async_press(self) -> None:
        data = {
            "entry_id": self._entry.entry_id,
            "device_key": self._device_key,
        }
        if self._action == "next":
            data["direction"] = "next"
        elif self._action == "prev":
            data["direction"] = "prev"
        else:
            data["direction"] = "stay"
            data["force_reload"] = True
            data["randomize"] = True

        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_FRAME_REFRESH,
            data,
            blocking=True,
            return_response=True,
        )
