from __future__ import annotations

import re
from html.parser import HTMLParser
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


class _LklRows(HTMLParser):
    """Keep each scoreboard row isolated, including its preceding date label."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.context = ""
        self.depth = 0
        self.row = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "battle-row" in attrs.get("class", "").split():
                self.depth = 1
                self.row = {"text": "", "teams": [], "id": None,
                            "date_context": self.context[-300:]}
        if not self.depth:
            return
        if tag == "img" and attrs.get("alt"):
            self.row["teams"].append(attrs["alt"])
        if tag == "a":
            match = re.search(r"/rungtynes/(\d+)(?:[/?#]|$)", attrs.get("href", ""))
            if match:
                self.row["id"] = match.group(1)

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.rows.append(self.row)
                self.row = None

    def handle_data(self, data):
        if self.depth:
            self.row["text"] += " " + data
        else:
            self.context = (self.context + " " + data)[-600:]


def _lkl_rows(raw_html):
    parser = _LklRows()
    parser.feed(raw_html)
    return parser.rows


def _parse_lkl_homepage_score(raw_html: str, game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Require the same date and ordered teams inside one scoreboard row."""
    start = dt_util.parse_datetime(game.get("start") or "")
    if not start or not game.get("home") or not game.get("away"):
        return None
    months = ("sausio", "vasario", "kovo", "balandžio", "gegužės", "birželio",
              "liepos", "rugpjūčio", "rugsėjo", "spalio", "lapkričio", "gruodžio")
    candidates = []
    for row in _lkl_rows(raw_html):
        if not row["id"] or len(row["teams"]) != 2:
            continue
        dates = list(re.finditer(
            r"(" + "|".join(months) + r")\s+(\d{1,2})\s*d\.",
            row["date_context"], re.IGNORECASE))
        if not dates:
            continue
        date = dates[-1]
        if months.index(date.group(1).lower()) + 1 != start.month or int(date.group(2)) != start.day:
            continue
        if not all(re.fullmatch(_alias_pattern(game[side]), team, re.IGNORECASE)
                   for side, team in zip(("home", "away"), row["teams"])):
            continue
        score = re.search(r"(?<!\d)(\d{1,3})\s*-\s*(\d{1,3})(?!\d)", row["text"])
        if not score:
            continue
        candidates.append({
            "score_home": int(score.group(1)), "score_away": int(score.group(2)),
            "status": "inprogress" if "gyvai" in row["text"].lower() else "finished",
            "source": "LKL.lt", "source_game_id": row["id"],
            "source_date": start.date().isoformat(),
        })
    # Conflicting rows are safer to reject than to guess.
    return candidates[0] if candidates and all(c == candidates[0] for c in candidates) else None


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
            game["lkl_game_id"] = parsed["source_game_id"]
            game["lkl_game_date"] = parsed["source_date"]
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
            if not start_dt:
                continue
            domestic = "euro" not in str(game.get("league") or "").lower()
            if _status_finished(game.get("live_status")) and not domestic:
                continue
            if start_dt - PREGAME_WINDOW <= now <= start_dt + GAME_WINDOW:
                # Beta versions could persist scores from an unrelated row and
                # then stop polling forever after setting status=finished.
                if domestic and game.get("live_source") == "LKL.lt" and not game.get("lkl_game_id"):
                    for key in ("score_home", "score_away", "zalgiris_score", "opponent_score",
                                "live_status", "live_period", "live_clock", "live_source"):
                        game[key] = None
                    game["is_live"] = False
                relevant.append(game)

        if not relevant:
            self._lkl_live_repair = {"found": False, "reason": "no_relevant_game"}
            return 0

        updated = 0
        # Never overwrite a cached fixture's identity from an unrelated live row.
        euro_games = [g for g in relevant if "euro" in str(g.get("league") or "").lower()]
        domestic_games = [g for g in relevant if g not in euro_games]
        self._lkl_live_repair = {"mode": "date_and_ordered_teams"}

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

