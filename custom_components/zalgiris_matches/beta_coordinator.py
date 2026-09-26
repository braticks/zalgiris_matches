from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import async_timeout

from homeassistant.util import dt as dt_util

from .coordinator import ZalgirisMatchesCoordinator as BaseZalgirisMatchesCoordinator
from .standings import TOURNAMENTS, parse_team_standing, select_current_season

_LOGGER = logging.getLogger(__name__)

SOFASCORE_TEAM_ID = 6662
SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"

LIVE_POLL_SECONDS = 30
PREGAME_POLL_SECONDS = 60
POSTGAME_POLL_SECONDS = 300
PREGAME_WINDOW = timedelta(minutes=30)
GAME_WINDOW = timedelta(hours=4)
BASE_REFRESH_DURING_GAME = timedelta(minutes=5)
STANDINGS_REFRESH = timedelta(hours=2)

FINISHED_STATUSES = {
    "finished",
    "ended",
    "canceled",
    "cancelled",
    "postponed",
}


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


def _status_finished(status: Any) -> bool:
    return str(status or "").strip().lower() in FINISHED_STATUSES


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
    """Beta coordinator with SofaScore live scores and standings."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._last_base_refresh = None
        self._last_standings_refresh = None
        self._standings: Dict[str, Dict[str, Any]] = {}

    def _match_window_active(self, now=None) -> bool:
        now = now or dt_util.now()
        for game in self._games.values():
            start_iso = game.get("start")
            start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
            if start_dt and start_dt - PREGAME_WINDOW <= now <= start_dt + GAME_WINDOW:
                return True
        return False

    def _desired_poll_seconds(self, now=None) -> Optional[int]:
        now = now or dt_util.now()
        desired: Optional[int] = None

        for game in self._games.values():
            start_iso = game.get("start")
            start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
            if not start_dt:
                continue

            if start_dt - PREGAME_WINDOW <= now < start_dt:
                desired = PREGAME_POLL_SECONDS if desired is None else min(desired, PREGAME_POLL_SECONDS)
                continue

            if start_dt <= now <= start_dt + GAME_WINDOW:
                if _status_finished(game.get("live_status")):
                    desired = POSTGAME_POLL_SECONDS if desired is None else min(desired, POSTGAME_POLL_SECONDS)
                else:
                    desired = LIVE_POLL_SECONDS if desired is None else min(desired, LIVE_POLL_SECONDS)

        return desired

    async def _fetch_json(self, url: str) -> Optional[Dict[str, Any]]:
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
                        _LOGGER.debug("SofaScore returned HTTP %s for %s", resp.status, url)
                        return None
                    payload = await resp.json(content_type=None)
                    return payload if isinstance(payload, dict) else None
                finally:
                    resp.release()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("SofaScore beta fetch failed for %s: %s", url, err)
            return None

    async def _fetch_sofascore_day(self, day: str) -> List[Dict[str, Any]]:
        payload = await self._fetch_json(f"{SOFASCORE_BASE_URL}/sport/basketball/scheduled-events/{day}")
        events = payload.get("events", []) if payload else []
        return [event for event in events if isinstance(event, dict) and _matches_zalgiris(event)]

    async def _refresh_sofascore(self) -> int:
        now = dt_util.now()
        relevant = []
        for game in self._games.values():
            start_iso = game.get("start")
            start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
            if not start_dt:
                continue
            if _status_finished(game.get("live_status")):
                continue
            if start_dt - PREGAME_WINDOW <= now <= start_dt + GAME_WINDOW:
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
            home_id = home.get("id")
            away_id = away.get("id")
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
            game["sofascore_home_id"] = home_id
            game["sofascore_away_id"] = away_id

            if home_id == SOFASCORE_TEAM_ID:
                game["zalgiris_score"] = home_score
                game["opponent_score"] = away_score
                game["opponent"] = away.get("name")
            elif away_id == SOFASCORE_TEAM_ID:
                game["zalgiris_score"] = away_score
                game["opponent_score"] = home_score
                game["opponent"] = home.get("name")

            updated += 1

        return updated

    async def _fetch_tournament_standing(self, key: str, tournament_id: int) -> Optional[Dict[str, Any]]:
        seasons_payload = await self._fetch_json(
            f"{SOFASCORE_BASE_URL}/unique-tournament/{tournament_id}/seasons"
        )
        if not seasons_payload:
            return None

        season = select_current_season(seasons_payload.get("seasons", []), dt_util.now())
        if not season:
            return None
        season_id = season.get("id")
        if season_id is None:
            return None

        standings_payload = await self._fetch_json(
            f"{SOFASCORE_BASE_URL}/unique-tournament/{tournament_id}/season/{season_id}/standings/total"
        )
        standing = parse_team_standing(standings_payload) if standings_payload else None
        if not standing:
            return None

        standing["tournament"] = TOURNAMENTS[key]["name"]
        standing["tournament_id"] = tournament_id
        standing["season"] = season.get("name") or season.get("year")
        standing["season_id"] = season_id
        standing["source"] = "SofaScore"
        standing["updated_at"] = dt_util.now().isoformat()
        return standing

    async def _refresh_standings(self) -> int:
        updated = 0
        for key, tournament in TOURNAMENTS.items():
            standing = await self._fetch_tournament_standing(key, int(tournament["id"]))
            if standing:
                self._standings[key] = standing
                updated += 1
        self._last_standings_refresh = dt_util.now()
        return updated

    async def _async_update_data(self) -> Dict[str, Any]:
        now = dt_util.now()
        in_match_window = self._match_window_active(now)
        refresh_base = (
            self.data is None
            or self._last_base_refresh is None
            or not in_match_window
            or now - self._last_base_refresh >= BASE_REFRESH_DURING_GAME
        )

        if refresh_base:
            data = await super()._async_update_data()
            self._last_base_refresh = now
        else:
            data = dict(self.data or {})

        try:
            updated = await self._refresh_sofascore()
        except Exception as err:  # noqa: BLE001
            updated = 0
            _LOGGER.debug("SofaScore beta enrichment failed: %s", err)

        standings_due = (
            self._last_standings_refresh is None
            or now - self._last_standings_refresh >= STANDINGS_REFRESH
        )
        standings_updated = 0
        if standings_due:
            try:
                standings_updated = await self._refresh_standings()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("SofaScore standings refresh failed: %s", err)
                self._last_standings_refresh = now

        upcoming, finished = self._classify()
        data["upcoming"] = upcoming
        data["finished"] = finished
        data["standings"] = dict(self._standings)
        data.setdefault("debug", {})["sofascore_matches_updated"] = updated
        data["debug"]["sofascore_standings_updated"] = standings_updated
        data["debug"]["live_score_beta"] = True
        data["debug"]["zalgiris_schedule_refreshed"] = refresh_base
        data["debug"]["live_fetched_at"] = dt_util.now().isoformat()

        desired = self._desired_poll_seconds()
        if desired is not None:
            self.update_interval = timedelta(seconds=desired)
            data["debug"]["next_poll_seconds"] = desired

        return data
