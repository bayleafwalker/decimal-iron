import unittest

from decimal_iron.machine import DecimalMachine
from decimal_iron.panel import PanelController


class PanelTests(unittest.TestCase):
    def test_signals_follow_processor_state_and_controls_cannot_post(self):
        machine = DecimalMachine()
        panel = PanelController(machine)
        start = panel.snapshot()
        self.assertEqual(start["processor"]["phase"], "CLOSED")
        self.assertFalse(start["processor"]["beacon_on"])

        panel.control({"action": "key", "position": "OPEN"})
        self.assertEqual(machine.phase, "CLOSED", "moving a hardware switch does not itself open a day")
        machine.command("OPEN 1982-10-01")
        machine.command("PAY P001 FI01 FI02 FIM 4250")
        snapshot = panel.snapshot()
        self.assertEqual(snapshot["registers"]["AC"], 4_250)
        self.assertEqual(snapshot["meter"]["value_minor"], -4_250)
        self.assertTrue(any(cell["wordmark"] for cell in snapshot["wordmark_window"]))
        self.assertFalse(snapshot["processor"]["beacon_on"])

        before = dict(machine.positions)
        panel.control({"action": "deposit", "address": 249, "character": 7})
        self.assertEqual(machine.positions, before)
        with self.assertRaises(ValueError):
            panel.control({"action": "deposit", "address": 100, "character": 7})
        with self.assertRaises(ValueError):
            panel.control({"action": "key", "position": "SETTLED"})

    def test_beacon_signal_is_the_reconciliation_register(self):
        machine = DecimalMachine()
        panel = PanelController(machine)
        machine.command("KEY OPEN")
        machine.command("OPEN 1982-10-01")
        machine.command("KEY CUT-OFF")
        machine.command("CUTOFF")
        machine.command("KEY SETTLE")
        machine.command("SETTLE")
        machine.command("BREAK 1")
        self.assertFalse(panel.snapshot()["processor"]["beacon_on"])
        machine.command("RECONCILE")
        self.assertTrue(panel.snapshot()["processor"]["beacon_on"])


if __name__ == "__main__":
    unittest.main()
