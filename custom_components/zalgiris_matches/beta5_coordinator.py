from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, Optional

import async_timeout

from homeassistant.util import dt as dt_util

from .beta_coordinator import ZalgirisMatchesCoordinator as BetaCoordinator
from .standings import TOURNAMENTS

SOFASCORE_PUBLIC_PAGES = {
    "euroleague": "https://www.sofascore.com/basketball/tournament/international/euroleague/138",
    "lkl": "https://www.sofascore.com/basketball/tournament/lithuania/betsafe-lkl/975",
    "kmt": "https://www.sofascore.com/basketball/tournament/lithuania/king-mindaugas-cup/11012",
}


def _expected_season(now) -> str:
    start_year = now.year if now.month >= 7 else now.year - 1
    return f"{start_year % 100:02d}/{(start_year + 1) % 100:02d}"


def _page_text(raw_html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_public_standing(raw_html: str, expected_season: str) -> Optional[Dict[str, Any]]:
    text = _page_text(raw_html)
    if expected_season not in text:
        return {
            "status": "not_started",
            "stage": "Neprasidėjo",
            "season": expected_season,
            "source": "SofaScore public page",
        }

    # Public standings text is rendered as e.g. "7 Žalgiris 1-0 1.000 W1".
    match = re.search(
        r"(?:^|\s)(\d{1,2})\s+(?:Kauno\s+)?Žalgiris\s+(\d+)\s*-\s*(\d+)(?:\s+([01](?:\.\d{3})?))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    wins = int(match.group(2))
    losses = int(match.group(3))
    result: Dict[str, Any] = {
        "position": int(match.group(1)),
        "team": "Žalgiris",
        "matches": wins + losses,
        "wins": wins,
        "losses": losses,
        "season": expected_season,
        "source": "SofaScore public page",
        "status": "ok",
        "updated_at": dt_util.now().isoformat(),
    }
    if match.group(4):
        result["percentage"] = float(match.group(4))
    return result


class ZalgirisMatchesCoordinator(BetaCoordinator):
    """Beta coordinator with a fallback to SofaScore public standings pages."""

    async def _fetch_public_page(self, url: str) -> Optional[str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            async with async_timeout.timeout(12):
                resp = await self.session.get(url, headers=headers, allow_redirects=True)
                try:
                    if resp.status != 200:
                        return None
                    return await resp.text()
                finally:
                    resp.release()
        except Exception:  # noqa: BLE001
            return None

    async def _fetch_tournament_standing(self, key: str, tournament_id: int) -> Optional[Dict[str, Any]]:
        # Prefer the JSON API used by beta.4.
        standing = await super()._fetch_tournament_standing(key, tournament_id)
        if standing:
            return standing

        # Fallback to the public server-rendered tournament page.
        url = SOFASCORE_PUBLIC_PAGES.get(key)
        if not url:
            return None
        raw_html = await self._fetch_public_page(url)
        if not raw_html:
            return None

        standing = _parse_public_standing(raw_html, _expected_season(dt_util.now()))
        if not standing:
            return None

        standing["tournament"] = TOURNAMENTS[key]["name"]
        standing["tournament_id"] = tournament_id
        standing["public_url"] = url
        return standing
