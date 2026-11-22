"""Pure helpers for enabling presence-controlled frame backlights.

The conditions are evaluated in Home Assistant by the caller, but the helpers
are independent of Home Assistant for fast offline regression testing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

PRESENCE_REQUIRE_ON = "presence_require_on_entities"
PRESENCE_REQUIRE_OFF = "presence_require_off_entities"


def normalize_condition_entities(value: Any) -> list[str]:
    """Normalize a multi-entity selection while preserving its order."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )


def presence_conditions_valid(profile: Mapping[str, Any]) -> bool:
    """Reject conflicting requirements for the same entity."""
    required_on = set(normalize_condition_entities(profile.get(PRESENCE_REQUIRE_ON)))
    required_off = set(normalize_condition_entities(profile.get(PRESENCE_REQUIRE_OFF)))
    return not bool(required_on & required_off)


def presence_conditions_met(
    profile: Mapping[str, Any],
    get_state: Callable[[str], str | None],
) -> bool:
    """Require ALL configured conditions; unknown/missing state fails closed.

    With no conditions the result is True, preserving legacy frame behaviour.
    This guards only *turning on* a backlight; absence-driven turn-off remains
    independent of conditions.
    """
    if not presence_conditions_valid(profile):
        return False

    for key, expected_state in ((PRESENCE_REQUIRE_ON, "on"), (PRESENCE_REQUIRE_OFF, "off")):
        for entity_id in normalize_condition_entities(profile.get(key)):
            if get_state(entity_id) != expected_state:
                return False
    return True
