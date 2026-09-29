from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

from .beta11_coordinator import ZalgirisMatchesCoordinator as Beta11Coordinator
from .beta7_coordinator import _strip_html
from .beta9_coordinator import (
    EUROLEAGUE_PBP_URL,
    EUROLEAGUE_SEASON,
    GAME_WINDOW,
    PREGAME_WINDOW,
    _status_finished,
    _to_int,
)

LKL_LIVE_URL = "https://lkl.lt/"
EUROLEAGUE_LIVE_POLL_SECONDS = 10

TEAM_ALIASES = {
    "žalgiris": ["ŽAL", "ZAL", "Žalgiris"],
    "siauliai": ["ŠIA", "SIA", "Šiauliai"],
    "šiauliai": ["ŠIA", "SIA", "Šiauliai"],
    "lietkabelis": ["LIE", "Lietkabelis"],
    "nevėžis": ["NEV", "Nevėžis", "Nevėžis-Paskolų klubas"],
    "nevėžis-paskolų klubas": ["NEV", "Nevėžis", "Nevėžis-Paskolų klubas"],
    "rytas": ["RYT", "Rytas"],
    "juventus": ["JUV", "Juventus"],
    "neptūnas": ["NEP", "Neptūnas"],
    "gargždai": ["GAR", "Gargždai"],
    "tauragė": ["TAU", "Tauragė"],
    "hipocredit": ["JON", "Hipocredit", "Jonava"],
    "jonava": ["JON", "Hipocredit", "Jonava"],
}

TEAM_CODE_TO_NAME = {
    "ZAL": "Žalgiris",
    "ŽAL": "Žalgiris",
    "SIA": "Šiauliai",
    "ŠIA": "Šiauliai",
    "LIE": "Lietkabelis",
    "NEV": "Nevėžis",
    "RYT": "Rytas",
    "JUV": "Juventus",
    "NEP": "Neptūnas",
    "GAR": "Gargždai",
    "TAU": "Tauragė",
    "JON": "Hipocredit",
}

INVALID_TEAM_WORDS = (
    "google play",
    "google pay",
    "app store",
    "apple store",
    "facebook",
    "instagram",
    "youtube",
    "linkedin",
    "tiktok",
)


def _norm_team(name: Any) -> str:
    return str(name or "").strip().lower()


def _is_zalgiris(name: Any) -> bool:
    return "žalgiris" in _norm_team(name) or "zalgiris" in _norm_team(name)


def _valid_team_pair(home: Any, away: Any) -> bool:
    h = _norm_team(home)
    a = _norm_team(away)
    if not h or not a:
        return False
    if any(word in h or word in a for word in INVALID_TEAM_WORDS):
        return False
    return _is_zalgiris(home) or _is_zalgiris(away)


def _alias_pattern(team: str) -> str:
    key = _norm_team(team)
    aliases = TEAM_ALIASES.get(key, [team])
    aliases = sorted({a for a in aliases if a}, key=len, reverse=True)
    return "(?:" + "|".join(re.escape(a) for a in aliases) + ")"


def _parse_lkl_homepage_score(raw_html: str, game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a known current game from the official LKL homepage scoreboard."""
    home = str(game.get("home") or "").strip()
    away = str(game.get("away") or "").strip()
    if not home or not away:
        return None

    text = _strip_html(raw_html)
    home_pat = _alias_pattern(home)
    away_pat = _alias_pattern(away)
    pattern = re.compile(
        rf"{home_pat}.{{0,100}}?(\d{{1,3}})\s*-\s*(\d{{1,3}})(.{{0,100}}?){away_pat}",
        re.IGNORECASE,
    )

    candidates = list(pattern.finditer(text))
    if not candidates:
        return None

    match = next((m for m in candidates if "gyvai" in m.group(3).lower()), candidates[0])
    return {
        "score_home": int(match.group(1)),
        "score_away": int(match.group(2)),
        "status": "inprogress" if "gyvai" in match.group(3).lower() else "finished",
        "source": "LKL.lt",
    }


def _parse_current_lkl_live(raw_html: str) -> Optional[Dict[str, Any]]:
    """Parse Žalgiris live block without relying on cached team names."""
    text = _strip_html(raw_html)
    pattern = re.compile(
        r"\b([A-ZĄČĘĖĮŠŲŪŽ]{2,4})\s+(\d{1,3})\s*-\s*(\d{1,3})\s*GYVAI\s*[●•]?\s*([A-ZĄČĘĖĮŠŲŪŽ]{2,4})\b",
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        home_code = match.group(1).upper()
        away_code = match.group(4).upper()
        if home_code not in {"ZAL", "ŽAL"} and away_code not in {"ZAL", "ŽAL"}:
            continue
        return {
            "home_code": home_code,
            "away_code": away_code,
            "home": TEAM_CODE_TO_NAME.get(home_code, home_code),
            "away": TEAM_CODE_TO_NAME.get(away_code, away_code),
            "score_home": int(match.group(2)),
            "score_away": int(match.group(3)),
            "status": "inprogress",
            "source": "LKL.lt",
        }
    return None


def _parse_euroleague_live(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract EuroLeague score plus the newest available event clock."""
    period_keys = [
        ("FirstQuarter", "Q1"),
        ("SecondQuarter", "Q2"),
        ("ThirdQuarter", "Q3"),
        ("ForthQuarter", "Q4"),
        ("ExtraTime", "OT"),
    ]

    events_with_period: List[tuple[int, str, Dict[str, Any]]] = []
    for key, label in period_keys:
        events = payload.get(key)
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            sequence = _to_int(event.get("NUMBEROFPLAY")) or 0
            events_with_period.append((sequence, label, event))

    if not events_with_period:
        return None

    # Running score is only populated on scoring plays, so use the latest
    # scoring event for points.
    scored: List[tuple[int, Dict[str, Any], int, int]] = []
    for sequence, _label, event in events_with_period:
        score_a = _to_int(event.get("POINTS_A"))
        score_b = _to_int(event.get("POINTS_B"))
        if score_a is not None and score_b is not None:
            scored.append((sequence, event, score_a, score_b))

    if not scored:
        return None

    _score_sequence, _score_event, score_a, score_b = max(scored, key=lambda item: item[0])

    # Clock must come from the latest event, not from the latest scoring event.
    # The old code made the clock appear badly delayed whenever several
    # rebounds/fouls/misses happened after the last basket.
    clock: Optional[str] = None
    latest_period: Optional[str] = None
    for _sequence, label, event in sorted(events_with_period, key=lambda item: item[0], reverse=True):
        marker = str(event.get("MARKERTIME") or "").strip()
        if marker:
            clock = marker
            latest_period = label
            break

    actual_quarter = _to_int(payload.get("ActualQuarter"))
    if actual_quarter is not None:
        if 1 <= actual_quarter <= 4:
            period = f"Q{actual_quarter}"
        elif actual_quarter >= 5:
            period = "OT" if actual_quarter == 5 else f"OT{actual_quarter - 4}"
        else:
            period = latest_period
    else:
        period = latest_period

    return {
        "score_a": score_a,
        "score_b": score_b,
        "status": "inprogress" if bool(payload.get("Live")) else "finished",
        "period": period,
        "clock": clock,
        "team_a": payload.get("TeamA"),
        "team_b": payload.get("TeamB"),
        "code_a": payload.get("CodeTeamA"),
        "code_b": payload.get("CodeTeamB"),
        "source": "EuroLeague",
    }


class ZalgirisMatchesCoordinator(Beta11Coordinator):
    """Beta coordinator with corrected official live feeds."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._lkl_live_repair: Dict[str, Any] = {}

    def _parse_match_from_window(self, game_id: str, window: str) -> Dict[str, Any]:
        parsed = super()._parse_match_from_window(game_id, window)

        # Do not let footer/app icons overwrite a known game while zalgiris.lt
        # changes its card markup during live matches.
        if not _valid_team_pair(parsed.get("home"), parsed.get("away")):
            parsed["home"] = None
            parsed["away"] = None
            parsed["home_logo"] = None
            parsed["away_logo"] = None
            parsed["league"] = None

        return parsed

    def _known_logo(self, team_name: str) -> Optional[str]:
        wanted = _norm_team(team_name)
        for game in self._games.values():
            for side in ("home", "away"):
                if _norm_team(game.get(side)) != wanted:
                    continue
                logo = game.get(f"{side}_logo")
                if not isinstance(logo, str) or not logo:
                    continue
                low = logo.lower()
                if "google-play" in low or "app-store" in low:
                    continue
                return logo
        return None

    def _repair_game_from_live_block(self, game: Dict[str, Any], live: Dict[str, Any]) -> None:
        game["home"] = live["home"]
        game["away"] = live["away"]
        game["league"] = "Lietuvos Krepšinio Lyga"
        game["is_live"] = True

        home_logo = self._known_logo(live["home"])
        away_logo = self._known_logo(live["away"])
        if home_logo:
            game["home_logo"] = home_logo
        elif "google-play" in str(game.get("home_logo") or "").lower():
            game["home_logo"] = None
        if away_logo:
            game["away_logo"] = away_logo
        elif "app-store" in str(game.get("away_logo") or "").lower():
            game["away_logo"] = None

        self._apply_scores(
            game,
            live["score_home"],
            live["score_away"],
            status=live["status"],
            source=live["source"],
        )

    def _desired_poll_seconds(self, now=None) -> Optional[int]:
        """Poll EuroLeague faster while a game is active."""
        now = now or dt_util.now()
        desired = super()._desired_poll_seconds(now)

        for game in self._games.values():
            league = str(game.get("league") or "").lower()
            if "euro" not in league:
                continue
            start_raw = game.get("start")
            start_dt = dt_util.parse_datetime(start_raw) if isinstance(start_raw, str) else None
            if not start_dt:
                continue
            if start_dt <= now <= start_dt + GAME_WINDOW and not _status_finished(game.get("live_status")):
                return min(desired or EUROLEAGUE_LIVE_POLL_SECONDS, EUROLEAGUE_LIVE_POLL_SECONDS)

        return desired

    async def _update_lkl_games(self, games: List[Dict[str, Any]], now) -> int:
        if not games:
            return 0

        raw_html = await self._fetch_live_text("lkl_live", LKL_LIVE_URL)
        if not raw_html:
            return 0

        updated = 0
        for game in games:
            parsed = _parse_lkl_homepage_score(raw_html, game)
            if not parsed:
                continue
            self._apply_scores(
                game,
                parsed["score_home"],
                parsed["score_away"],
                status=parsed["status"],
                source=parsed["source"],
            )
            game["is_live"] = parsed["status"] == "inprogress"
            updated += 1
        return updated

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
        game["live_clock_source"] = "latest_event"
        return 1

    async def _refresh_sofascore(self) -> int:
        """Compatibility hook: refresh live scores from official sources only."""
        now = dt_util.now()
        relevant: List[Dict[str, Any]] = []
        for game in self._games.values():
            start_raw = game.get("start")
            start_dt = dt_util.parse_datetime(start_raw) if isinstance(start_raw, str) else None
            if not start_dt or _status_finished(game.get("live_status")):
                continue
            if start_dt - PREGAME_WINDOW <= now <= start_dt + GAME_WINDOW:
                relevant.append(game)

        if not relevant:
            self._lkl_live_repair = {"found": False, "reason": "no_relevant_game"}
            return 0

        updated = 0
        repaired_game: Optional[Dict[str, Any]] = None

        # First inspect the official LKL live block independently from cached
        # team/league fields. This repairs old bad cache such as Google Play /
        # App Store and an incorrectly parsed EuroLeague label.
        raw_html = await self._fetch_live_text("lkl_live", LKL_LIVE_URL)
        live = _parse_current_lkl_live(raw_html) if raw_html else None
        if live:
            repaired_game = min(
                relevant,
                key=lambda g: abs(
                    (dt_util.parse_datetime(g.get("start")) - now).total_seconds()
                    if g.get("start") and dt_util.parse_datetime(g.get("start"))
                    else 10**12
                ),
            )
            self._repair_game_from_live_block(repaired_game, live)
            updated += 1
            self._lkl_live_repair = {
                "found": True,
                "game_id": repaired_game.get("game_id"),
                "home": live["home"],
                "away": live["away"],
                "score": f"{live['score_home']}:{live['score_away']}",
            }
        else:
            self._lkl_live_repair = {"found": False, "reason": "live_block_not_found"}

        remaining = [g for g in relevant if g is not repaired_game]
        euro_games = [g for g in remaining if "euro" in str(g.get("league") or "").lower()]
        domestic_games = [g for g in remaining if g not in euro_games]

        if domestic_games:
            updated += await self._update_lkl_games(domestic_games, now)
        for game in euro_games:
            updated += await self._update_euroleague_game(game)

        return updated

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        debug = data.setdefault("debug", {})
        debug["lkl_live_source"] = LKL_LIVE_URL
        debug["team_validation"] = True
        debug["lkl_live_repair"] = dict(self._lkl_live_repair)
        debug["euroleague_live_poll_seconds"] = EUROLEAGUE_LIVE_POLL_SECONDS
        debug["euroleague_clock_source"] = "latest_event"
        return data
