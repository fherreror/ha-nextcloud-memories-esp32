# Changelog

## [Unreleased]

- Prepare the existing integration for GitHub, Marketplace/HACS and offline CI tests.
- Replace deprecated device registry APIs with the 2026+ single-config-entry API, preserving ESPHome frame lookups.
- Add offline regression tests for MAC and LCD backlight resolution.
- Add per-frame ON/OFF prerequisite entities for presence-controlled backlights, with fail-closed evaluation and rechecks on prerequisite changes.
- Show the frame target and prerequisite fields dynamically in Home Assistant 2026.11+ options forms.
- Add Python CodeQL security analysis to pull requests, main branch updates, and a weekly schedule.
- Extend offline tests and configuration documentation.

## [0.1.0] - Initial existing implementation

- Nextcloud Memories album browsing, preview caching and ESPHome photo frames.
- Frame controls, sensors, rotation and presence/backlight support.
