from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

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

    @property
    def native_value(self):
        data = self.coordinator.data or {}

        if self.desc.key == "schedule":
            # Show total matches we currently know about (upcoming + finished)
            return len(data.get("upcoming") or []) + len(data.get("finished") or [])

        if self.desc.key == "next":
            upcoming = data.get("upcoming") or []
            if not upcoming:
                return None
            return dt_util.parse_datetime(upcoming[0].get("start"))

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}

        if self.desc.key == "schedule":
            return {
                "team_path": data.get("team_path"),
                "source_url": data.get("source_url"),
                "fetched_at": data.get("fetched_at"),
                "upcoming": data.get("upcoming"),
                "finished": data.get("finished"),
                "debug": data.get("debug"),
            }

        if self.desc.key == "next":
            upcoming = data.get("upcoming") or []
            return upcoming[0] if upcoming else {}

        return {}
