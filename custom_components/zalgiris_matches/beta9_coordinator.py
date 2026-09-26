from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

import async_timeout

from homeassistant.util import dt as dt_util

from .beta7_coordinator import ZalgirisMatchesCoordinator as Beta7Coordinator, _strip_html

LKL_TV_URL = "https://lkl.lt/tv"
EUROLEAGUE_SEASON = "E2026"
EUROLEAGUE_GAMES_URL = (
    f"https://api-live.euroleague.net/v2/competitions/E/seasons/{EUROLEAGUE_SEASON}/games"
)
EUROLEAGUE_PBP_URL = "https://live.euroleague.net/api/PlayByPlay"

PREGAME_WINDOW = timedelta(minutes=30)
GAME_WINDOW = timedelta(hours=4)
FINISHED_STATUSES = {"finished", "ended", "canceled", "cancelled", "postponed"}


def _status_finished(value: Any) -> bool:
    return str(value or "").strip().lower() in FINISHED_STATUSES


def _is_zalgiris(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return "zalgiris" in text or "žalgiris" in text or text == "zal"


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if match:
            return int(match.group(0))
    return None


def _recursive_value(node: Any, wanted_key: str) -> Any:
    wanted = wanted_key.lower()
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() == wanted:
                return value
        for value in node.values():
            found = _recursive_value(value, wanted_key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _recursive_value(value, wanted_key)
            if found is not None:
                return found
    return None


def _team_pattern(name: str) -> str:
    if name.strip().lower() == "nevėžis":
        return r"Nevėžis(?:-Paskolų\s+klubas)?"
    return re.escape(name.strip())


def _parse_lkl_score(raw_html: str, game: Dict[str, Any], now) -> Optional[Dict[str, Any]]:
    """Find the relevant Žalgiris score on the official LKL TV page."""
    home = str(game.get("home") or "").strip()
    away = str(game.get("away") or "").strip()
    if not home or not away:
        return None

    start_raw = game.get("start")
    start_dt = dt_util.parse_datetime(start_raw) if isinstance(start_raw, str) else None
    if start_dt and now < start_dt:
        # Avoid accidentally picking an older result between the same teams.
        return None

    text = _strip_html(raw_html)
    pattern = re.compile(
        rf"{_team_pattern(home)}\s*-\s*{_team_pattern(away)}\s*\.?\s*(\d{{1,3}})\s*:\s*(\d{{1,3}})",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None

    match = matches[-1]
    home_score = int(match.group(1))
    away_score = int(match.group(2))
    context = text[max(0, match.start() - 140) : match.start()].lower()
    finished = "rungtynės baigėsi" in context or "pasibaigė" in context

    return {
        "score_home": home_score,
        "score_away": away_score,
        "status": "finished" if finished else "inprogress",
        "source": "LKL.lt",
    }


def _latest_euroleague_score(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract score, period and clock from EuroLeague play-by-play JSON."""
    period_keys = [
        ("FirstQuarter", "Q1"),
        ("SecondQuarter", "Q2"),
        ("ThirdQuarter", "Q3"),
        ("ForthQuarter", "Q4"),
        ("ExtraTime", "OT"),
    ]

    all_events: List[Dict[str, Any]] = []
    period: Optional[str] = None
    for key, label in period_keys:
        events = payload.get(key)
        if isinstance(events, list) and events:
            period = label
            all_events.extend(event for event in events if isinstance(event, dict))

    scored: List[tuple[int, Dict[str, Any], int, int]] = []
    for event in all_events:
        score_a = _to_int(event.get("POINTS_A"))
        score_b = _to_int(event.get("POINTS_B"))
        if score_a is None or score_b is None:
            continue
        sequence = _to_int(event.get("NUMBEROFPLAY")) or 0
        scored.append((sequence, event, score_a, score_b))

    if not scored:
        return None

    _, event, score_a, score_b = max(scored, key=lambda item: item[0])
    clock = str(event.get("MARKERTIME") or "").strip() or None
    live = bool(payload.get("Live"))

    return {
        "score_a": score_a,
        "score_b": score_b,
        "status": "inprogress" if live else "finished",
        "period": period,
        "clock": clock,
        "team_a": payload.get("TeamA"),
        "team_b": payload.get("TeamB"),
        "code_a": payload.get("CodeTeamA"),
        "code_b": payload.get("CodeTeamB"),
        "source": "EuroLeague",
    }


class ZalgirisMatchesCoordinator(Beta7Coordinator):
    """Beta coordinator using official competition sources for live scores."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._official_live_http: Dict[str, Any] = {}
        self._euro_gamecodes: Dict[str, int] = {}

    async def _fetch_live_text(self, key: str, url: str) -> Optional[str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
            "Accept-Language": "lt-LT,lt;q=0.9,en;q=0.8",
        }
        try:
            async with async_timeout.timeout(12):
                resp = await self.session.get(url, headers=headers, allow_redirects=True)
                try:
                    self._official_live_http[key] = resp.status
                    if resp.status != 200:
                        return None
                    return await resp.text()
                finally:
                    resp.release()
        except Exception as err:  # noqa: BLE001
            self._official_live_http[key] = f"error:{type(err).__name__}"
            return None

    async def _fetch_live_json(self, key: str, url: str) -> Optional[Dict[str, Any]]:
        raw = await self._fetch_live_text(key, url)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            self._official_live_http[f"{key}:json"] = "invalid"
            return None
        if not isinstance(payload, dict):
            self._official_live_http[f"{key}:json"] = "not_dict"
            return None
        self._official_live_http[f"{key}:json"] = "ok"
        return payload

    async def _euroleague_gamecode(self, game: Dict[str, Any]) -> Optional[int]:
        game_id = str(game.get("game_id") or game.get("start") or "")
        if game_id in self._euro_gamecodes:
            return self._euro_gamecodes[game_id]

        payload = await self._fetch_live_json("euroleague_games", EUROLEAGUE_GAMES_URL)
        if not payload:
            return None

        items = payload.get("data")
        if not isinstance(items, list):
            return None

        start_raw = game.get("start")
        start_dt = dt_util.parse_datetime(start_raw) if isinstance(start_raw, str) else None
        date_text = start_dt.date().isoformat() if start_dt else ""
        opponent = str(game.get("away") if _is_zalgiris(game.get("home")) else game.get("home") or "").strip()
        opponent_token = opponent.lower().split()[0] if opponent else ""

        candidates = []
        for item in items:
            if not isinstance(item, dict):
                continue
            blob = json.dumps(item, ensure_ascii=False).lower()
            if "zalgiris" not in blob and "žalgiris" not in blob:
                continue
            if opponent_token and opponent_token not in blob:
                continue
            candidates.append((item, blob))

        if date_text:
            dated = [(item, blob) for item, blob in candidates if date_text in blob]
            if dated:
                candidates = dated

        if not candidates:
            return None

        item = candidates[0][0]
        code = _to_int(item.get("gameCode"))
        if code is None:
            code = _to_int(_recursive_value(item, "gameCode"))
        if code is None:
            return None

        self._euro_gamecodes[game_id] = code
        return code

    def _apply_scores(
        self,
        game: Dict[str, Any],
        home_score: int,
        away_score: int,
        *,
        status: str,
        source: str,
        period: Optional[str] = None,
        clock: Optional[str] = None,
    ) -> None:
        game["score_home"] = home_score
        game["score_away"] = away_score
        game["live_source"] = source
        game["live_status"] = status
        game["live_period"] = period
        game["live_clock"] = clock

        if _is_zalgiris(game.get("home")):
            game["zalgiris_score"] = home_score
            game["opponent_score"] = away_score
            game["opponent"] = game.get("away")
        else:
            game["zalgiris_score"] = away_score
            game["opponent_score"] = home_score
            game["opponent"] = game.get("home")

    async def _update_lkl_games(self, games: List[Dict[str, Any]], now) -> int:
        if not games:
            return 0
        raw_html = await self._fetch_live_text("lkl_live", LKL_TV_URL)
        if not raw_html:
            return 0

        updated = 0
        for game in games:
            parsed = _parse_lkl_score(raw_html, game, now)
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

    async def _update_euroleague_game(self, game: Dict[str, Any]) -> int:
        gamecode = await self._euroleague_gamecode(game)
        if gamecode is None:
            return 0

        url = f"{EUROLEAGUE_PBP_URL}?gamecode={gamecode}&seasoncode={EUROLEAGUE_SEASON}"
        payload = await self._fetch_live_json("euroleague_pbp", url)
        if not payload:
            return 0

        parsed = _latest_euroleague_score(payload)
        if not parsed:
            return 0

        score_a = parsed["score_a"]
        score_b = parsed["score_b"]
        a_is_zalgiris = _is_zalgiris(parsed.get("code_a")) or _is_zalgiris(parsed.get("team_a"))
        b_is_zalgiris = _is_zalgiris(parsed.get("code_b")) or _is_zalgiris(parsed.get("team_b"))

        # EuroLeague TeamA is the local/home side. Keep a conservative fallback
        # to the zalgiris.lt home/away assignment if team codes are absent.
        if a_is_zalgiris or b_is_zalgiris:
            home_score, away_score = score_a, score_b
        else:
            home_score, away_score = score_a, score_b

        self._apply_scores(
            game,
            home_score,
            away_score,
            status=parsed["status"],
            source="EuroLeague",
            period=parsed.get("period"),
            clock=parsed.get("clock"),
        )
        game["euroleague_gamecode"] = gamecode
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
            return 0

        euro_games = [game for game in relevant if "euro" in str(game.get("league") or "").lower()]
        domestic_games = [game for game in relevant if game not in euro_games]

        updated = await self._update_lkl_games(domestic_games, now)
        for game in euro_games:
            updated += await self._update_euroleague_game(game)

        return updated

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        debug = data.setdefault("debug", {})
        updated = debug.pop("sofascore_matches_updated", 0)
        debug["official_live_updated"] = updated
        debug["official_live_http"] = dict(self._official_live_http)
        debug["live_source_mode"] = "official"
        return data
