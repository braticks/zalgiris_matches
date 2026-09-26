from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import async_timeout

from homeassistant.util import dt as dt_util

from .coordinator import ZalgirisMatchesCoordinator as BaseZalgirisMatchesCoordinator

_LOGGER = logging.getLogger(__name__)

SOFASCORE_TEAM_ID = 6662
SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"


def _event_score(event: Dict[str, Any], side: str) -> Optional[int]:
    score = event.get(f"{side}Score") or {}
    value = score.get("current")
    return int(value) if isinstance(value, (int, float)) else None


def _event_status(event: Dict[str, Any]) -> Optional[str]:
    status = event.get("status") or {}
    return status.get("type") or status.get("description")


def _event_period(event: Dict[str, Any]) -> Optional[str]:
    period = event.get("lastPeriod")
    if period:
        return str(period)
    status = event.get("status") or {}
    description = status.get("description")
    return str(description) if description else None


def _event_clock(event: Dict[str, Any]) -> Optional[str]:
    time_data = event.get("time") or {}
    period_length = time_data.get("periodLength")
    played = time_data.get("played")
    if isinstance(period_length, (int, float)) and isinstance(played, (int, float)):
        remaining = max(0, int(period_length - played))
        return f"{remaining // 60}:{remaining % 60:02d}"
    return None


def _matches_zalgiris(event: Dict[str, Any]) -> bool:
    home_id = (event.get("homeTeam") or {}).get("id")
    away_id = (event.get("awayTeam") or {}).get("id")
    return home_id == SOFASCORE_TEAM_ID or away_id == SOFASCORE_TEAM_ID


def _find_matching_event(game: Dict[str, Any], events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    start_iso = game.get("start")
    start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
    if not start_dt:
        return None

    best: Optional[Dict[str, Any]] = None
    best_delta = 4 * 3600 + 1

    for event in events:
        if not _matches_zalgiris(event):
            continue
        ts = event.get("startTimestamp")
        if not isinstance(ts, (int, float)):
            continue
        delta = abs(start_dt.timestamp() - float(ts))
        if delta < best_delta and delta <= 4 * 3600:
            best = event
            best_delta = delta

    return best


class ZalgirisMatchesCoordinator(BaseZalgirisMatchesCoordinator):
    """Beta coordinator that enriches zalgiris.lt fixtures with SofaScore live scores."""

    async def _fetch_sofascore_day(self, day: str) -> List[Dict[str, Any]]:
        url = f"{SOFASCORE_BASE_URL}/sport/basketball/scheduled-events/{day}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.sofascore.com/",
        }
        try:
            async with async_timeout.timeout(10):
                resp = await self.session.get(url, headers=headers, allow_redirects=True)
                try:
                    if resp.status != 200:
                        _LOGGER.debug("SofaScore returned HTTP %s", resp.status)
                        return []
                    payload = await resp.json(content_type=None)
                finally:
                    resp.release()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("SofaScore beta fetch failed: %s", err)
            return []

        events = payload.get("events", []) if isinstance(payload, dict) else []
        return [event for event in events if isinstance(event, dict) and _matches_zalgiris(event)]

    async def _refresh_sofascore(self) -> int:
        now = dt_util.now()
        relevant = []
        for game in self._games.values():
            start_iso = game.get("start")
            start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
            if start_dt and now - timedelta(hours=8) <= start_dt <= now + timedelta(hours=8):
                relevant.append(game)

        if not relevant:
            return 0

        days = {now.date().isoformat()}
        for game in relevant:
            start_dt = dt_util.parse_datetime(game.get("start"))
            if start_dt:
                days.add(start_dt.date().isoformat())

        events: List[Dict[str, Any]] = []
        for day in sorted(days):
            events.extend(await self._fetch_sofascore_day(day))

        updated = 0
        for game in relevant:
            event = _find_matching_event(game, events)
            if not event:
                continue

            home = event.get("homeTeam") or {}
            away = event.get("awayTeam") or {}
            home_score = _event_score(event, "home")
            away_score = _event_score(event, "away")

            if home_score is not None:
                game["score_home"] = home_score
            if away_score is not None:
                game["score_away"] = away_score

            game["live_source"] = "SofaScore"
            game["sofascore_event_id"] = event.get("id")
            game["live_status"] = _event_status(event)
            game["live_period"] = _event_period(event)
            game["live_clock"] = _event_clock(event)
            game["sofascore_home"] = home.get("name")
            game["sofascore_away"] = away.get("name")
            updated += 1

        return updated

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()

        try:
            updated = await self._refresh_sofascore()
        except Exception as err:  # noqa: BLE001
            updated = 0
            _LOGGER.debug("SofaScore beta enrichment failed: %s", err)

        upcoming, finished = self._classify()
        data["upcoming"] = upcoming
        data["finished"] = finished
        data.setdefault("debug", {})["sofascore_matches_updated"] = updated
        data["debug"]["live_score_beta"] = True
        return data
