import tempfile
import unittest
from pathlib import Path

from decimal_iron.machine import DecimalMachine


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Path(self.temp.name) / "journal.jsonl"
        self.machine = DecimalMachine(self.journal)

    def tearDown(self):
        self.temp.cleanup()

    def open_day(self):
        self.assertEqual(self.machine.command("KEY OPEN").code, "KEY")
        self.assertEqual(self.machine.command("OPEN 1982-10-01").code, "OPENED")

    def settle_day(self):
        self.assertEqual(self.machine.command("KEY CUT-OFF").code, "KEY")
        self.assertEqual(self.machine.command("CUTOFF").code, "CUTOFF")
        self.assertEqual(self.machine.command("KEY SETTLE").code, "KEY")
        self.assertEqual(self.machine.command("SETTLE").code, "SETTLED")

    def test_idempotency_limits_override_reversal_and_conservation(self):
        self.open_day()
        self.assertEqual(self.machine.command("PAY P001 FI01 FI02 FIM 90000").code, "POSTED")
        rejected = self.machine.command("PAY P002 FI01 FI02 FIM 20000")
        self.assertEqual(rejected.data["error_code"], "OVERRIDE_REASON_REQUIRED")
        self.assertEqual(self.machine.command("PAY P002 FI01 FI02 FIM 20000 approved by treasury").code, "POSTED")

        before = dict(self.machine.positions)
        duplicate = self.machine.command("PAY P002 FI01 FI02 FIM 20000 approved by treasury")
        self.assertEqual(duplicate.code, "DUPLICATE")
        self.assertEqual(self.machine.positions, before)
        conflict = self.machine.command("PAY P002 FI01 FI02 FIM 20001 approved by treasury")
        self.assertEqual(conflict.data["error_code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.machine.command("PAY P003 FI01 FI02 FIM 5000001").data["error_code"], "HARD_AMOUNT_LIMIT")

        self.assertEqual(self.machine.command("REV P001 R001 correction requested").code, "REVERSED")
        self.assertEqual(self.machine.command("REV P001 R001 correction requested").code, "REVERSAL_DUPLICATE")
        self.assertEqual(self.machine.command("REV P001 R002 another attempt").data["error_code"], "ALREADY_REVERSED")
        self.assertEqual(sum(self.machine.positions.values()), 0)

    def test_business_day_guards_and_beacon_is_only_reconciliation_register(self):
        self.assertEqual(self.machine.command("OPEN 1982-10-01").data["error_code"], "TRANSITION_GUARD")
        self.open_day()
        self.assertEqual(self.machine.command("CUTOFF").data["error_code"], "TRANSITION_GUARD")
        self.assertFalse(self.machine.beacon_on)
        self.assertEqual(self.machine.command("KEY CUT-OFF").code, "KEY")
        self.assertEqual(self.machine.command("CUTOFF").code, "CUTOFF")
        self.assertEqual(self.machine.command("PAY P001 FI01 FI02 FIM 100").data["error_code"], "DAY_NOT_OPEN")
        self.assertFalse(self.machine.beacon_on)

        self.machine.command("KEY SETTLE")
        self.assertEqual(self.machine.command("SETTLE").code, "SETTLED")
        self.machine.command("BREAK 17")
        self.assertFalse(self.machine.beacon_on, "unreconciled input must not drive the physical beacon")
        self.machine.command("KEY CLOSED")
        self.assertEqual(self.machine.command("CLOSE").data["error_code"], "RECONCILIATION_REQUIRED")
        self.machine.command("RECONCILE")
        self.assertTrue(self.machine.beacon_on)
        self.assertEqual(self.machine.command("NOT-A-COMMAND").data["error_code"], "UNKNOWN_COMMAND")
        self.assertTrue(self.machine.beacon_on, "ordinary command errors cannot alter the beacon register")
        self.machine.command("CLEARBREAK")
        self.assertTrue(self.machine.beacon_on, "clearing input is not itself a reconciliation")
        self.machine.command("RECONCILE")
        self.assertFalse(self.machine.beacon_on)
        self.assertEqual(self.machine.command("CLOSE").code, "CLOSED")

    def test_hash_chained_restart_rebuilds_balances_and_report(self):
        self.open_day()
        self.machine.command("PAY P001 FI01 FI02 FIM 2250")
        self.settle_day()
        self.machine.command("RECONCILE")
        self.machine.command("KEY CLOSED")
        self.machine.command("CLOSE")
        report = self.machine.report_text()
        positions = dict(self.machine.positions)

        replayed = DecimalMachine(self.journal)
        self.assertEqual(replayed.positions, positions)
        self.assertEqual(replayed.report_text(), report)
        self.assertEqual(replayed.journal_head, self.machine.journal_head)
        self.assertEqual(replayed.phase, "CLOSED")

    def test_tampered_journal_is_rejected(self):
        self.open_day()
        raw = self.journal.read_text(encoding="ascii").replace('"OPEN"', '"CLOSED"')
        self.journal.write_text(raw, encoding="ascii")
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            DecimalMachine(self.journal)

    def test_conservation_and_beacon_properties_across_deterministic_sweep(self):
        self.open_day()
        members = ("FI01", "FI02", "FI03", "FI04")
        for index in range(1, 81):
            source = members[(index - 1) % len(members)]
            destination = members[index % len(members)]
            amount = (index * 37) % 900 + 1
            result = self.machine.command(f"PAY Q{index:03d} {source} {destination} FIM {amount}")
            self.assertEqual(result.code, "POSTED")
            self.assertEqual(sum(self.machine.positions.values()), 0)

        self.settle_day()
        for discrepancy in (-1000, -1, 1, 1000):
            self.machine.command("CLEARBREAK")
            self.machine.command(f"BREAK {discrepancy}")
            self.machine.command("RECONCILE")
            self.assertEqual(self.machine.beacon_on, self.machine.reconciliation_break_minor != 0)
            self.assertEqual(self.machine.beacon_on, discrepancy != 0)


if __name__ == "__main__":
    unittest.main()
