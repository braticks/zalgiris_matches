"""Polling policy independent of Home Assistant and network transport."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
import time


def next_interval(games, scan_interval, now=None, jitter=None):
    """Two hours idle; configured interval near games; 60–120s in game window."""
    now = time.time() if now is None else now
    jitter = random.uniform(0, 0.1) if jitter is None else jitter
    starts = []
    for game in games:
        try:
            start = datetime.fromisoformat(game.get("start") or "")
            if start.tzinfo is not None:
                starts.append(start.timestamp())
        except (TypeError, ValueError):
            continue
    configured = max(60, min(3600, int(scan_interval)))
    active = any(-4 * 3600 < start - now <= 900 for start in starts)
    near = any(0 < start - now <= 6 * 3600 for start in starts)
    base = min(configured, 120) if active else configured if near else 7200
    interval = base * (1 + jitter)
    # Wake at the fast-window boundary instead of sleeping through kickoff.
    boundaries = [start - now - 900 for start in starts if start - now > 900]
    if boundaries:
        interval = min(interval, min(boundaries))
    return max(60, interval)


class PollingGate:
    """Shared across coordinator reloads during this HA process lifetime."""
    def __init__(self):
        self.until = 0.0
        self.failures = 0

    def remaining(self, now=None):
        return max(0, self.until - (time.time() if now is None else now))

    def failed(self, retry_after=None, status=None, now=None, jitter=None):
        now = time.time() if now is None else now
        jitter = random.uniform(0, 0.1) if jitter is None else jitter
        self.failures = min(self.failures + 1, 8)
        delay = min(21600, 300 * 2 ** (self.failures - 1))
        if status == 403:
            delay = max(delay, 3600)
        server_delay = 0
        if retry_after:
            try:
                server_delay = max(0, int(retry_after))
            except (TypeError, ValueError):
                try:
                    date = parsedate_to_datetime(retry_after)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    server_delay = max(0, date.timestamp() - now)
                except (TypeError, ValueError, OverflowError):
                    pass
        # Never shorten a server deadline, even when it exceeds our own cap.
        self.until = max(self.until, now + max(delay, server_delay) * (1 + jitter))

    def succeeded(self):
        self.failures = 0
        self.until = 0.0
