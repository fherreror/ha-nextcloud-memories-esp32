"""Number entities for Nextcloud Memories integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RuntimeEntry, _frame_signal, async_set_rotation_minutes, resolve_esp_device_mac
from .const import DEFAULT_ROTATION_MINUTES, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up rotation slider entities per frame device."""
    runtime: RuntimeEntry = entry.runtime_data
    entities: list[NumberEntity] = []
    for device_key in sorted(runtime.frame_devices.keys()):
        entities.append(FrameRotationMinutesNumber(hass, entry, device_key))
    async_add_entities(entities)


class FrameRotationMinutesNumber(NumberEntity):
    """Rotation speed controller (minutes) for one frame device."""

    _attr_has_entity_name = True
    _attr_name = "Rotation Minutes"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"
    _attr_mode = "slider"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_key: str) -> None:
        self.hass = hass
        self._entry = entry
        self._device_key = device_key
        self._attr_unique_id = f"{entry.entry_id}_{device_key}_rotation_minutes"

        profile = self._runtime.frame_devices.get(device_key, {})
        esp_device_id = str(profile.get("esp_device_id", "")).strip() or None
        self._esp_mac = resolve_esp_device_mac(hass, esp_device_id)

    @property
    def _runtime(self) -> RuntimeEntry:
        return self._entry.runtime_data

    @property
    def _profile(self) -> dict:
        return self._runtime.frame_devices.get(self._device_key, {})

    @property
    def native_value(self) -> float:
        try:
            value = int(self._profile.get("rotation_minutes", DEFAULT_ROTATION_MINUTES))
        except (TypeError, ValueError):
            value = DEFAULT_ROTATION_MINUTES
        return float(max(1, min(30, value)))

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

    async def async_set_native_value(self, value: float) -> None:
        await async_set_rotation_minutes(
            self.hass,
            self._entry,
            self._device_key,
            int(round(value)),
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
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
