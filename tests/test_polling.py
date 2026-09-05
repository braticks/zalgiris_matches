"""Clock-based policy and coordinator HTTP cooldown regression tests."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/zalgiris_matches'
policy = runpy.run_path(str(ROOT / 'polling.py'))
Gate = policy['PollingGate']
interval = policy['next_interval']
NOW = 1800000000


def game(offset):
    return {'start': datetime.fromtimestamp(NOW + offset, timezone.utc).isoformat()}


class PollingTests(unittest.TestCase):
    def test_idle_and_near(self):
        self.assertEqual(interval([], 600, NOW, 0), 7200)
        self.assertEqual(interval([game(3*3600)], 600, NOW, 0), 600)

    def test_fast_window_and_end(self):
        self.assertEqual(interval([game(900)], 600, NOW, 0), 120)
        self.assertEqual(interval([game(-60)], 60, NOW, 0), 60)
        self.assertEqual(interval([game(-4*3600)], 600, NOW, 0), 7200)

    def test_wake_before_kickoff(self):
        self.assertEqual(interval([game(1200)], 3600, NOW, 0.1), 300)

    def test_jitter_and_invalid_dates(self):
        self.assertAlmostEqual(interval([{'start':'bad'}, {'start':None}], 600, NOW, 0.1), 7920)

    def test_retry_after_seconds_and_date(self):
        gate = Gate()
        gate.failed('86400', 429, NOW, 0)
        self.assertEqual(gate.remaining(NOW), 86400)
        gate = Gate()
        date = format_datetime(datetime.fromtimestamp(NOW+900, timezone.utc))
        gate.failed(date, 503, NOW, 0)
        self.assertEqual(gate.remaining(NOW), 900)

    def test_backoff_and_recovery(self):
        gate = Gate()
        gate.failed('invalid', 429, NOW, 0)
        self.assertEqual(gate.remaining(NOW), 300)
        gate.failed(None, 429, NOW+300, 0)
        self.assertEqual(gate.remaining(NOW+300), 600)
        gate.succeeded()
        self.assertEqual(gate.remaining(NOW), 0)
        self.assertEqual(gate.failures, 0)

    def test_forbidden_pause(self):
        gate = Gate()
        gate.failed(None, 403, NOW, 0)
        self.assertEqual(gate.remaining(NOW), 3600)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_blocks_next_network_request(self):
        tree = ast.parse((ROOT/'coordinator.py').read_text())
        coordinator = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fetch = next(n for n in coordinator.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_fetch_text')
        class UpdateFailed(Exception):
            pass
        ns = {'UpdateFailed':UpdateFailed, 'timedelta':timedelta,
              'async_timeout':SimpleNamespace(timeout=asyncio.timeout)}
        exec(compile(ast.Module(body=[fetch], type_ignores=[]), 'coordinator.py', 'exec'), ns)
        class Response:
            status = 429
            headers = {'Retry-After':'3600'}
            released = False
            def raise_for_status(self):
                raise RuntimeError('rate limited')
            def release(self):
                self.released = True
        response = Response()
        calls = []
        async def get(*args, **kwargs):
            calls.append(args)
            return response
        obj = SimpleNamespace(_polling_gate=Gate(), _etag={}, _last_modified={},
                              _last_text={}, session=SimpleNamespace(get=get))
        with self.assertRaises(UpdateFailed):
            await ns['_fetch_text'](obj, 'https://example.test/schedule')
        self.assertTrue(response.released)
        self.assertGreaterEqual(obj._polling_gate.remaining(), 3599)
        # Manual refresh or another match URL must obey the same source cooldown.
        with self.assertRaises(UpdateFailed):
            await ns['_fetch_text'](obj, 'https://example.test/match')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
