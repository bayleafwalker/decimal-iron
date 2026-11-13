import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from decimal_iron.replay import (
    FixtureFailure, check_replay, encode_replay, export_replay, implementation_identity,
    load_fixture, run_negative_controls, run_scenario,
)


class ReplayFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_fixture()

    def test_all_scenarios_replay_exactly_and_every_checkpoint_is_checked(self):
        for scenario in self.fixture["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                trace = run_scenario(scenario)
                self.assertEqual(trace, run_scenario(scenario))
                self.assertEqual(trace["status"], "passed")
                self.assertTrue(trace["replay"]["state_matches"])
                self.assertTrue(trace["replay"]["report_matches"])
                for step in trace["steps"]:
                    self.assertEqual(step["status"], "passed")
                    self.assertTrue(step["assertions"])
                    for assertion in step["assertions"]:
                        self.assertEqual(assertion["status"], "passed")

    def test_lost_ack_trace_distinguishes_commit_from_client_knowledge(self):
        trace = run_scenario(self.fixture["scenarios"][0])
        steps = {step["id"]: step for step in trace["steps"]}
        committed = steps["payment.committed-unacknowledged"]
        self.assertEqual(committed["state"]["transaction_count"], 1)
        self.assertIsNone(committed["terminal_result"])
        lost = steps["payment.reply-lost"]
        self.assertEqual(lost["state"]["journal_head"], committed["state"]["journal_head"])
        recovered = steps["payment"]
        self.assertEqual(recovered["state"]["journal_head"], committed["state"]["journal_head"])
        self.assertEqual(recovered["receipt_resolution"], "RECOVERED_BY_INQUIRY")
        self.assertEqual(steps["duplicate"]["receipt_resolution"], "IDEMPOTENT_DUPLICATE")
        self.assertEqual(steps["duplicate"]["state"]["transaction_count"], 1)

    def test_changed_expectation_fails_instead_of_rewriting_truth(self):
        changed = copy.deepcopy(self.fixture["scenarios"][0])
        changed["steps"][2]["expected"]["state"]["transaction_count"] = 2
        with self.assertRaisesRegex(FixtureFailure, "expected 2, observed 1"):
            run_scenario(changed)
        changed = copy.deepcopy(self.fixture["scenarios"][0])
        changed["steps"][2]["expected_checkpoints"]["committed-unacknowledged"]["state"]["transaction_count"] = 0
        with self.assertRaisesRegex(FixtureFailure, "expected 0, observed 1"):
            run_scenario(changed)

    def test_real_behavior_mutations_are_rejected(self):
        results = run_negative_controls(self.fixture)
        self.assertEqual(len(results), 3)
        for control in results:
            self.assertEqual(control["status"], "passed")
            self.assertTrue(control["mutation_rejected"])
            self.assertTrue(control["failed_assertions"])

    def test_declarative_fixture_cannot_execute_python_or_multiline_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "fixture.json"
            changed = copy.deepcopy(self.fixture)
            changed["scenarios"][0]["steps"][0]["action"] = {"kind": "python", "code": "raise RuntimeError()"}
            fixture_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                load_fixture(fixture_path)
            changed["scenarios"][0]["steps"][0]["action"] = {"kind": "command", "command": "KEY OPEN\nOPEN 2002-01-01"}
            fixture_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                load_fixture(fixture_path)

    def test_dirty_source_cannot_be_published_as_pinned_evidence(self):
        with patch("decimal_iron.replay.SOURCE_FILES", ("README.md",)):
            # Simulate changed bytes without depending on this checkout's state.
            original_read_bytes = Path.read_bytes
            def changed_bytes(path):
                result = original_read_bytes(path)
                return result + b"changed" if path.name == "README.md" else result
            with patch.object(Path, "read_bytes", changed_bytes):
                with self.assertRaisesRegex(ValueError, "requires committed"):
                    implementation_identity()
                identity = implementation_identity(allow_uncommitted=True)
                self.assertFalse(identity["clean"])
                self.assertIn("README.md", identity["uncommitted_files"])

    def test_export_is_reproducible_and_does_not_upgrade_skips_to_passes(self):
        trace = export_replay(allow_uncommitted=True)
        self.assertEqual(encode_replay(trace), encode_replay(export_replay(allow_uncommitted=True)))
        targets = {target["id"]: target for target in trace["verification"]["targets"]}
        self.assertEqual(targets["python-reference"]["status"], "passed")
        for target in ("rtl-scenario-adapter", "physical-installation", "keskus-game"):
            self.assertEqual(targets[target]["status"], "skipped")
        self.assertEqual(len(trace["implementation"]["revision"]), 40)
        self.assertEqual(len(trace["fixture"]["sha256"]), 64)

    def test_check_allows_reformatting_but_rejects_semantic_and_type_changes(self):
        trace = run_scenario(self.fixture["scenarios"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.json"
            path.write_text(json.dumps(trace, sort_keys=False, indent=4))
            check_replay(trace, path)
            changed = copy.deepcopy(trace)
            changed["steps"][2]["state"]["transaction_count"] = True
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "differs"):
                check_replay(trace, path)


if __name__ == "__main__":
    unittest.main()
