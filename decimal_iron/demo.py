"""Deterministic end-to-end clearing-day demonstration."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from .adapter import MemoryTerminalChannel, TerminalPaymentAdapter, TerminalTimeout
from .machine import DecimalMachine
from .protocol import result_line
from .terminal import TerminalSession


class _DropFirstPaymentReply:
    """Lose one acknowledgement after the terminal has processed the payment."""

    def __init__(self, channel: MemoryTerminalChannel):
        self.channel = channel
        self.drop_next = True

    def write(self, data: bytes) -> None:
        self.channel.write(data)

    def read(self, timeout: float = 2.0) -> bytes:
        frame = self.channel.read(timeout)
        if self.drop_next:
            self.drop_next = False
            raise TerminalTimeout("demonstration: acknowledgement lost after durable posting")
        return frame


class _Channel(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float = 2.0) -> bytes: ...


def _command(channel: _Channel, text: str) -> str:
    channel.write(text.encode("ascii") + b"\r")
    return result_line(channel.read())


def _expect(channel: _Channel, command: str, prefix: str) -> str:
    result = _command(channel, command)
    if not result.startswith(prefix):
        raise RuntimeError(f"{command!r} returned {result!r}, expected prefix {prefix!r}")
    return result


def run_demo(output_dir: str | Path) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"demo output directory must be empty: {output}")

    journal_path = output / "journal.jsonl"
    machine = DecimalMachine(journal_path)
    session = TerminalSession(machine)
    channel = MemoryTerminalChannel(session)
    adapter_channel = _DropFirstPaymentReply(channel)
    adapter = TerminalPaymentAdapter(adapter_channel)

    _expect(channel, "KEY OPEN", "RESULT KEY")
    _expect(channel, "OPEN 1982-10-01", "RESULT OPENED")
    adapter.post_payment("T001", "FI01", "FI02", 50_000)
    adapter.post_payment("T002", "FI02", "FI03", 35_000)
    adapter.post_payment("T003", "FI03", "FI01", 20_000)
    adapter.post_payment("T004", "FI01", "FI02", 120_000, override_reason="Treasury approved intraday limit override")
    _expect(channel, "INQUIRE T001", "RESULT INQUIRY POSTED T001")
    _expect(channel, "REV T003 R003 returned settlement", "RESULT REVERSED R003")
    _expect(channel, "REV T003 R003 returned settlement", "RESULT REVERSAL_DUPLICATE R003")

    _expect(channel, "KEY CUT-OFF", "RESULT KEY")
    _expect(channel, "CUTOFF", "RESULT CUTOFF")
    _expect(channel, "KEY SETTLE", "RESULT KEY")
    _expect(channel, "SETTLE", "RESULT SETTLED")

    _expect(channel, "BREAK 1", "RESULT BREAK_INJECTED")
    _expect(channel, "RECONCILE", "RESULT RECONCILED")
    if not machine.beacon_on:
        raise AssertionError("injected nonzero reconciliation difference did not illuminate beacon")
    (output / "break-report.txt").write_text(machine.report_text(), encoding="ascii")

    _expect(channel, "CLEARBREAK", "RESULT BREAK_CLEARED")
    _expect(channel, "RECONCILE", "RESULT RECONCILED")
    if machine.beacon_on:
        raise AssertionError("clean reconciliation left beacon illuminated")
    _expect(channel, "KEY CLOSED", "RESULT KEY")
    _expect(channel, "CLOSE", "RESULT CLOSED")
    _expect(channel, "REPORT", "RESULT REPORT")

    report = machine.report_text()
    (output / "closing-report.txt").write_text(report, encoding="ascii")
    machine.close()
    replayed = DecimalMachine(journal_path)
    try:
        replay_report = replayed.report_text()
        replay_matches = report == replay_report and machine.positions == replayed.positions
    finally:
        replayed.close()
    if not replay_matches:
        raise AssertionError("journal replay did not reproduce balances and closing report")

    summary = {
        "business_date": machine.business_date,
        "phase": machine.phase,
        "payments": 4,
        "reversals": 1,
        "unknown_outcome": "recovered by terminal inquiry after lost acknowledgement",
        "injected_break_minor": 1,
        "beacon_after_recovery": machine.beacon_on,
        "journal_events": len(machine.journal.entries),
        "journal_head": machine.journal_head,
        "report_sha256": machine.report_digest(),
        "replay_matches": replay_matches,
    }
    (output / "demo-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return summary


def run_demo_in_temporary_directory() -> tuple[Path, dict[str, object]]:
    root = Path(tempfile.mkdtemp(prefix="decimal-iron-demo-"))
    output = root / "clearing-day"
    try:
        summary = run_demo(output)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return output, summary
