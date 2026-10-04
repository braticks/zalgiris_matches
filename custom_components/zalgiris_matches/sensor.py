from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .live_selection import select_live_game
from .const import DOMAIN
from .coordinator import ZalgirisMatchesCoordinator


@dataclass(frozen=True)
class SensorDescription:
    key: str
    name: str
    device_class: Optional[SensorDeviceClass] = None


SENSORS = [
    SensorDescription("schedule", "Zalgiris - rungtyniu sarasas", None),
    SensorDescription("next", "Zalgiris - kitos rungtynes", SensorDeviceClass.TIMESTAMP),
    SensorDescription("live_score", "Zalgiris - live rezultatas", None),
    SensorDescription("zalgiris_score", "Zalgiris - taskai", None),
    SensorDescription("opponent_score", "Zalgiris - varzovo taskai", None),
    SensorDescription("opponent", "Zalgiris - varzovas", None),
    SensorDescription("live_status", "Zalgiris - live busena", None),
    SensorDescription("live_state", "Zalgiris - zaidimo busena", None),
    SensorDescription("live_period", "Zalgiris - live kelinys", None),
    SensorDescription("live_clock", "Zalgiris - live laikas", None),
    SensorDescription("live_clock_seconds", "Zalgiris - live laikas sekundemis", None),
    SensorDescription("break_type", "Zalgiris - pertraukos tipas", None),
    SensorDescription("break_clock", "Zalgiris - pertraukos laikas", None),
    SensorDescription("break_clock_seconds", "Zalgiris - pertraukos sekundes", None),
    SensorDescription("clock_source", "Zalgiris - laikrodzio saltinis", None),
    SensorDescription("live_source", "Zalgiris - live saltinis", None),
    SensorDescription("standing_euroleague", "Zalgiris - Eurolyga vieta", None),
    SensorDescription("standing_lkl", "Zalgiris - LKL vieta", None),
    SensorDescription("standing_kmt", "Zalgiris - KMT vieta", None),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ZalgirisMatchesCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [ZalgirisSensor(coordinator, entry, desc) for desc in SENSORS]
    async_add_entities(entities)


class ZalgirisSensor(CoordinatorEntity[ZalgirisMatchesCoordinator], SensorEntity):
    def __init__(self, coordinator: ZalgirisMatchesCoordinator, entry: ConfigEntry, desc: SensorDescription) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.desc = desc
        self._attr_name = desc.name
        self._attr_device_class = desc.device_class
        self._attr_unique_id = f"{entry.entry_id}_{desc.key}"

    def _live_game(self) -> Optional[Dict[str, Any]]:
        data = self.coordinator.data or {}
        games = (data.get("finished") or []) + (data.get("upcoming") or [])
        return select_live_game(games, dt_util.now())

    def _standing(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        key_map = {
            "standing_euroleague": "euroleague",
            "standing_lkl": "lkl",
            "standing_kmt": "kmt",
        }
        standing_key = key_map.get(self.desc.key)
        if not standing_key:
            return {}
        standings = data.get("standings") or {}
        value = standings.get(standing_key) or {}
        return value if isinstance(value, dict) else {}

    @property
    def native_value(self):
        data = self.coordinator.data or {}

        if self.desc.key == "schedule":
            return len(data.get("upcoming") or []) + len(data.get("finished") or [])

        if self.desc.key == "next":
            upcoming = data.get("upcoming") or []
            if not upcoming:
                return None
            return dt_util.parse_datetime(upcoming[0].get("start"))

        if self.desc.key.startswith("standing_"):
            standing = self._standing()
            return standing.get("position") or standing.get("stage")

        game = self._live_game()
        if not game:
            return None

        if self.desc.key == "live_score":
            zs = game.get("zalgiris_score")
            os = game.get("opponent_score")
            if zs is None or os is None:
                return None
            return f"{zs}:{os}"
        if self.desc.key == "zalgiris_score":
            return game.get("zalgiris_score")
        if self.desc.key == "opponent_score":
            return game.get("opponent_score")
        if self.desc.key == "opponent":
            return game.get("opponent")
        if self.desc.key == "live_status":
            return game.get("live_status")
        if self.desc.key == "live_state":
            return game.get("live_state")
        if self.desc.key == "live_period":
            return game.get("live_period")
        if self.desc.key == "live_clock":
            return game.get("live_clock")
        if self.desc.key == "live_clock_seconds":
            return game.get("live_clock_seconds")
        if self.desc.key == "break_type":
            return game.get("break_type")
        if self.desc.key == "break_clock":
            return game.get("break_clock")
        if self.desc.key == "break_clock_seconds":
            return game.get("break_clock_seconds")
        if self.desc.key == "clock_source":
            return game.get("clock_source")
        if self.desc.key == "live_source":
            return game.get("live_source")

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}

        if self.desc.key == "schedule":
            # Important: coordinator mutates game dictionaries in-place during
            # fast live refreshes. Home Assistant keeps the previous State
            # attributes for equality comparison. Returning the same nested
            # list/dict objects can therefore make an attribute-only live
            # change look unchanged to the frontend. Deep-copying creates a
            # real snapshot on every write so Lovelace receives state_changed
            # for score/period/clock updates as well.
            return {
                "team_path": data.get("team_path"),
                "source_url": data.get("source_url"),
                "fetched_at": data.get("fetched_at"),
                "upcoming": deepcopy(data.get("upcoming")),
                "finished": deepcopy(data.get("finished")),
                "standings": deepcopy(data.get("standings")),
                "debug": deepcopy(data.get("debug")),
            }

        if self.desc.key == "next":
            upcoming = data.get("upcoming") or []
            return deepcopy(upcoming[0]) if upcoming else {}

        if self.desc.key.startswith("standing_"):
            return deepcopy(self._standing())

        game = self._live_game()
        return deepcopy(game) if game else {}

