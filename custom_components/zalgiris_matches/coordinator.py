from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    BASE_URL,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_STORE_DAYS,
    CONF_TEAM_PATH,
    DEFAULT_LIVE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STORE_DAYS,
    DEFAULT_TEAM_PATH,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"/rungtynes/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

# e.g. "PN, 01-30, 21:30" (Lithuanian weekday abbreviations)
START_RE = re.compile(r"([A-ZŠŽĮŪ]{1,3})\s*,\s*(\d{2})-(\d{2})\s*,\s*(\d{2}):(\d{2})")

KOOBIN_RE = re.compile(r"https?://zalgiris\.koobin\.com[^\s\"<>]+", re.IGNORECASE)

# HTML and escaped-JSON variants
IMG_SRC_ALT_RE1 = re.compile(r"<img[^>]+src=\"([^\"]+)\"[^>]+alt=\"([^\"]+)\"", re.IGNORECASE)
IMG_SRC_ALT_RE2 = re.compile(r"<img[^>]+alt=\"([^\"]+)\"[^>]+src=\"([^\"]+)\"", re.IGNORECASE)
IMG_ESC_RE = re.compile(r"\\\"src\\\":\\\"([^\\\"]+)\\\"[^}]+?\\\"alt\\\":\\\"([^\\\"]+)\\\"", re.IGNORECASE)

SCORE_RE = re.compile(r"tabular-nums[^>]*>\s*([^<]{1,3})\s*</p>", re.IGNORECASE)
SCORE_ESC_RE = re.compile(r"tabular-nums\\\",\\\"children\\\":\\\"([^\\\"]{1,3})", re.IGNORECASE)

TV_HTML_RE = re.compile(r"Transliacijos\s*</p>\s*<p[^>]*>([^<]{1,60})</p>", re.IGNORECASE)
TV_ESC_RE = re.compile(r"Transliacijos\\\",\\\"children\\\":\\\"([^\\\"]{1,60})", re.IGNORECASE)

# Common league names seen on the page (we pick the first match)
KNOWN_LEAGUES = [
    "Eurolyga",
    "Lietuvos Krepšinio Lyga",
    "Karaliaus Mindaugo Taurė",
    "KMT",
    "LKL",
]


def _now() -> dt_util.dt.datetime:
    return dt_util.now()


def _guess_start_dt(month: int, day: int, hour: int, minute: int) -> dt_util.dt.datetime:
    now = _now()
    dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    # If it looks like it's in the past by ~half a year, move to next year (season spans new year)
    if dt < (now - timedelta(days=180)):
        dt = dt.replace(year=now.year + 1)
    # If it looks too far in the future and month is much smaller (rare), move back a year
    if dt > (now + timedelta(days=330)) and month < now.month:
        dt = dt.replace(year=now.year - 1)
    return dt


def _first_match(pattern: re.Pattern[str], text: str) -> Optional[str]:
    m = pattern.search(text)
    if not m:
        return None
    return m.group(1).strip()


def _safe_unescape(s: str) -> str:
    # Unescape common HTML entities used in attributes
    return (
        s.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#x2F;", "/")
        .replace("&#47;", "/")
    )


def _parse_teams_and_logos(window: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    # Build (team -> logo) map with several patterns (HTML + escaped JSON)
    logos: Dict[str, str] = {}

    for src, alt in IMG_SRC_ALT_RE1.findall(window):
        logos.setdefault(alt.strip(), src.strip())
    for alt, src in IMG_SRC_ALT_RE2.findall(window):
        logos.setdefault(alt.strip(), src.strip())
    for src, alt in IMG_ESC_RE.findall(window):
        logos.setdefault(alt.strip(), src.strip())

    # Ordered team list by first occurrence of alt="..."
    teams: List[str] = []
    # HTML alts
    for m in re.finditer(r'alt=\"([^\"]{2,50})\"', window):
        t = m.group(1).strip()
        if t and t not in teams and t.lower() not in {"žalgiris team"}:
            teams.append(t)
        if len(teams) >= 4:
            break
    # Escaped JSON alts
    if len(teams) < 2:
        for m in re.finditer(r'\\\"alt\\\":\\\"([^\\\"]{2,50})\\\"', window):
            t = m.group(1).strip()
            if t and t not in teams and t.lower() not in {"žalgiris team"}:
                teams.append(t)
            if len(teams) >= 4:
                break

    # Keep only two main teams (usually includes Žalgiris + opponent)
    team1 = teams[0] if len(teams) >= 1 else None
    team2 = None
    for t in teams[1:]:
        if t != team1:
            team2 = t
            break

    home_logo = logos.get(team1) if team1 else None
    away_logo = logos.get(team2) if team2 else None
    return team1, team2, home_logo, away_logo


def _parse_scores(window: str) -> Tuple[Optional[int], Optional[int]]:
    raw: List[str] = []
    raw.extend([x.strip() for x in SCORE_RE.findall(window)])
    raw.extend([x.strip() for x in SCORE_ESC_RE.findall(window)])

    # Deduplicate while keeping order
    cleaned: List[str] = []
    for r in raw:
        if r not in cleaned:
            cleaned.append(r)

    nums: List[int] = []
    for r in cleaned:
        r2 = r.replace("\u00a0", " ").strip()
        if r2.isdigit():
            nums.append(int(r2))
        if len(nums) >= 2:
            break

    if len(nums) >= 2:
        return nums[0], nums[1]
    return None, None


def _parse_league(window: str) -> Optional[str]:
    for lg in KNOWN_LEAGUES:
        if lg in window:
            return lg
    # Fallback: first small header line (HTML)
    m = re.search(r'text-white/60 text-2xs truncate[^>]*>([^<]{3,60})</p>', window)
    if m:
        return m.group(1).strip()
    # Escaped JSON fallback is risky -> keep None
    return None


def _parse_start(window: str) -> Optional[dt_util.dt.datetime]:
    m = START_RE.search(window)
    if not m:
        # Sometimes weekday has weird nbsp char before it (like "\xa0T")
        m2 = re.search(r"\b(\d{2})-(\d{2})\s*,\s*(\d{2}):(\d{2})\b", window)
        if not m2:
            return None
        month, day, hh, mm = map(int, m2.groups())
        return _guess_start_dt(month, day, hh, mm)

    month = int(m.group(2))
    day = int(m.group(3))
    hh = int(m.group(4))
    mm = int(m.group(5))
    return _guess_start_dt(month, day, hh, mm)


def _parse_tv(window: str) -> Optional[str]:
    tv = _first_match(TV_HTML_RE, window)
    if tv:
        return tv
    tv = _first_match(TV_ESC_RE, window)
    return tv


def _parse_info_url(game_id: str, window: str) -> str:
    # Prefer an explicit href that includes extra params (like ?tab=media) if present.
    # We take the first href around the window that contains this game_id.
    m = re.search(r'href=\"([^\"]*/rungtynes/%s[^\"]*)\"' % re.escape(game_id), window)
    if m:
        return urljoin(BASE_URL, _safe_unescape(m.group(1)))
    m = re.search(r'\\\"href\\\":\\\"([^\\\"]*/rungtynes/%s[^\\\"]*)\\\"' % re.escape(game_id), window)
    if m:
        return urljoin(BASE_URL, _safe_unescape(m.group(1)))
    return urljoin(BASE_URL, f"/rungtynes/{game_id}")


def _parse_tickets_url(window: str) -> Optional[str]:
    # Pick the first koobin link in this match window
    m = KOOBIN_RE.search(window)
    if not m:
        return None
    return _safe_unescape(m.group(0))


def _parse_live_flag(window: str) -> bool:
    # The page can show LIVE/gyvai badge (varies). We keep it simple.
    w = window.lower()
    return ("live" in w) or ("gyvai" in w) or ("tiesiogiai" in w)


def _serialize_dt(dt: Optional[dt_util.dt.datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.isoformat()


class ZalgirisMatchesCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)

        self._etag: Dict[str, str] = {}
        self._last_modified: Dict[str, str] = {}
        self._last_text: Dict[str, str] = {}

        self._games: Dict[str, Dict[str, Any]] = {}  # by game_id
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._store_loaded = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._opt_scan_interval()),
        )

    def _opt_team_path(self) -> str:
        return (self.entry.options.get(CONF_TEAM_PATH) or self.entry.data.get(CONF_TEAM_PATH) or DEFAULT_TEAM_PATH).strip()

    def _opt_scan_interval(self) -> int:
        val = self.entry.options.get(CONF_SCAN_INTERVAL, self.entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        return int(val)

    def _opt_live_scan_interval(self) -> int:
        val = self.entry.options.get(CONF_LIVE_SCAN_INTERVAL, self.entry.data.get(CONF_LIVE_SCAN_INTERVAL, DEFAULT_LIVE_SCAN_INTERVAL))
        return int(val)

    def _opt_store_days(self) -> int:
        val = self.entry.options.get(CONF_STORE_DAYS, self.entry.data.get(CONF_STORE_DAYS, DEFAULT_STORE_DAYS))
        return int(val)

    async def async_load_store(self) -> None:
        if self._store_loaded:
            return
        self._store_loaded = True
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001
            data = None

        if not data:
            return

        games = data.get("games", {})
        if isinstance(games, dict):
            # Only keep dict-like games
            for gid, g in games.items():
                if isinstance(g, dict):
                    self._games[gid] = g

    async def _save_store(self) -> None:
        # Prune old items by store_days
        days = self._opt_store_days()
        cutoff = _now() - timedelta(days=days)

        pruned: Dict[str, Dict[str, Any]] = {}
        for gid, g in self._games.items():
            start_iso = g.get("start")
            start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
            if start_dt and start_dt < cutoff:
                continue
            pruned[gid] = g

        self._games = pruned
        await self._store.async_save(
            {
                "saved_at": _serialize_dt(_now()),
                "games": self._games,
            }
        )

    async def _fetch_text(self, url: str) -> str:
        headers = {"User-Agent": "HomeAssistant-ZalgirisMatches/2.0"}
        if url in self._etag:
            headers["If-None-Match"] = self._etag[url]
        if url in self._last_modified:
            headers["If-Modified-Since"] = self._last_modified[url]

        try:
            async with async_timeout.timeout(15):
                resp = await self.session.get(url, headers=headers, allow_redirects=True)
                if resp.status == 304 and url in self._last_text:
                    return self._last_text[url]
                resp.raise_for_status()
                text = await resp.text()

                etag = resp.headers.get("ETag")
                if etag:
                    self._etag[url] = etag
                lm = resp.headers.get("Last-Modified")
                if lm:
                    self._last_modified[url] = lm

                self._last_text[url] = text
                return text
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Fetch failed ({url}): {err}") from err

    def _parse_schedule(self, html: str) -> Tuple[List[str], Dict[str, Any]]:
        game_ids = []
        for gid in UUID_RE.findall(html):
            if gid not in game_ids:
                game_ids.append(gid)

        debug = {
            "parse_mode": "href",
            "links_found": len(UUID_RE.findall(html)),
            "matches_found": len(game_ids),
            "has_rungtynes": "/rungtynes" in html,
            "has_uuid": bool(game_ids),
            "html_head": html[:160].replace("\n", " "),
        }
        return game_ids, debug

    def _extract_match_window(self, html: str, game_id: str, size: int = 6000) -> str:
        # Find the first occurrence of this id inside a /rungtynes/... link
        m = re.search(r"/rungtynes/%s" % re.escape(game_id), html, re.IGNORECASE)
        idx = m.start() if m else html.find(game_id)
        if idx < 0:
            idx = 0
        start = max(0, idx - size // 2)
        end = min(len(html), idx + size // 2)
        return html[start:end]

    def _parse_match_from_window(self, game_id: str, window: str) -> Dict[str, Any]:
        start_dt = _parse_start(window)
        team1, team2, logo1, logo2 = _parse_teams_and_logos(window)
        s1, s2 = _parse_scores(window)

        return {
            "game_id": game_id,
            "start": _serialize_dt(start_dt),
            "league": _parse_league(window),
            "home": team1,
            "away": team2,
            "home_logo": logo1,
            "away_logo": logo2,
            "tv": _parse_tv(window),
            "arena": None,  # usually not present in schedule; can be filled from match page later
            "score_home": s1,
            "score_away": s2,
            "info_url": _parse_info_url(game_id, window),
            "tickets_url": _parse_tickets_url(window),
            "is_live": _parse_live_flag(window),
        }

    async def _maybe_fetch_match_details(self, game: Dict[str, Any]) -> None:
        # Optional: For live or recently-started games, the match page often has better data (score, arena, etc.)
        url = game.get("info_url")
        if not url:
            return

        html = await self._fetch_text(url)
        # Re-use same parsing rules on the match page
        window = html[:12000]

        # Update only missing / important fields
        parsed = self._parse_match_from_window(game["game_id"], window)

        for k in ["home", "away", "home_logo", "away_logo", "tv", "arena", "score_home", "score_away"]:
            if parsed.get(k) is None:
                continue
            if game.get(k) in (None, "", "—", "-"):
                game[k] = parsed[k]
            # Always refresh scores during live
            if k in ("score_home", "score_away") and parsed.get(k) is not None:
                game[k] = parsed[k]

        # live flag can change
        game["is_live"] = bool(parsed.get("is_live")) or game.get("is_live", False)

    def _classify(self) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        now = _now()
        upcoming: List[Dict[str, Any]] = []
        finished: List[Dict[str, Any]] = []
        live: Optional[Dict[str, Any]] = None

        for g in self._games.values():
            start_iso = g.get("start")
            start_dt = dt_util.parse_datetime(start_iso) if isinstance(start_iso, str) else None
            if not start_dt:
                continue

            is_live = bool(g.get("is_live", False))
            has_score = (g.get("score_home") is not None) and (g.get("score_away") is not None)

            if is_live:
                live = g
                continue

            if start_dt > now:
                upcoming.append(g)
            else:
                # Past: keep if we have a score (or it was within last 6h so it might still be relevant)
                if has_score or (start_dt > now - timedelta(hours=6)):
                    finished.append(g)

        upcoming.sort(key=lambda x: x.get("start") or "")
        finished.sort(key=lambda x: x.get("start") or "", reverse=True)
        return live, upcoming, finished

    async def _async_update_data(self) -> Dict[str, Any]:
        # Update intervals (options can change live)
        self.update_interval = timedelta(seconds=self._opt_scan_interval())

        team_path = self._opt_team_path()
        if not team_path.startswith("/"):
            team_path = "/" + team_path

        schedule_url = urljoin(BASE_URL, team_path)

        html = await self._fetch_text(schedule_url)
        game_ids, debug = self._parse_schedule(html)

        # Parse schedule matches
        for gid in game_ids:
            window = self._extract_match_window(html, gid)
            parsed = self._parse_match_from_window(gid, window)

            # Merge into cache
            existing = self._games.get(gid, {})
            merged = {**existing, **{k: v for k, v in parsed.items() if v is not None}}
            # Keep scores if we already have them and schedule returns "-"
            if existing.get("score_home") is not None and parsed.get("score_home") is None:
                merged["score_home"] = existing["score_home"]
            if existing.get("score_away") is not None and parsed.get("score_away") is None:
                merged["score_away"] = existing["score_away"]
            # Preserve arena if already known
            if existing.get("arena") and not parsed.get("arena"):
                merged["arena"] = existing["arena"]

            self._games[gid] = merged

        live, upcoming, finished = self._classify()

        # If we have a live game or a just-started game, poll its match page more often
        detail_tasks = []
        live_interval = self._opt_live_scan_interval()

        if live:
            # Reduce to live interval; coordinator will still be triggered by HA, but we can refresh via sensor
            self.update_interval = timedelta(seconds=live_interval)
            detail_tasks.append(self._maybe_fetch_match_details(live))
        else:
            # Try to finalize score for the most recent started game (last 24h) if score missing
            now = _now()
            candidates = []
            for g in finished[:3]:
                start_dt = dt_util.parse_datetime(g.get("start")) if g.get("start") else None
                if start_dt and start_dt > now - timedelta(hours=24):
                    if g.get("score_home") is None or g.get("score_away") is None:
                        candidates.append(g)
            for g in candidates[:2]:
                detail_tasks.append(self._maybe_fetch_match_details(g))

        if detail_tasks:
            try:
                await asyncio.gather(*detail_tasks)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Match details update failed: %s", err)

            # Re-classify after details update
            live, upcoming, finished = self._classify()

        # Save store occasionally (not every tick)
        try:
            await self._save_store()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Store save failed: %s", err)

        # Build "last finished with score"
        last_with_score = next((g for g in finished if g.get("score_home") is not None and g.get("score_away") is not None), None)

        return {
            "team_path": team_path,
            "source_url": schedule_url,
            "fetched_at": _serialize_dt(_now()),
            "live": live,
            "upcoming": upcoming,
            "finished": finished,
            "last_finished_with_score": last_with_score,
            "debug": debug,
        }
