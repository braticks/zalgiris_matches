"""Pure parser regression tests; do not require a running Home Assistant."""
import ast
import html
from pathlib import Path
import re
import typing
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "custom_components/zalgiris_matches/coordinator.py"
NAMES = {"SCORE_RE", "SCORE_ESC_RE", "TV_HTML_RE", "TV_ESC_RE", "_parse_scores", "_parse_tv", "_first_match"}
tree = ast.parse(SOURCE.read_text())
selected = [node for node in tree.body if
            (isinstance(node, ast.FunctionDef) and node.name in NAMES) or
            (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in NAMES for t in node.targets))]
namespace = {**vars(typing), "re": re, "html_lib": html}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)


class ParserTests(unittest.TestCase):
    def test_scores(self):
        for pair in [(50, 50), (0, 0), (50, 49), (100, 99)]:
            with self.subTest(pair=pair):
                source = ''.join(f'<p class="tabular-nums">{s}</p>' for s in pair)
                self.assertEqual(namespace['_parse_scores'](source), pair)

    def test_incomplete_scores(self):
        source = '<p class="tabular-nums">-</p><p class="tabular-nums">50</p>'
        self.assertEqual(namespace['_parse_scores'](source), (None, None))

    def test_broadcaster(self):
        for source in ['<p>Transliacijos</p><p>TV3, Go3</p>',
                       '<p>Transliacijos</p><div><p>TV3, Go3</p></div>']:
            self.assertEqual(namespace['_parse_tv'](source), 'TV3, Go3')

    def test_missing_broadcaster(self):
        self.assertIsNone(namespace['_parse_tv']('<p>Žalgiris</p>'))


if __name__ == '__main__':
    unittest.main()
