from __future__ import annotations

from typing import Any, Dict

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .beta7_coordinator import _parse_lkl_standing
from .beta9_coordinator import ZalgirisMatchesCoordinator as Beta9Coordinator

LKL_PRIMARY_URL = "https://lkl.lt/"
LKL_FALLBACK_URL = "https://www.lkl.lt/"
STANDINGS_CACHE_VERSION = 1


class ZalgirisMatchesCoordinator(Beta9Coordinator):
    """Beta coordinator with persistent last-known-good standings."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._standings_cache_store = Store(
            hass,
            STANDINGS_CACHE_VERSION,
            f"zalgiris_matches_standings_{entry.entry_id}",
        )
        self._standings_cache_loaded = False
        self._standings_cache: Dict[str, Dict[str, Any]] = {}
        self._standings_cache_used: Dict[str, bool] = {}

    async def _async_load_standings_cache(self) -> None:
        if self._standings_cache_loaded:
            return

        stored = await self._standings_cache_store.async_load()
        if isinstance(stored, dict):
            for key, value in stored.items():
                if isinstance(key, str) and isinstance(value, dict):
                    self._standings_cache[key] = dict(value)

        # Make cached values available immediately. A successful refresh below
        # will replace them with fresh data.
        for key, value in self._standings_cache.items():
            self._standings.setdefault(key, dict(value))

        self._standings_cache_loaded = True

    async def _official_lkl_standing(self) -> Dict[str, Any]:
        """Fetch LKL standings, trying both official hostname variants."""
        for debug_key, url in (
            ("lkl", LKL_PRIMARY_URL),
            ("lkl_www", LKL_FALLBACK_URL),
        ):
            raw = await self._fetch_text_official(debug_key, url)
            if not raw:
                continue

            parsed = _parse_lkl_standing(raw)
            if parsed:
                parsed["season"] = "2026/27"
                parsed["source_url"] = url
                return parsed

        return {
            "stage": "Duomenų nėra",
            "tournament": "LKL",
            "status": "unavailable",
            "season": "2026/27",
            "source": "LKL.lt",
        }

    def _fresh_or_cached(self, key: str, fresh: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        """Keep the last good value when a source temporarily fails."""
        if fresh.get("status") != "unavailable":
            clean = dict(fresh)
            clean.pop("stale", None)
            clean.pop("refresh_error", None)
            clean.pop("last_refresh_attempt", None)
            self._standings_cache[key] = dict(clean)
            self._standings_cache_used[key] = False
            return clean, True

        cached = self._standings_cache.get(key)
        if cached:
            stale = dict(cached)
            stale["stale"] = True
            stale["refresh_error"] = fresh.get("stage") or "Duomenų šaltinis nepasiekiamas"
            stale["last_refresh_attempt"] = dt_util.now().isoformat()
            self._standings_cache_used[key] = True
            return stale, False

        self._standings_cache_used[key] = False
        return fresh, False

    async def _refresh_standings(self) -> int:
        """Refresh standings while preserving last-known-good data."""
        await self._async_load_standings_cache()

        fresh_lkl = await self._official_lkl_standing()
        fresh_euroleague = await self._official_euroleague_standing()
        fresh_kmt = await self._official_kmt_standing()

        lkl, lkl_fresh = self._fresh_or_cached("lkl", fresh_lkl)
        euroleague, euro_fresh = self._fresh_or_cached("euroleague", fresh_euroleague)
        kmt, kmt_fresh = self._fresh_or_cached("kmt", fresh_kmt)

        self._standings["lkl"] = lkl
        self._standings["euroleague"] = euroleague
        self._standings["kmt"] = kmt
        self._last_standings_refresh = dt_util.now()

        # Persist only last-known-good values; stale/error metadata is runtime-only.
        await self._standings_cache_store.async_save(dict(self._standings_cache))

        return sum((lkl_fresh, euro_fresh, kmt_fresh))

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        debug = data.setdefault("debug", {})
        debug["standings_cache_used"] = dict(self._standings_cache_used)
        debug["standings_cache_entries"] = sorted(self._standings_cache.keys())
        return data
