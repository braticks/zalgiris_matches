from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

from .beta11_coordinator import ZalgirisMatchesCoordinator as Beta11Coordinator
from .beta7_coordinator import _strip_html
from .beta9_coordinator import GAME_WINDOW, PREGAME_WINDOW, _status_finished

LKL_LIVE_URL = "https://lkl.lt/"

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


class ZalgirisMatchesCoordinator(Beta11Coordinator):
    """Beta coordinator with corrected LKL live source and team validation."""

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
        return data
