import tempfile
import unittest
from pathlib import Path

from decimal_iron.demo import run_demo


class DemoTests(unittest.TestCase):
    def test_full_clearing_day_includes_break_recovery_and_replay(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "clearing-day"
            summary = run_demo(output)
            self.assertEqual(summary["phase"], "CLOSED")
            self.assertTrue(summary["replay_matches"])
            self.assertFalse(summary["beacon_after_recovery"])
            self.assertTrue((output / "journal.jsonl").exists())
            self.assertIn("Red beacon: OFF", (output / "closing-report.txt").read_text())
            self.assertIn("Red beacon: ON", (output / "break-report.txt").read_text())


if __name__ == "__main__":
    unittest.main()
