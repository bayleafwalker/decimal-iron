import tempfile
import unittest
from pathlib import Path

from decimal_iron.conversion import fim_minor_to_eur_minor, prepare_euro_statement, statement_difference
from decimal_iron.machine import DecimalMachine
from decimal_iron.panel import PanelController
from decimal_iron.protocol import decode_screen
from decimal_iron.terminal import TerminalSession


class ExactConversionTests(unittest.TestCase):
    def test_known_integer_results_and_signed_symmetry(self):
        # Independent expected figures, including the exact fixed-rate pair:
        # FIM 5945.73 -> EUR 1000.00. No decimal/float implementation oracle.
        for source, expected in ((0, 0), (1, 0), (2, 0), (3, 1), (100, 17), (300, 50), (594573, 100000)):
            self.assertEqual(fim_minor_to_eur_minor(source), expected)
            self.assertEqual(fim_minor_to_eur_minor(-source), -expected)
        for invalid in (True, 1.0, "100", None):
            with self.assertRaises(ValueError):
                fim_minor_to_eur_minor(invalid)

    def test_residue_is_explicit_and_currency_typed(self):
        omitted = prepare_euro_statement([100, 100, 100], "OMIT")
        accounted = prepare_euro_statement([100, 100, 100], "ACCOUNT")
        self.assertEqual(omitted["item_amounts_minor"], [17, 17, 17])
        self.assertEqual(omitted["item_total_minor"], 51)
        self.assertEqual(omitted["aggregate_total_minor"], 50)
        self.assertEqual(omitted["residue_minor"], 1)
        self.assertEqual(accounted["rounding_adjustment_minor"], -1)
        self.assertEqual(statement_difference(omitted), 1)
        self.assertEqual(statement_difference(accounted), 0)
        self.assertEqual(statement_difference(prepare_euro_statement([-100] * 3, "OMIT")), -1)
        self.assertEqual(statement_difference(prepare_euro_statement([], "ACCOUNT")), 0)
        with self.assertRaisesRegex(ValueError, "EUR cents"):
            statement_difference({**accounted, "currency": "FIM"})
        with self.assertRaises(ValueError):
            prepare_euro_statement([100], "SILENT")


class CurrencyScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal_path = Path(self.temp.name) / "journal.jsonl"
        self.machine = DecimalMachine(self.journal_path)
        self.command("KEY OPEN", "KEY")
        self.command("OPEN 2002-01-02", "OPENED")
        for identity in ("E001", "E002", "E003"):
            self.command(f"PAY {identity} FI01 FI02 FIM 100", "POSTED")

    def tearDown(self):
        self.machine.close()
        self.temp.cleanup()

    def command(self, command, expected):
        result = self.machine.command(command)
        self.assertEqual(result.code, expected, result)
        return result

    def settle(self):
        for command, expected in (("KEY CUT-OFF", "KEY"), ("CUTOFF", "CUTOFF"), ("KEY SETTLE", "KEY"), ("SETTLE", "SETTLED")):
            self.command(command, expected)

    def close_error(self, expected):
        self.command("KEY CLOSED", "KEY")
        self.assertEqual(self.command("CLOSE", "ERROR").data["error_code"], expected)

    def test_euro_clear_cannot_erase_fim_break_or_bypass_close(self):
        self.settle()
        self.command("BREAK 7", "BREAK_INJECTED")
        self.command("RECONCILE FIM", "RECONCILED")
        self.command("CONVERT EUR ACCOUNT", "EUR_STATEMENT")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.assertTrue(self.machine.beacon_on)
        self.assertEqual(self.machine.reconciliation_scopes()["FIM"]["difference_minor"], 7)
        self.assertEqual(self.machine.reconciliation_scopes()["EUR"]["difference_minor"], 0)
        self.close_error("RECONCILIATION_BREAK")
        self.command("CLEARBREAK", "BREAK_CLEARED")
        self.assertTrue(self.machine.beacon_on)
        self.close_error("RECONCILIATION_REQUIRED")
        self.command("RECONCILE FIM", "RECONCILED")
        self.assertFalse(self.machine.beacon_on)
        self.command("CLOSE", "CLOSED")

    def test_fim_clear_cannot_erase_euro_break_or_bypass_close(self):
        self.settle()
        self.command("CONVERT EUR OMIT", "EUR_STATEMENT")
        self.assertFalse(self.machine.beacon_on)
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.command("RECONCILE FIM", "RECONCILED")
        self.assertTrue(self.machine.beacon_on)
        self.assertEqual(self.machine.reconciliation_break_minor, 0, "legacy field remains FIM only")
        self.close_error("EUR_RECONCILIATION_BREAK")
        self.command("CONVERT EUR ACCOUNT", "EUR_STATEMENT")
        self.assertTrue(self.machine.beacon_on, "changed input cannot clear the retained result")
        self.assertTrue(self.machine.reconciliation_current)
        self.assertFalse(self.machine.euro_reconciliation_current)
        self.close_error("EUR_RECONCILIATION_REQUIRED")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.assertFalse(self.machine.beacon_on)
        self.command("CLOSE", "CLOSED")

    def test_each_scope_requires_current_input_and_matching_reconciliation(self):
        self.settle()
        self.command("CONVERT EUR ACCOUNT", "EUR_STATEMENT")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.close_error("RECONCILIATION_REQUIRED")
        self.command("RECONCILE", "RECONCILED")
        self.command("CONVERT EUR ACCOUNT", "EUR_STATEMENT")
        self.close_error("EUR_RECONCILIATION_REQUIRED")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.command("BREAK 2", "BREAK_INJECTED")
        self.assertFalse(self.machine.beacon_on)
        self.close_error("RECONCILIATION_REQUIRED")

    def test_statement_uses_current_day_journal_postings_and_signed_reversals(self):
        self.command("REV E003 R003 correction", "REVERSED")
        self.settle()
        source_head = self.machine.journal_head
        self.command("CONVERT EUR OMIT", "EUR_STATEMENT")
        statement = self.machine.euro_statement
        self.assertEqual(statement["source_amounts_minor"], [100, 100, 100, -100])
        self.assertEqual(statement["item_amounts_minor"], [17, 17, 17, -17])
        self.assertEqual(statement["source_journal_head"], source_head)
        for sequence in statement["source_posting_sequences"]:
            self.assertIn(self.machine.journal.entries[sequence - 1]["kind"], {"PAYMENT_POSTED", "PAYMENT_REVERSED"})
        self.command("RECONCILE FIM", "RECONCILED")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.command("KEY CLOSED", "KEY")
        self.command("CLOSE", "CLOSED")
        self.command("KEY OPEN", "KEY")
        self.command("OPEN 2002-01-03", "OPENED")
        self.assertIsNone(self.machine.euro_statement)
        self.command("PAY N001 FI01 FI02 FIM 594", "POSTED")
        self.settle()
        self.command("CONVERT EUR ACCOUNT", "EUR_STATEMENT")
        self.assertEqual(self.machine.euro_statement["source_amounts_minor"], [594])
        self.assertEqual(self.machine.euro_statement["item_amounts_minor"], [100])

    def test_conversion_is_not_a_multi_currency_posting_or_visual_era_switch(self):
        self.assertEqual(self.command("CONVERT EUR ACCOUNT", "ERROR").data["error_code"], "DAY_NOT_SETTLED")
        self.command("PAY EURO FI01 FI02 EUR 100", "ERROR")
        self.settle()
        self.assertEqual(self.command("RECONCILE EUR", "ERROR").data["error_code"], "EUR_STATEMENT_REQUIRED")
        positions, transactions = dict(self.machine.positions), dict(self.machine.transactions)
        self.command("CONVERT EUR ACCOUNT", "EUR_STATEMENT")
        self.assertEqual(self.machine.positions, positions)
        self.assertEqual(self.machine.transactions, transactions)
        self.command("RECONCILE FIM", "RECONCILED")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        self.command("KEY CLOSED", "KEY")
        self.command("CLOSE", "CLOSED")
        self.assertEqual(self.command("CONVERT EUR OMIT", "ERROR").data["error_code"], "DAY_NOT_SETTLED")

    def test_journal_replay_preserves_both_scopes_and_typed_views(self):
        self.settle()
        self.command("BREAK 7", "BREAK_INJECTED")
        self.command("RECONCILE FIM", "RECONCILED")
        self.command("CONVERT EUR OMIT", "EUR_STATEMENT")
        self.command("RECONCILE EUR", "EUR_RECONCILED")
        expected, report = self.machine.summary(), self.machine.report_text()
        self.machine.close()
        self.machine = DecimalMachine(self.journal_path)
        self.assertEqual(self.machine.summary(), expected)
        self.assertEqual(self.machine.report_text(), report)
        self.assertIn("1 EUR cents", report)
        terminal = TerminalSession(self.machine)
        self.assertIn("EUR STATEMENT RECON 1 cents CURRENT", "\n".join(decode_screen(terminal.take_output())))
        self.assertEqual(PanelController(self.machine).snapshot()["processor"]["reconciliation_scopes"], expected["reconciliation_scopes"])

    def test_open_cannot_erase_closed_day_break_or_stale_input(self):
        self.settle()
        self.command("RECONCILE FIM", "RECONCILED")
        self.command("KEY CLOSED", "KEY")
        self.command("CLOSE", "CLOSED")
        self.command("BREAK 1", "BREAK_INJECTED")
        self.command("KEY OPEN", "KEY")
        self.assertEqual(self.command("OPEN 2002-01-03", "ERROR").data["error_code"], "PREVIOUS_RECONCILIATION_REQUIRED")
        self.command("RECONCILE FIM", "RECONCILED")
        self.assertTrue(self.machine.beacon_on)
        self.assertEqual(self.command("OPEN 2002-01-03", "ERROR").data["error_code"], "PREVIOUS_RECONCILIATION_REQUIRED")
        self.command("CLEARBREAK", "BREAK_CLEARED")
        self.command("RECONCILE FIM", "RECONCILED")
        self.command("OPEN 2002-01-03", "OPENED")


if __name__ == "__main__":
    unittest.main()
