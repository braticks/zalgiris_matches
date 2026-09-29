from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from homeassistant.util import dt as dt_util

from .beta12_coordinator import (
    ZalgirisMatchesCoordinator as Beta12Coordinator,
    _parse_euroleague_live,
)
from .beta9_coordinator import EUROLEAGUE_PBP_URL, EUROLEAGUE_SEASON, _to_int

PERIOD_KEYS = [
    ("FirstQuarter", "Q1"),
    ("SecondQuarter", "Q2"),
    ("ThirdQuarter", "Q3"),
    ("ForthQuarter", "Q4"),
    ("ExtraTime", "OT"),
]

QUARTER_BREAK_SECONDS = 120
HALFTIME_BREAK_SECONDS = 15 * 60
OVERTIME_BREAK_SECONDS = 120
TIMEOUT_SECONDS = 60


def _clock_to_seconds(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text or ":" not in text:
        return None
    try:
        minutes_s, seconds_s = text.split(":", 1)
        minutes = int(minutes_s)
        seconds = int(seconds_s)
    except (TypeError, ValueError):
        return None
    if minutes < 0 or seconds < 0 or seconds > 59:
        return None
    return minutes * 60 + seconds


def _format_seconds(seconds: int) -> str:
    value = max(0, int(seconds))
    return f"{value // 60:02d}:{value % 60:02d}"


def _latest_event(payload: Dict[str, Any]) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    latest: Optional[Tuple[int, str, Dict[str, Any]]] = None
    for key, label in PERIOD_KEYS:
        events = payload.get(key)
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            sequence = _to_int(event.get("NUMBEROFPLAY")) or 0
            if latest is None or sequence >= latest[0]:
                latest = (sequence, label, event)
    return latest


def _break_kind(period: Optional[str], play_info: str) -> Tuple[Optional[str], Optional[int]]:
    info = play_info.lower().strip()

    if "timeout" in info or "time out" in info:
        return "timeout", TIMEOUT_SECONDS

    if "end period" not in info and "end of period" not in info:
        return None, None

    if period == "Q2":
        return "halftime", HALFTIME_BREAK_SECONDS
    if period == "OT" or str(period or "").startswith("OT"):
        return "overtime", OVERTIME_BREAK_SECONDS
    return "quarter", QUARTER_BREAK_SECONDS


class ZalgirisMatchesCoordinator(Beta12Coordinator):
    """Add live clock metadata and estimated break countdowns."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._break_started: Dict[str, Dict[str, Any]] = {}

    def _set_break_state(
        self,
        game: Dict[str, Any],
        *,
        sequence: int,
        period: Optional[str],
        break_type: str,
        duration: int,
    ) -> None:
        game_id = str(game.get("game_id") or "")
        now = dt_util.now()
        tracker = self._break_started.get(game_id)

        if not tracker or tracker.get("sequence") != sequence or tracker.get("type") != break_type:
            tracker = {
                "sequence": sequence,
                "type": break_type,
                "started_at": now,
                "duration": duration,
            }
            self._break_started[game_id] = tracker

        started_at = tracker.get("started_at")
        elapsed = int((now - started_at).total_seconds()) if started_at else 0
        remaining = max(0, int(tracker.get("duration", duration)) - elapsed)

        game["live_state"] = "break"
        game["break_type"] = break_type
        game["break_clock_seconds"] = remaining
        game["break_clock"] = _format_seconds(remaining)
        game["clock_source"] = "estimated_local"
        game["live_clock_synced_at"] = now.isoformat()
        if period:
            game["live_period"] = period

    def _clear_break_state(self, game: Dict[str, Any]) -> None:
        game_id = str(game.get("game_id") or "")
        self._break_started.pop(game_id, None)
        game["break_type"] = None
        game["break_clock"] = None
        game["break_clock_seconds"] = None

    async def _update_euroleague_game(self, game: Dict[str, Any]) -> int:
        gamecode = await self._euroleague_gamecode(game)
        if gamecode is None:
            return 0

        url = f"{EUROLEAGUE_PBP_URL}?gamecode={gamecode}&seasoncode={EUROLEAGUE_SEASON}"
        payload = await self._fetch_live_json("euroleague_pbp", url)
        if not payload:
            return 0

        parsed = _parse_euroleague_live(payload)
        if not parsed:
            return 0

        self._apply_scores(
            game,
            parsed["score_a"],
            parsed["score_b"],
            status=parsed["status"],
            source="EuroLeague",
            period=parsed.get("period"),
            clock=parsed.get("clock"),
        )

        game["euroleague_gamecode"] = gamecode
        game["live_clock_seconds"] = _clock_to_seconds(parsed.get("clock"))
        game["live_clock_synced_at"] = dt_util.now().isoformat()
        game["clock_source"] = "official_event"

        latest = _latest_event(payload)
        if latest:
            sequence, event_period, event = latest
            play_info = str(event.get("PLAYINFO") or "").strip()
            game["live_last_play"] = play_info or None
            game["live_last_play_number"] = sequence

            break_type, duration = _break_kind(event_period, play_info)
            if parsed.get("status") == "inprogress" and break_type and duration:
                self._set_break_state(
                    game,
                    sequence=sequence,
                    period=event_period,
                    break_type=break_type,
                    duration=duration,
                )
            else:
                self._clear_break_state(game)
                game["live_state"] = "live" if parsed.get("status") == "inprogress" else "finished"
        else:
            self._clear_break_state(game)
            game["live_state"] = "live" if parsed.get("status") == "inprogress" else "finished"

        return 1

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        debug = data.setdefault("debug", {})
        debug["live_clock_entities"] = True
        debug["break_countdown_mode"] = "estimated_from_latest_play"
        return data
