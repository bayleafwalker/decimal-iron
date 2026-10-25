from pathlib import Path
import unittest

from decimal_iron.machine import DecimalMachine
from decimal_iron.protocol import CELLS, decode_screen, render_cells
from decimal_iron.terminal import TerminalSession


ROOT = Path(__file__).parent


class ProtocolTests(unittest.TestCase):
    def test_banner_matches_24_by_80_golden_fixture_and_byte_round_trip(self):
        encoded_fixture = (ROOT / "fixtures/banner-screen.txt").read_text(encoding="ascii").splitlines()
        expected = tuple(line.replace("_", " ") for line in encoded_fixture)
        self.assertEqual(len(expected), 24)
        self.assertTrue(all(len(line) == 80 for line in expected))
        self.assertEqual(sum(map(len, expected)), CELLS)

        session = TerminalSession(DecimalMachine())
        cells = session.cells()
        actual = tuple("".join(cells[i : i + 80]) for i in range(0, CELLS, 80))
        self.assertEqual(actual, expected)
        self.assertEqual(decode_screen(render_cells(cells)), expected)


if __name__ == "__main__":
    unittest.main()
