from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import async_timeout

from homeassistant.util import dt as dt_util

from .beta6_coordinator import ZalgirisMatchesCoordinator as Beta6Coordinator

LKL_URL = "https://lkl.lt/"
EUROLEAGUE_V1_STANDINGS = "https://api-live.euroleague.net/v1/standings?seasoncode=E2026"


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_lkl_standing(raw_html: str) -> Optional[Dict[str, Any]]:
    """Parse Žalgiris row from the official LKL standings table."""
    text = _strip_html(raw_html)
    matches = re.findall(
        r"(?:^|\s)(\d{1,2})\s+Žalgiris\s+(\d+)\s+(\d+)\s+(\d+)(?=\s|$)",
        text,
        flags=re.IGNORECASE,
    )

    candidates: List[Dict[str, int]] = []
    for position_s, wins_s, losses_s, games_s in matches:
        position = int(position_s)
        wins = int(wins_s)
        losses = int(losses_s)
        games = int(games_s)
        if 1 <= position <= 20 and wins + losses == games:
            candidates.append(
                {
                    "position": position,
                    "wins": wins,
                    "losses": losses,
                    "matches": games,
                }
            )

    if not candidates:
        return None

    # The page can contain the same current table more than once; pick the
    # candidate with the largest number of played games and then best position.
    best = sorted(candidates, key=lambda x: (-x["matches"], x["position"]))[0]
    return {
        **best,
        "team": "Žalgiris",
        "tournament": "LKL",
        "status": "ok",
        "source": "LKL.lt",
        "source_url": LKL_URL,
        "updated_at": dt_util.now().isoformat(),
    }


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_number(values: Dict[str, str], keys: tuple[str, ...]) -> Optional[int]:
    for key, value in values.items():
        if any(token in key for token in keys):
            match = re.search(r"-?\d+", value or "")
            if match:
                return int(match.group(0))
    return None


def _parse_euroleague_xml(raw_xml: str) -> Optional[Dict[str, Any]]:
    """Best-effort parser for the official EuroLeague v1 standings XML."""
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return None

    for elem in root.iter():
        texts = [text.strip() for text in elem.itertext() if text and text.strip()]
        joined = " ".join(texts)
        if not re.search(r"\bzalgiris\b|\bžalgiris\b", joined, re.IGNORECASE):
            continue

        values: Dict[str, str] = {}
        for child in elem.iter():
            if child is elem:
                continue
            text = (child.text or "").strip()
            if text:
                values[_local_tag(child.tag)] = text

        position = _first_number(values, ("position", "rank", "pos"))
        if position is None or not 1 <= position <= 30:
            continue

        result: Dict[str, Any] = {
            "position": position,
            "team": "Žalgiris",
            "tournament": "Eurolyga",
            "status": "ok",
            "source": "EuroLeague official API",
            "source_url": EUROLEAGUE_V1_STANDINGS,
            "updated_at": dt_util.now().isoformat(),
        }
        wins = _first_number(values, ("won", "wins", "win"))
        losses = _first_number(values, ("lost", "losses", "loss"))
        games = _first_number(values, ("played", "games", "gp"))
        if wins is not None:
            result["wins"] = wins
        if losses is not None:
            result["losses"] = losses
        if games is not None:
            result["matches"] = games
        elif wins is not None and losses is not None:
            result["matches"] = wins + losses
        return result

    return None


class ZalgirisMatchesCoordinator(Beta6Coordinator):
    """Beta coordinator using official sources for standings."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._official_standings_http: Dict[str, Any] = {}

    async def _fetch_text_official(self, key: str, url: str) -> Optional[str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "lt-LT,lt;q=0.9,en;q=0.8",
        }
        try:
            async with async_timeout.timeout(12):
                resp = await self.session.get(url, headers=headers, allow_redirects=True)
                try:
                    self._official_standings_http[key] = resp.status
                    if resp.status != 200:
                        return None
                    return await resp.text()
                finally:
                    resp.release()
        except Exception as err:  # noqa: BLE001
            self._official_standings_http[key] = f"error:{type(err).__name__}"
            return None

    def _has_started_euroleague(self) -> bool:
        now = dt_util.now()
        euro_games = []
        for game in self._games.values():
            league = str(game.get("league") or "").lower()
            if "euro" not in league:
                continue
            start = game.get("start")
            start_dt = dt_util.parse_datetime(start) if isinstance(start, str) else None
            if start_dt:
                euro_games.append(start_dt)
        return bool(euro_games and min(euro_games) <= now)

    def _has_kmt_game(self) -> bool:
        for game in self._games.values():
            league = str(game.get("league") or "").lower()
            if "kmt" in league or "mindaugo" in league:
                return True
        return False

    async def _official_euroleague_standing(self) -> Dict[str, Any]:
        if not self._has_started_euroleague():
            return {
                "stage": "Neprasidėjo",
                "tournament": "Eurolyga",
                "status": "not_started",
                "season": "2026/27",
                "source": "EuroLeague",
            }

        raw = await self._fetch_text_official("euroleague", EUROLEAGUE_V1_STANDINGS)
        if raw:
            parsed = _parse_euroleague_xml(raw)
            if parsed:
                parsed["season"] = "2026/27"
                return parsed

        return {
            "stage": "Duomenų nėra",
            "tournament": "Eurolyga",
            "status": "unavailable",
            "season": "2026/27",
            "source": "EuroLeague",
        }

    async def _official_lkl_standing(self) -> Dict[str, Any]:
        raw = await self._fetch_text_official("lkl", LKL_URL)
        if raw:
            parsed = _parse_lkl_standing(raw)
            if parsed:
                parsed["season"] = "2026/27"
                return parsed

        return {
            "stage": "Duomenų nėra",
            "tournament": "LKL",
            "status": "unavailable",
            "season": "2026/27",
            "source": "LKL.lt",
        }

    async def _official_kmt_standing(self) -> Dict[str, Any]:
        if not self._has_kmt_game():
            return {
                "stage": "Neprasidėjo",
                "tournament": "KMT",
                "status": "not_started",
                "season": "2026/27",
                "source": "LKL.lt",
            }

        # KMT is a knockout cup, so a numerical league position is not always
        # meaningful. Until a reliable stage endpoint is added, expose the stage.
        return {
            "stage": "Vyksta",
            "tournament": "KMT",
            "status": "in_progress",
            "season": "2026/27",
            "source": "LKL.lt",
        }

    async def _refresh_standings(self) -> int:
        """Refresh standings without SofaScore, which may return HTTP 403."""
        lkl = await self._official_lkl_standing()
        euroleague = await self._official_euroleague_standing()
        kmt = await self._official_kmt_standing()

        self._standings["lkl"] = lkl
        self._standings["euroleague"] = euroleague
        self._standings["kmt"] = kmt
        self._last_standings_refresh = dt_util.now()

        return sum(1 for item in (lkl, euroleague, kmt) if item.get("status") != "unavailable")

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        data.setdefault("debug", {})["official_standings_http"] = dict(self._official_standings_http)
        data["debug"]["standings_source"] = "official"
        return data
