from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlparse

import async_timeout

from .beta5_coordinator import ZalgirisMatchesCoordinator as Beta5Coordinator


class ZalgirisMatchesCoordinator(Beta5Coordinator):
    """Beta coordinator with SofaScore API host fallback and diagnostics."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._sofascore_http: Dict[str, Any] = {}

    async def _fetch_json(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch SofaScore JSON, trying both public API host variants."""
        candidates = []

        if "api.sofascore.com/api/v1" in url:
            candidates.append(url.replace("api.sofascore.com/api/v1", "www.sofascore.com/api/v1"))
            candidates.append(url)
        elif "www.sofascore.com/api/v1" in url:
            candidates.append(url)
            candidates.append(url.replace("www.sofascore.com/api/v1", "api.sofascore.com/api/v1"))
        else:
            candidates.append(url)

        # Preserve order while removing duplicates.
        candidates = list(dict.fromkeys(candidates))

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.sofascore.com/",
            "Origin": "https://www.sofascore.com",
        }

        for candidate in candidates:
            parsed = urlparse(candidate)
            debug_key = f"{parsed.netloc}{parsed.path}"
            try:
                async with async_timeout.timeout(12):
                    resp = await self.session.get(candidate, headers=headers, allow_redirects=True)
                    try:
                        self._sofascore_http[debug_key] = resp.status
                        if resp.status != 200:
                            continue

                        payload = await resp.json(content_type=None)
                        if isinstance(payload, dict):
                            self._sofascore_http[f"{debug_key}:json"] = "ok"
                            return payload

                        self._sofascore_http[f"{debug_key}:json"] = "not_dict"
                    finally:
                        resp.release()
            except Exception as err:  # noqa: BLE001
                self._sofascore_http[debug_key] = f"error:{type(err).__name__}"

        return None

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()
        data.setdefault("debug", {})["sofascore_http"] = dict(self._sofascore_http)
        return data
