from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

from .beta11_coordinator import ZalgirisMatchesCoordinator as Beta11Coordinator
from .beta7_coordinator import _strip_html

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
    # Longer aliases first to avoid short-code partials where possible.
    aliases = sorted({a for a in aliases if a}, key=len, reverse=True)
    return "(?:" + "|".join(re.escape(a) for a in aliases) + ")"


def _parse_lkl_homepage_score(raw_html: str, game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse the current Žalgiris game from the official LKL homepage scoreboard."""
    home = str(game.get("home") or "").strip()
    away = str(game.get("away") or "").strip()
    if not home or not away:
        return None

    text = _strip_html(raw_html)
    home_pat = _alias_pattern(home)
    away_pat = _alias_pattern(away)

    # Homepage live block is effectively: ŽAL 43 - 37 GYVAI ● ŠIA.
    # Allow small amounts of markup-derived text between fields.
    pattern = re.compile(
        rf"{home_pat}.{{0,100}}?(\d{{1,3}})\s*-\s*(\d{{1,3}})(.{{0,100}}?){away_pat}",
        re.IGNORECASE,
    )

    candidates = list(pattern.finditer(text))
    if not candidates:
        return None

    # Prefer the block explicitly marked live; otherwise use the first matching
    # current home/away pair (useful immediately after final buzzer).
    match = next((m for m in candidates if "gyvai" in m.group(3).lower()), candidates[0])
    home_score = int(match.group(1))
    away_score = int(match.group(2))
    between = match.group(3).lower()

    return {
        "score_home": home_score,
        "score_away": away_score,
        "status": "inprogress" if "gyvai" in between else "finished",
        "source": "LKL.lt",
    }


class ZalgirisMatchesCoordinator(Beta11Coordinator):
    """Beta coordinator with corrected LKL live source and team validation."""

    def _parse_match_from_window(self, game_id: str, window: str) -> Dict[str, Any]:
        parsed = super()._parse_match_from_window(game_id, window)

        # zalgiris.lt sometimes changes the card HTML while a game is live.
        # The legacy parser can then pick footer/app image alt texts (Google
        # Play/App Store) as team names. Never overwrite a known game with a
        # pair that does not actually contain Žalgiris.
        if not _valid_team_pair(parsed.get("home"), parsed.get("away")):
            parsed["home"] = None
            parsed["away"] = None
            parsed["home_logo"] = None
            parsed["away_logo"] = None

        return parsed

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
            updated += 1

        return updated

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        debug = data.setdefault("debug", {})
        debug["lkl_live_source"] = LKL_LIVE_URL
        debug["team_validation"] = True
        return data
