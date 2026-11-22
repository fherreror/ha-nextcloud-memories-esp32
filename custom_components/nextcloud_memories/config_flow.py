"""Config flow for Nextcloud Memories."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant import data_entry_flow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import NextcloudMemoriesClient
from .presence import normalize_condition_entities
from .const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    CONF_ENTRY_ID,
    CONF_IMAGE_BASE_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_ROTATION_MINUTES,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate authentication fails."""


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    session = async_get_clientsession(hass)
    client = NextcloudMemoriesClient(
        session=session,
        base_url=str(data[CONF_BASE_URL]).rstrip("/"),
        api_token=str(data[CONF_API_TOKEN]),
        username=str(data.get(CONF_USERNAME) or "").strip() or None,
        verify_ssl=bool(data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
    )

    try:
        await client.async_test_connection()
    except aiohttp.ClientResponseError as exc:
        if exc.status in (401, 403):
            raise InvalidAuth from exc
        raise CannotConnect from exc
    except RuntimeError as exc:
        raise CannotConnect from exc
    except aiohttp.ClientError as exc:
        raise CannotConnect from exc


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_BASE_URL] = str(user_input[CONF_BASE_URL]).rstrip("/")
            user_input[CONF_IMAGE_BASE_URL] = str(
                user_input.get(CONF_IMAGE_BASE_URL, _default_image_base_url(self.hass))
            ).rstrip("/")
            user_input[CONF_USERNAME] = str(user_input.get(CONF_USERNAME, "")).strip()
            user_input[CONF_API_TOKEN] = str(user_input.get(CONF_API_TOKEN, "")).replace(" ", "").strip()
            try:
                await _validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Nextcloud Memories config")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_BASE_URL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_BASE_URL],
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): str,
                vol.Optional(CONF_USERNAME, default="admin"): str,
                vol.Required(CONF_API_TOKEN): str,
                vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                vol.Optional(
                    CONF_IMAGE_BASE_URL,
                    default=_default_image_base_url(self.hass),
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return NextcloudMemoriesOptionsFlow(config_entry)


class NextcloudMemoriesOptionsFlow(config_entries.OptionsFlow):
    """Options flow to manage logical frame devices from UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._action: str | None = None
        self._source_device_key: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        devices = await self._async_load_devices()
        errors: dict[str, str] = {}

        if user_input is not None:
            image_base_url = str(
                user_input.get(
                    CONF_IMAGE_BASE_URL,
                    self._entry.data.get(CONF_IMAGE_BASE_URL, _default_image_base_url(self.hass)),
                )
            ).rstrip("/")
            if image_base_url != str(self._entry.data.get(CONF_IMAGE_BASE_URL, "")).rstrip("/"):
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={**self._entry.data, CONF_IMAGE_BASE_URL: image_base_url},
                )

            action = str(user_input.get("action", "")).strip() or "create"
            target = str(user_input.get("target_device_key", "")).strip()

            if action in ("edit", "delete") and target not in devices:
                errors["target_device_key"] = "required_target_device"
            elif action in ("edit", "delete") and not target:
                errors["target_device_key"] = "required_target_device"
            elif action == "delete":
                if target in devices:
                    devices.pop(target, None)
                    await self._async_save_devices(devices)
                    await self.hass.config_entries.async_reload(self._entry.entry_id)
                return self.async_create_entry(
                    title="",
                    data={CONF_ENTRY_ID: self._entry.entry_id, "devices_count": len(devices)},
                )
            elif action == "edit":
                self._action = action
                self._source_device_key = target
                return await self.async_step_device()
            else:
                self._action = "create"
                self._source_device_key = None
                return await self.async_step_device()

        return self.async_show_form(
            step_id="init",
            data_schema=self._step_init_schema(devices),
            errors=errors,
            description_placeholders={"devices": ", ".join(sorted(devices.keys())) or "-"},
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        devices = await self._async_load_devices()
        profile_defaults = self._profile_defaults(devices)
        album_options = await self._async_get_album_options()
        esp_device_options = self._get_esp_device_options(devices)
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                device_key = _sanitize_device_key(str(user_input.get("device_key", "")))
            except HomeAssistantError:
                errors["device_key"] = "invalid_device_key"
                return self.async_show_form(
                    step_id="device",
                    data_schema=self._device_schema(user_input, album_options, esp_device_options),
                    errors=errors,
                )

            album_ids = _normalize_album_ids(user_input.get("album_ids") or [])
            if not album_ids:
                errors["album_ids"] = "invalid_album_ids"
                return self.async_show_form(
                    step_id="device",
                    data_schema=self._device_schema(user_input, album_options, esp_device_options),
                    errors=errors,
                )

            presence_entity_id = str(user_input.get("presence_entity_id") or "").strip() or None
            presence_require_on = normalize_condition_entities(
                user_input.get("presence_require_on_entities"), presence_entity_id
            )
            presence_require_off = normalize_condition_entities(
                user_input.get("presence_require_off_entities"), presence_entity_id
            )
            if set(presence_require_on) & set(presence_require_off):
                errors["presence_require_off_entities"] = "conflicting_presence_conditions"
                return self.async_show_form(
                    step_id="device",
                    data_schema=self._device_schema(user_input, album_options, esp_device_options),
                    errors=errors,
                )

            profile = {
                "device_key": device_key,
                "esp_device_id": _sanitize_esp_device_id(str(user_input.get("esp_device_id", "")) or None),
                "name": str(user_input.get("name", "")).strip() or device_key,
                "album_ids": album_ids,
                "width": int(user_input.get("width", 800)),
                "height": int(user_input.get("height", 480)),
                "image_format": str(user_input.get("image_format", "jpeg")).strip().lower() or "jpeg",
                "randomize": bool(user_input.get("randomize", True)),
                "max_photos": int(user_input.get("max_photos", 500)),
                "max_cache_files": int(user_input.get("max_cache_files", 80)),
                "prefetch_each_side": int(user_input.get("prefetch_each_side", 5)),
                "rotation_minutes": int(user_input.get("rotation_minutes", DEFAULT_ROTATION_MINUTES)),
                "presence_entity_id": presence_entity_id,
                "presence_require_on_entities": presence_require_on,
                "presence_require_off_entities": presence_require_off,
            }

            if self._action == "edit" and self._source_device_key and self._source_device_key != device_key:
                devices.pop(self._source_device_key, None)

            esp_device_id = str(profile.get("esp_device_id") or "").strip()
            if esp_device_id:
                for key, existing in devices.items():
                    if key == device_key:
                        continue
                    if str(existing.get("esp_device_id", "")).strip() == esp_device_id:
                        errors["esp_device_id"] = "duplicate_esp_device_id"
                        return self.async_show_form(
                            step_id="device",
                            data_schema=self._device_schema(user_input, album_options, esp_device_options),
                            errors=errors,
                        )

            devices[device_key] = profile
            await self._async_save_devices(devices)
            await self.hass.config_entries.async_reload(self._entry.entry_id)
            return self.async_create_entry(
                title="",
                data={CONF_ENTRY_ID: self._entry.entry_id, "devices_count": len(devices)},
            )

        return self.async_show_form(
            step_id="device",
            data_schema=self._device_schema(profile_defaults, album_options, esp_device_options),
        )

    def _step_init_schema(self, devices: dict[str, Any]) -> vol.Schema:
        options = ["create"]
        if devices:
            options.extend(("edit", "delete"))

        target_selector: Any = str
        if devices:
            target_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        *[
                            {"value": key, "label": str(devices.get(key, {}).get("name") or key)}
                            for key in sorted(devices.keys())
                        ],
                    ],
                    multiple=False,
                    custom_value=False,
                )
            )

        return vol.Schema(
            {
                vol.Optional(
                    CONF_IMAGE_BASE_URL,
                    default=str(
                        self._entry.data.get(
                            CONF_IMAGE_BASE_URL, _default_image_base_url(self.hass)
                        )
                    ),
                ): str,
                vol.Required("action", default="create"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        custom_value=False,
                        translation_key="frame_action",
                    )
                ),
                data_entry_flow.Optional(
                    "target_device_key",
                    visible={"field": "action", "operator": "in", "value": ["edit", "delete"]},
                ): target_selector,
            }
        )

    def _device_schema(
        self,
        defaults: dict[str, Any],
        album_options: dict[str, str],
        esp_device_options: dict[str, str],
    ) -> vol.Schema:
        # Keep selector UX even if album fetch fails: include currently selected albums
        # as fallback options instead of degrading to a plain text field.
        for aid in defaults.get("album_ids", []) or []:
            a = str(aid).strip()
            if a and a not in album_options:
                album_options[a] = a

        album_ids_selector: Any = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": value, "label": label}
                    for value, label in sorted(album_options.items(), key=lambda kv: kv[1].lower())
                ],
                multiple=True,
                custom_value=True,
            )
        )
        album_default: Any = list(defaults.get("album_ids", []))

        default_esp = str(defaults.get("esp_device_id", "")).strip()
        if default_esp and default_esp not in esp_device_options:
            esp_device_options[default_esp] = default_esp
        esp_device_selector: Any = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": value, "label": label}
                    for value, label in sorted(
                        esp_device_options.items(), key=lambda kv: kv[1].lower()
                    )
                ],
                multiple=False,
                custom_value=True,
            )
        )

        return vol.Schema(
            {
                vol.Required("device_key", default=str(defaults.get("device_key", ""))): str,
                vol.Optional(
                    "esp_device_id", default=str(defaults.get("esp_device_id", ""))
                ): esp_device_selector,
                vol.Optional("name", default=str(defaults.get("name", ""))): str,
                vol.Optional("album_ids", default=album_default): album_ids_selector,
                vol.Optional("width", default=int(defaults.get("width", 800))): vol.All(
                    int, vol.Range(min=16, max=4096)
                ),
                vol.Optional("height", default=int(defaults.get("height", 480))): vol.All(
                    int, vol.Range(min=16, max=4096)
                ),
                vol.Optional("image_format", default=str(defaults.get("image_format", "jpeg"))): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            "jpeg",
                            "bmp24",
                        ],
                        multiple=False,
                        custom_value=False,
                        translation_key="frame_image_format",
                    )
                ),
                vol.Optional("randomize", default=bool(defaults.get("randomize", True))): bool,
                vol.Optional("max_photos", default=int(defaults.get("max_photos", 500))): vol.All(
                    int, vol.Range(min=1, max=5000)
                ),
                vol.Optional("max_cache_files", default=int(defaults.get("max_cache_files", 80))): vol.All(
                    int, vol.Range(min=5, max=500)
                ),
                vol.Optional("prefetch_each_side", default=int(defaults.get("prefetch_each_side", 5))): vol.All(
                    int, vol.Range(min=1, max=20)
                ),
                vol.Optional(
                    "rotation_minutes",
                    default=int(defaults.get("rotation_minutes", DEFAULT_ROTATION_MINUTES)),
                ): vol.All(int, vol.Range(min=1, max=30)),
                vol.Optional(
                    "presence_entity_id",
                    description={
                        "suggested_value": str(defaults.get("presence_entity_id") or "")
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "input_boolean"]
                    )
                ),
                data_entry_flow.Optional(
                    "presence_require_on_entities",
                    description={
                        "suggested_value": list(defaults.get("presence_require_on_entities") or [])
                    },
                    visible={"field": "presence_entity_id", "operator": "exists"},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "input_boolean", "switch"],
                        multiple=True,
                    )
                ),
                data_entry_flow.Optional(
                    "presence_require_off_entities",
                    description={
                        "suggested_value": list(defaults.get("presence_require_off_entities") or [])
                    },
                    visible={"field": "presence_entity_id", "operator": "exists"},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "input_boolean", "switch"],
                        multiple=True,
                    )
                ),
            }
        )

    async def _async_load_devices(self) -> dict[str, Any]:
        store = Store(self.hass, 1, f"{DOMAIN}.frame_devices.{self._entry.entry_id}")
        data = await store.async_load() or {}
        devices = data.get("devices", {}) if isinstance(data, dict) else {}
        return devices if isinstance(devices, dict) else {}

    async def _async_save_devices(self, devices: dict[str, Any]) -> None:
        store = Store(self.hass, 1, f"{DOMAIN}.frame_devices.{self._entry.entry_id}")
        await store.async_save({"devices": devices})

    def _profile_defaults(self, devices: dict[str, Any]) -> dict[str, Any]:
        def _normalize_format(value: Any) -> str:
            fmt = str(value or "jpeg").strip().lower()
            if fmt == "bmp16":
                return "bmp24"
            return fmt if fmt in ("jpeg", "bmp24") else "jpeg"

        if self._action == "edit" and self._source_device_key:
            p = devices.get(self._source_device_key, {})
            if isinstance(p, dict) and p:
                return {
                    "device_key": p.get("device_key", self._source_device_key),
                    "esp_device_id": p.get("esp_device_id", ""),
                    "name": p.get("name", ""),
                    "album_ids": list(p.get("album_ids", [])),
                    "width": int(p.get("width", 800)),
                    "height": int(p.get("height", 480)),
                    "image_format": _normalize_format(p.get("image_format", "jpeg")),
                    "randomize": bool(p.get("randomize", True)),
                    "max_photos": int(p.get("max_photos", 500)),
                    "max_cache_files": int(p.get("max_cache_files", 80)),
                    "prefetch_each_side": int(p.get("prefetch_each_side", 5)),
                    "rotation_minutes": int(p.get("rotation_minutes", DEFAULT_ROTATION_MINUTES)),
                    "presence_entity_id": p.get("presence_entity_id"),
                    "presence_require_on_entities": list(p.get("presence_require_on_entities") or []),
                    "presence_require_off_entities": list(p.get("presence_require_off_entities") or []),
                }
        return {
            "device_key": "",
            "esp_device_id": "",
            "name": "",
            "album_ids": [],
            "width": 800,
            "height": 480,
            "image_format": "jpeg",
            "randomize": True,
            "max_photos": 500,
            "max_cache_files": 80,
            "prefetch_each_side": 5,
            "rotation_minutes": DEFAULT_ROTATION_MINUTES,
            "presence_entity_id": None,
            "presence_require_on_entities": [],
            "presence_require_off_entities": [],
        }

    async def _async_get_album_options(self) -> dict[str, str]:
        """Return map album_id -> label for multi-select in options flow."""
        session = async_get_clientsession(self.hass)
        client = NextcloudMemoriesClient(
            session=session,
            base_url=str(self._entry.data[CONF_BASE_URL]).rstrip("/"),
            api_token=str(self._entry.data[CONF_API_TOKEN]),
            username=str(self._entry.data.get(CONF_USERNAME) or "").strip() or None,
            verify_ssl=bool(self._entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
        )
        try:
            albums = await asyncio.wait_for(client.async_get_albums(), timeout=10)
        except Exception:  # pragma: no cover - UI fallback
            _LOGGER.exception("Unable to load album list for options flow")
            return {}

        options: dict[str, str] = {}
        for album in albums:
            aid = str(album.get("id") or "").strip()
            if not aid:
                continue
            name = str(album.get("name") or aid)
            options[aid] = f"{name} ({aid})"
        return options

    def _get_esp_device_options(self, devices: dict[str, Any] | None = None) -> dict[str, str]:
        """Return map esp_device_id -> label from ESPHome config entries."""
        options: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries("esphome"):
            data = entry.data if isinstance(entry.data, dict) else {}
            esp_id = str(data.get("device_name", "")).strip()
            if not esp_id:
                continue
            label = str(entry.title or esp_id)
            options[esp_id] = f"{label} ({esp_id})"
        # Include already configured values to avoid empty selector in edge cases.
        if devices:
            for profile in devices.values():
                if not isinstance(profile, dict):
                    continue
                esp_id = str(profile.get("esp_device_id", "")).strip()
                if esp_id and esp_id not in options:
                    options[esp_id] = esp_id
        return options


def _sanitize_device_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9._-]", "_", value.strip())
    if not key:
        raise HomeAssistantError("invalid_device_key")
    return key


def _sanitize_esp_device_id(value: str | None) -> str | None:
    if value is None:
        return None
    out = re.sub(r"[^a-zA-Z0-9._-]", "_", value.strip())
    return out or None


def _normalize_album_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    out: list[str] = []
    for v in value:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def _default_image_base_url(hass: HomeAssistant) -> str:
    base = (
        (hass.config.internal_url or "").strip()
        or (hass.config.external_url or "").strip()
        or "http://homeassistant.local:8123"
    )
    return base.rstrip("/")
