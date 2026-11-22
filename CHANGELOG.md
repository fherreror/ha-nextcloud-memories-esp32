# Changelog

## [Unreleased]

## [0.1.1] - Unreleased

- Add Spanish translations for setup and frame configuration forms.
- Explain frame options, presence backlight behavior, and ON/OFF prerequisites in both languages.
- Translate create/edit/delete actions and image-format choices while preserving their internal values.
- Declare Home Assistant 2026.11.0 as the minimum supported version in Marketplace/HACS metadata.
- Keep presence prerequisite selectors conditional on selecting a presence entity.

## [0.1.0] - 2026-11-22

First public release of the Nextcloud Memories ESP32 integration for Home Assistant.

- Connect Home Assistant to Nextcloud Memories albums and configure ESPHome/ESP32 photo frames.
- Browse albums, cache and prepare JPEG/BMP24 images, prefetch adjacent photos, and rotate photos automatically.
- Provide frame sensors, next/previous/shuffle buttons, rotation interval controls, and actions for managing frames.
- Support presence-controlled LCD backlights, including per-frame prerequisites requiring selected entities to be ON or OFF; reevaluate when prerequisites change.
- Show the target frame only when editing/deleting and show prerequisite selectors only when presence is configured (Home Assistant 2026.11+).
- Update device registry access for compatibility with newer Home Assistant releases.
- Use the standard `custom_components/nextcloud_memories` repository layout for Marketplace/HACS.
- Add English translations, integration branding, installation documentation, and the MIT license.
- Add offline regression tests, HACS/Hassfest/Python CI, and CodeQL security analysis.

**Testing note:** Offline checks pass. Manual testing has confirmed startup and integration loading in Home Assistant 2026.11.2; all presence prerequisite combinations have not yet been exercised on physical frames.
