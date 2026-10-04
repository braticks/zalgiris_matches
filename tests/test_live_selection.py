from copy import deepcopy
from datetime import datetime
from pathlib import Path
import runpy
import unittest

select = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'custom_components/zalgiris_matches/live_selection.py'))['select_live_game']

def now(time='08:00:00', date='2026-10-04'):
    return datetime.fromisoformat(f'{date}T{time}+03:00')

def fixture(**kwargs):
    return dict(dict(game_id='today', start='2026-10-04T16:50:00+03:00', home='Žalgiris', away='Lietkabelis'), **kwargs)

OLD = dict(game_id='old', start='2026-10-01T21:00:00+03:00', live_source='EuroLeague', zalgiris_score=63, opponent_score=79)

class SelectionTests(unittest.TestCase):
    def test_today_preferred_without_live_source(self):
        g = select([OLD, fixture()], now())
        self.assertEqual(g['game_id'], 'today')
        self.assertEqual((g['zalgiris_score'], g['opponent_score']), (0, 0))
        self.assertEqual(g['opponent'], 'Lietkabelis')
        self.assertEqual(g['live_status'], 'scheduled')
        self.assertTrue(g['score_pending'])
        self.assertFalse(g['is_live'])

    def test_started_without_result(self):
        self.assertEqual(select([OLD, fixture()], now('17:00:00'))['live_status'], 'waiting')

    def test_real_and_final_results_preserved(self):
        for status in ('inprogress', 'finished'):
            for source in ('LKL.lt', 'EuroLeague'):
                g = fixture(live_source=source, lkl_game_id='11593', zalgiris_score=8, opponent_score=9, live_status=status)
                self.assertIs(select([OLD, g], now('17:00:00')), g)

    def test_away_orientation(self):
        g = fixture(home='Lietkabelis', away='Žalgiris')
        self.assertEqual(select([g], now())['opponent'], 'Lietkabelis')

    def test_stale_metadata_cleared_without_mutating_cache(self):
        g = fixture(live_source='LKL.lt', live_status='finished', zalgiris_score=63, opponent_score=79,
                    live_clock='02:50', live_period='Q4', break_clock='00:30', clock_source='official_event')
        before = deepcopy(g)
        result = select([g], now('17:00:00'))
        self.assertEqual(result['zalgiris_score'], 0)
        for key in ('live_clock', 'live_period', 'break_clock', 'clock_source', 'live_source'):
            self.assertIsNone(result[key])
        self.assertEqual(g, before)

    def test_local_midnight_rollover(self):
        g = fixture(start='2026-10-03T22:00:00+00:00')
        self.assertEqual(select([OLD, g], now('00:00:00'))['game_id'], 'today')
        self.assertIs(select([OLD, g], now('23:59:59', '2026-10-03')), OLD)

    def test_nonmatch_day_keeps_previous(self):
        self.assertIs(select([OLD, fixture()], now(date='2026-10-03')), OLD)

    def test_invalid_and_empty(self):
        self.assertIsNone(select([{'start': 'bad'}, {'start': '2026-10-04'}], now()))
        self.assertIsNone(select([], now()))

if __name__ == '__main__':
    unittest.main()
