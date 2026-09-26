from __future__ import annotations

from typing import Any, Dict

from homeassistant.util import dt as dt_util

from .beta7_coordinator import ZalgirisMatchesCoordinator as Beta7Coordinator

SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"


class ZalgirisMatchesCoordinator(Beta7Coordinator):
    """Beta coordinator with a one-time SofaScore live endpoint diagnostic."""

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._live_endpoint_tested = False
        self._live_endpoint_test: Dict[str, Any] = {}

    async def _run_live_endpoint_test(self) -> None:
        day = dt_util.now().date().isoformat()
        url = f"{SOFASCORE_BASE_URL}/sport/basketball/scheduled-events/{day}"

        payload = await self._fetch_json(url)
        ok = isinstance(payload, dict)
        events = payload.get("events", []) if ok else []

        self._live_endpoint_test = {
            "tested": True,
            "date": day,
            "ok": ok,
            "events_count": len(events) if isinstance(events, list) else 0,
        }
        self._live_endpoint_tested = True

    async def _async_update_data(self) -> Dict[str, Any]:
        data = await super()._async_update_data()

        if not self._live_endpoint_tested:
            try:
                await self._run_live_endpoint_test()
            except Exception as err:  # noqa: BLE001
                self._live_endpoint_test = {
                    "tested": True,
                    "ok": False,
                    "error": type(err).__name__,
                }
                self._live_endpoint_tested = True

        debug = data.setdefault("debug", {})
        debug["sofascore_live_endpoint_test"] = dict(self._live_endpoint_test)
        debug["sofascore_http"] = dict(getattr(self, "_sofascore_http", {}))
        return data
