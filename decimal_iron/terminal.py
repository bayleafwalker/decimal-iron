"""Terminal sessions: command interpretation stays behind the byte boundary."""

from __future__ import annotations

import threading
from collections import deque

from .machine import DecimalMachine, format_minor
from .protocol import COLUMNS, ROWS, render_cells


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


class TerminalSession:
    """A single terminal cursor attached to the processor's text command loop."""

    def __init__(self, machine: DecimalMachine):
        self.machine = machine
        self._lock = threading.RLock()
        self._input = bytearray()
        self._output = bytearray()
        self._history: deque[str] = deque(maxlen=2)
        self._last_message = "console ready"
        self._result_line = "RESULT READY"
        self._skip_lf = False
        self._append_screen()

    def _append_screen(self) -> None:
        self._output.extend(render_cells(self.cells()))

    def cells(self) -> list[str]:
        summary = self.machine.summary()
        cells = [" "] * (ROWS * COLUMNS)

        def put(row: int, column: int, value: str) -> None:
            value = _ascii(value)[: max(0, COLUMNS - column)]
            start = row * COLUMNS + column
            cells[start : start + len(value)] = list(value)

        put(0, 0, "DECIMAL IRON / 24x80 TERMINAL / 1982 SERVICE CONSOLE")
        reconciliation = format_minor(summary["reconciliation_break_minor"])
        beacon = "ON" if summary["beacon_on"] else "OFF"
        put(
            1,
            0,
            f"DAY {summary['business_date']:<10} PHASE {summary['phase']:<7} KEY {summary['key_position']:<7} RECON {reconciliation:<17} BEACON {beacon}",
        )
        put(3, 0, "MEMBER POSITIONS (FIM) - negative means net debit")
        put(4, 0, "ACCOUNT    NET POSITION")
        positions = [(k, v) for k, v in summary["positions"].items() if k != "SETTLEMENT"]
        for idx, (member, amount) in enumerate(positions[:7], start=5):
            put(idx, 0, f"{member:<10} {format_minor(amount)}")
        put(13, 0, f"JOURNAL RECORDS {summary['journal_events']:06d}  HEAD {summary['journal_head'][:16]}")
        put(15, 0, "KEY OPEN -> OPEN YYYY-MM-DD | KEY CUT-OFF -> CUTOFF")
        put(16, 0, "KEY SETTLE -> SETTLE | KEY CLOSED -> CLOSE | RECONCILE")
        put(17, 0, "PAY id src dst FIM penni [override reason] | INQUIRE id | REV id reversal-id [reason]")
        put(18, 0, f"LAST: {self._last_message}")
        put(19, 0, self._result_line)
        if self._history:
            put(20, 0, f"PREVIOUS: {self._history[-1]}")
        prompt = "> " + self._input.decode("ascii", "replace")
        put(21, 0, prompt[-COLUMNS:])
        put(23, 0, "TYPE A COMMAND AND PRESS ENTER. ALL AMOUNTS ARE INTEGER PENNI.")
        return cells

    def feed(self, data: bytes) -> None:
        """Consume raw inbound keyboard bytes; output is another terminal byte stream."""
        with self._lock:
            dirty = False
            for byte in data:
                if byte == 0x0A and self._skip_lf:
                    self._skip_lf = False
                    continue
                if byte == 0x0D or byte == 0x0A:
                    self._execute_line()
                    self._skip_lf = byte == 0x0D
                    dirty = True
                elif byte in (0x08, 0x7F):
                    if self._input:
                        self._input.pop()
                        dirty = True
                elif 0x20 <= byte <= 0x7E and len(self._input) < 512:
                    self._input.append(byte)
                    dirty = True
            if dirty:
                self._append_screen()

    def _execute_line(self) -> None:
        command = self._input.decode("ascii", "replace")
        self._input.clear()
        if command:
            self._history.append(command)
        result = self.machine.command(command)
        self._last_message = result.message
        self._result_line = result.terminal_line()

    def take_output(self) -> bytes:
        with self._lock:
            result = bytes(self._output)
            self._output.clear()
            return result
