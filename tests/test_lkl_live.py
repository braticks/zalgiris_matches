"""Regression coverage for cross-row LKL scores and poisoned finished cache."""
import ast
import asyncio
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
import re
from types import SimpleNamespace
import typing
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'custom_components/zalgiris_matches/beta12_coordinator.py'
NOW = datetime.fromisoformat('2026-10-04T17:00:00+03:00')
DT = SimpleNamespace(parse_datetime=lambda s: datetime.fromisoformat(s) if s else None, now=lambda: NOW)
namespace = {**vars(typing), 're': re, 'HTMLParser': HTMLParser, 'dt_util': DT,
             'Beta11Coordinator': object, 'GAME_WINDOW': timedelta(hours=4),
             'PREGAME_WINDOW': timedelta(minutes=15), '_status_finished': lambda s: s == 'finished'}
tree = ast.parse(SOURCE.read_text())
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))],
                        type_ignores=[]), str(SOURCE), 'exec'), namespace)
parse = namespace['_parse_lkl_homepage_score']
FIXTURE = (ROOT / 'tests/fixtures/lkl_scoreboard.html').read_text()


def game():
    return dict(game_id='ddf12255-2186-4350-91f7-e8200365b444',
                start='2026-10-04T16:50:00+03:00', home='Žalgiris', away='Lietkabelis',
                league='Lietuvos Krepšinio Lyga')


class LklTests(unittest.TestCase):
    def test_real_scoreboard(self):
        result = parse(FIXTURE, game())
        self.assertEqual((result['score_home'], result['score_away']), (8, 9))
        self.assertEqual(result['source_game_id'], '11593')
        self.assertEqual(result['status'], 'inprogress')

    def test_no_cross_row_score_before_tipoff(self):
        source = FIXTURE.replace('8 - 9', '16:50').replace('GYVAI', '')
        self.assertIsNone(parse(source, game()))

    def test_wrong_day_and_opponent(self):
        for changes in ({'start': '2026-10-03T16:50:00+03:00'},
                        {'away': 'Šiauliai'}, {'home': 'Lietkabelis', 'away': 'Žalgiris'}):
            self.assertIsNone(parse(FIXTURE, {**game(), **changes}))

    def test_tie_and_zero(self):
        for score in (0, 50):
            result = parse(FIXTURE.replace('8 - 9', f'{score} - {score}'), game())
            self.assertEqual((result['score_home'], result['score_away']), (score, score))

    def test_finished_same_fixture(self):
        result = parse(FIXTURE.replace('GYVAI', ''), game())
        self.assertEqual(result['status'], 'finished')

    def test_missing_date_rejected(self):
        self.assertIsNone(parse(FIXTURE.replace('Spalio 4d.', ''), game()))

    def test_conflicting_fixture_rejected(self):
        self.assertIsNone(parse(FIXTURE + FIXTURE.replace('11593', '99999'), game()))

    def test_recovery_and_unavailable_source(self):
        async def run(source):
            cls = namespace['ZalgirisMatchesCoordinator']
            obj = object.__new__(cls)
            stuck = {**game(), 'score_home': 63, 'score_away': 79,
                     'live_source': 'LKL.lt', 'live_status': 'finished'}
            obj._games = {'fixture': stuck}
            calls = []
            async def fetch(*args):
                calls.append(args)
                return source
            obj._fetch_live_text = fetch
            def apply(g, home, away, **kwargs):
                g.update(score_home=home, score_away=away, live_status=kwargs['status'],
                         live_source=kwargs['source'])
            obj._apply_scores = apply
            updated = await obj._refresh_sofascore()
            self.assertEqual(len(calls), 1)
            if source:
                self.assertEqual(updated, 1)
                self.assertEqual(stuck['score_home'], 8)
                self.assertTrue(stuck['is_live'])
                self.assertEqual(stuck['lkl_game_id'], '11593')
                self.assertEqual(stuck['home'], 'Žalgiris')
            else:
                self.assertEqual(updated, 0)
                self.assertIsNone(stuck['score_home'])
                self.assertIsNone(stuck['live_status'])
        asyncio.run(run(FIXTURE))
        asyncio.run(run(None))


if __name__ == '__main__':
    unittest.main()
