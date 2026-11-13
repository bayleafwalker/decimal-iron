"""Run declarative scenarios through the real terminal and export checked traces.

The browser receives observations; it does not implement payment or reconciliation
logic. Expected outcomes live in the fixture and are never implementation inputs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from .adapter import MemoryTerminalChannel, TerminalPaymentAdapter, TerminalTimeout
from .conversion import prepare_euro_statement
from .journal import canonical_json
from .machine import DecimalMachine
from .protocol import result_line
from .terminal import TerminalSession

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "replay-scenarios.json"
REPOSITORY = "https://github.com/bayleafwalker/decimal-iron"
# Include the complete Python package, including modules imported by the CLI.
# An uncommitted import side effect must not escape the committed-byte check.
SOURCE_FILES = tuple(str(path.relative_to(ROOT)) for path in sorted(Path(__file__).parent.rglob("*.py")))


class FixtureFailure(AssertionError):
    """An independently declared expectation did not match the implementation."""

    def __init__(self, scenario_id: str, step_id: str, assertions: list[dict[str, Any]]):
        self.scenario_id = scenario_id
        self.step_id = step_id
        self.assertions = assertions
        failed = [a for a in assertions if a["status"] == "failed"]
        super().__init__(f"{scenario_id}/{step_id}: " + "; ".join(
            f"{a['path']}: expected {a['expected']!r}, observed {a['observed']!r}" for a in failed
        ))


def load_fixture(path: str | Path = FIXTURE_PATH) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="ascii"))
    if fixture.get("schema") != "decimal-iron-scenarios/v1":
        raise ValueError("unsupported scenario fixture schema")
    scenarios = fixture.get("scenarios")
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 30:
        raise ValueError("fixture must contain 1-30 scenarios")
    scenario_ids: set[str] = set()
    for scenario in scenarios:
        scenario_id = scenario["id"]
        if not re.fullmatch(r"[a-z0-9-]{1,80}", scenario_id) or scenario_id in scenario_ids:
            raise ValueError("scenario identities must be unique bounded slugs")
        scenario_ids.add(scenario_id)
        if not isinstance(scenario["steps"], list) or not 1 <= len(scenario["steps"]) <= 100:
            raise ValueError("a scenario must contain 1-100 steps")
        step_ids: set[str] = set()
        for step in scenario["steps"]:
            if not re.fullmatch(r"[a-z0-9-]{1,80}", step["id"]) or step["id"] in step_ids:
                raise ValueError("step identities must be unique bounded slugs")
            step_ids.add(step["id"])
            if not isinstance(step.get("expected"), dict) or not step["expected"]:
                raise ValueError("every fixture step needs independent expectations")
            action = step["action"]
            if action["kind"] == "command":
                command = action["command"]
                if not isinstance(command, str) or not 1 <= len(command) <= 200 or any(
                    ord(ch) < 32 or ord(ch) > 126 for ch in command
                ):
                    raise ValueError("command must be one bounded printable ASCII line")
            elif action["kind"] == "payment":
                if action.get("fault") not in {"none", "before-delivery", "after-commit-before-ack"}:
                    raise ValueError("unsupported transport interruption")
                if type(action["amount_minor"]) is not int or not 1 <= action["amount_minor"] <= 5_000_000:
                    raise ValueError("payment amount must be positive bounded integer penni")
                for field in ("payment_id", "source", "destination"):
                    if not re.fullmatch(r"[A-Z0-9_-]{1,32}", action[field]):
                        raise ValueError(f"invalid payment {field}")
            else:
                raise ValueError("fixture actions are limited to command and payment")
    return fixture


def _state(machine: DecimalMachine) -> dict[str, Any]:
    return {**machine.summary(), "transaction_count": len(machine.transactions)}


def _compare(expected: Any, observed: Any, path: str = "") -> list[dict[str, Any]]:
    """Compare a declarative subset. Types matter: true is not integer 1."""
    if isinstance(expected, dict) and isinstance(observed, dict):
        assertions: list[dict[str, Any]] = []
        for key, value in expected.items():
            assertions.extend(_compare(value, observed.get(key), f"{path}.{key}".lstrip(".")))
        return assertions
    equal = type(expected) is type(observed) and expected == observed
    return [{"path": path, "expected": expected, "observed": observed, "status": "passed" if equal else "failed"}]


def _assertions(expected: dict[str, Any], observed: dict[str, Any], line: str | None) -> list[dict[str, Any]]:
    assertions = _compare({k: v for k, v in expected.items() if k != "terminal_prefix"}, observed)
    if "terminal_prefix" in expected:
        prefix = expected["terminal_prefix"]
        matches = line is not None and (line == prefix or line.startswith(prefix + " "))
        assertions.append({"path": "terminal_prefix", "expected": prefix, "observed": line,
                           "status": "passed" if matches else "failed"})
    return assertions


class _ObservedChannel:
    """Local byte transport with a single declared interruption, never a ledger API."""

    def __init__(self, terminal: MemoryTerminalChannel, fault: str,
                 observe: Callable[[str, str, str | None], None]):
        self.terminal = terminal
        self.fault = fault
        self.observe = observe
        self.triggered = False
        self.drop_reply = False
        self.command = ""
        self.last_result: str | None = None
        self.counters = {"payment_writes": 0, "inquiries": 0, "lost_replies": 0}

    def write(self, data: bytes) -> None:
        self.command = data.decode("ascii").rstrip("\r")
        payment = self.command.startswith("PAY ")
        if payment:
            self.counters["payment_writes"] += 1
        if self.command.startswith("INQUIRE "):
            self.counters["inquiries"] += 1
        if payment and self.fault == "before-delivery" and not self.triggered:
            self.triggered = True
            self.observe("request-interrupted", "The write is interrupted before delivery; the client cannot assume that.", None)
            raise TerminalTimeout("fixture interruption before delivery")
        self.terminal.write(data)
        if payment and self.fault == "after-commit-before-ack" and not self.triggered:
            self.triggered = True
            self.drop_reply = True
            self.observe("committed-unacknowledged", "The journal commit exists; the client has no acknowledgement.", None)

    def read(self, timeout: float = 2.0) -> bytes:
        frame = self.terminal.read(timeout)
        if self.drop_reply:
            self.drop_reply = False
            self.counters["lost_replies"] += 1
            self.observe("reply-lost", "The transport discards the reply after the commit.", None)
            raise TerminalTimeout("fixture interruption after commit before acknowledgement")
        self.last_result = result_line(frame)
        if self.command.startswith("INQUIRE "):
            self.observe("inquiry-result", "Inquiry resolves the original payment identity through the terminal.", self.last_result)
        return frame


def run_scenario(scenario: dict[str, Any], *, adapter_type: type[TerminalPaymentAdapter] = TerminalPaymentAdapter) -> dict[str, Any]:
    """Execute all fixture commands, then reconstruct the same state from disk."""
    trace: dict[str, Any] = {key: scenario[key] for key in ("id", "title", "summary")}
    trace["steps"] = []
    with tempfile.TemporaryDirectory(prefix="decimal-iron-replay-") as directory:
        journal_path = Path(directory) / "journal.jsonl"
        machine = DecimalMachine(journal_path)
        terminal = MemoryTerminalChannel(TerminalSession(machine))
        try:
            for step in scenario["steps"]:
                action = step["action"]
                observed_points: list[str] = []

                def observe(point: str, label: str, terminal_result: str | None) -> None:
                    observed_points.append(point)
                    checkpoint_state = _state(machine)
                    expected_checkpoint = step.get("expected_checkpoints", {}).get(point)
                    if not expected_checkpoint:
                        raise ValueError(f"{scenario['id']}/{step['id']}.{point}: checkpoint needs fixture expectations")
                    assertions = _assertions(expected_checkpoint, {"state": checkpoint_state, "terminal_result": terminal_result}, terminal_result)
                    status = "passed" if all(a["status"] == "passed" for a in assertions) else "failed"
                    trace["steps"].append({
                        "id": f"{step['id']}.{point}", "fixture_step": step["id"],
                        "label": label, "action": copy.deepcopy(action), "checkpoint": True,
                        "terminal_result": terminal_result, "state": checkpoint_state,
                        "assertions": assertions, "status": status,
                    })
                    if status == "failed":
                        raise FixtureFailure(scenario["id"], f"{step['id']}.{point}", assertions)

                observed: dict[str, Any] = {}
                if action["kind"] == "command":
                    terminal.write(action["command"].encode("ascii") + b"\r")
                    line = result_line(terminal.read())
                else:
                    channel = _ObservedChannel(terminal, action["fault"], observe)
                    receipt = adapter_type(channel).post_payment(
                        action["payment_id"], action["source"], action["destination"], action["amount_minor"],
                    )
                    observed["receipt_resolution"] = receipt.resolution
                    observed["receipt"] = asdict(receipt)
                    observed["transport"] = channel.counters
                    line = channel.last_result
                observed["state"] = _state(machine)
                expected = step["expected"]
                assertions = _assertions(expected, observed, line)
                if step.get("expected_checkpoints"):
                    assertions += _compare(sorted(step["expected_checkpoints"]), sorted(observed_points), "checkpoints_executed")
                status = "passed" if all(a["status"] == "passed" for a in assertions) else "failed"
                trace["steps"].append({
                    "id": step["id"], "fixture_step": step["id"], "label": step["label"],
                    "action": copy.deepcopy(action), "checkpoint": step.get("checkpoint", False),
                    "terminal_result": line, **observed, "assertions": assertions, "status": status,
                })
                if status != "passed":
                    raise FixtureFailure(scenario["id"], step["id"], assertions)
            state, report = _state(machine), machine.report_text()
            journal_digest = hashlib.sha256(journal_path.read_bytes()).hexdigest()
        finally:
            machine.close()
        replayed = DecimalMachine(journal_path)
        try:
            replay_assertions = _compare(state, _state(replayed), "state")
            replay_assertions += _compare(report, replayed.report_text(), "report")
            if any(a["status"] != "passed" for a in replay_assertions):
                raise FixtureFailure(scenario["id"], "journal-replay", replay_assertions)
            trace["replay"] = {
                "status": "passed", "state_matches": True, "report_matches": True,
                "journal_sha256": journal_digest,
                "report_sha256": hashlib.sha256(report.encode("ascii")).hexdigest(),
                "journal_events": state["journal_events"], "journal_head": state["journal_head"],
            }
        finally:
            replayed.close()
    trace["status"] = "passed"
    return trace


class _NewIdentityAfterTimeout(TerminalPaymentAdapter):
    """Deliberately wrong recovery, used only to prove that fixtures reject it."""

    def _recover(self, payment_id: str, command: str, original_error: Exception):
        del original_error
        changed_id = payment_id + "_RETRY"
        changed_command = command.replace(f"PAY {payment_id} ", f"PAY {changed_id} ", 1)
        # Report the normal resolution to ensure the ledger invariant, not merely
        # a result label, exposes the second posting.
        return self._payment_response(self._exchange(changed_command), changed_id, "RECOVERED_BY_INQUIRY")


def run_negative_controls(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = {scenario["id"]: scenario for scenario in fixture["scenarios"]}
    controls = []

    def expect_rejected(control_id: str, scenario_id: str, run: Callable[[], Any], required_path: str) -> None:
        try:
            run()
        except FixtureFailure as exc:
            failures = [a for a in exc.assertions if a["status"] == "failed"]
            if not any(a["path"] == required_path for a in failures):
                raise AssertionError(f"{control_id} did not reject its intended invariant") from exc
            controls.append({"id": control_id, "scenario": scenario_id, "status": "passed",
                             "mutation_rejected": True, "rejected_at": exc.step_id, "failed_assertions": failures})
        else:
            raise AssertionError(f"negative control {control_id} was accepted")

    expect_rejected(
        "new-identity-after-lost-ack", "lost-acknowledgement",
        lambda: run_scenario(scenarios["lost-acknowledgement"], adapter_type=_NewIdentityAfterTimeout),
        "state.transaction_count",
    )

    def omit_adjustment(amounts: list[int], treatment: str) -> dict[str, Any]:
        statement = prepare_euro_statement(amounts, treatment)
        statement["rounding_adjustment_minor"] = 0
        return statement

    with patch("decimal_iron.machine.prepare_euro_statement", omit_adjustment):
        expect_rejected(
            "silently-omit-rounding-adjustment", "euro-rounding-residue",
            lambda: run_scenario(scenarios["euro-rounding-residue"]),
            "state.conversion_statement.rounding_adjustment_minor",
        )
    with patch("decimal_iron.machine.statement_difference", return_value=0):
        expect_rejected(
            "suppress-eur-reconciliation-break", "euro-rounding-residue",
            lambda: run_scenario(scenarios["euro-rounding-residue"]),
            "state.reconciliation_scopes.EUR.difference_minor",
        )
    return controls


def implementation_identity(*, allow_uncommitted: bool = False) -> dict[str, Any]:
    """Bind exact executed source bytes to HEAD; reject unbound public evidence."""
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    files = {}
    uncommitted = []
    for name in (*SOURCE_FILES, str(FIXTURE_PATH.relative_to(ROOT)), "pyproject.toml"):
        raw = (ROOT / name).read_bytes()
        files[name] = hashlib.sha256(raw).hexdigest()
        committed = subprocess.run(["git", "show", f"{revision}:{name}"], cwd=ROOT, capture_output=True)
        if committed.returncode or committed.stdout != raw:
            uncommitted.append(name)
    if uncommitted and not allow_uncommitted:
        raise ValueError("replay evidence requires committed implementation and fixture bytes: " + ", ".join(uncommitted))
    return {"repository": REPOSITORY, "revision": revision, "clean": not uncommitted,
            "source_digest": hashlib.sha256(canonical_json(files)).hexdigest(),
            "source_files": files, "uncommitted_files": uncommitted}


def export_replay(*, allow_uncommitted: bool = False) -> dict[str, Any]:
    identity = implementation_identity(allow_uncommitted=allow_uncommitted)
    fixture = load_fixture()
    scenarios = [run_scenario(scenario) for scenario in fixture["scenarios"]]
    controls = run_negative_controls(fixture)
    return {
        "schema": "decimal-iron-replay/v1", "implementation": identity,
        "fixture": {"path": str(FIXTURE_PATH.relative_to(ROOT)),
                    "sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(), "schema": fixture["schema"]},
        "verification": {
            "status": "passed" if identity["clean"] else "draft",
            "negative_controls": controls,
            "targets": [
                {"id": "python-reference", "status": "passed", "detail": "Actual file-backed machine, byte terminal, payment adapter and journal replay"},
                {"id": "rtl-scenario-adapter", "status": "skipped", "detail": "This scenario runner does not execute RTL; transfer-vector tests are separate"},
                {"id": "physical-installation", "status": "skipped", "detail": "No physical meters, printer, UART timing or 300-baud link exercised"},
                {"id": "keskus-game", "status": "skipped", "detail": "Fixture contract is shareable; no game adapter executed"},
            ],
        },
        "scenarios": scenarios,
    }


def encode_replay(trace: dict[str, Any]) -> str:
    return json.dumps(trace, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def check_replay(trace: dict[str, Any], path: str | Path) -> None:
    """Ignore JSON presentation while retaining exact values and JSON types."""
    recorded = json.loads(Path(path).read_text(encoding="utf-8"))
    if canonical_json(recorded) != canonical_json(trace):
        raise ValueError("checked replay differs from the executed fixture evidence")
