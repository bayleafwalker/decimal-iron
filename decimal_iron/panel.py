"""State-derived front-panel signals and safe operator controls."""

from __future__ import annotations

import threading
from typing import Any

from .cpu import PANEL_SCRATCH_START
from .machine import DecimalMachine

REGISTER_NAMES = ("PC", "AR", "IR", "AC", "POSITION")
KEY_POSITIONS = ("CLOSED", "OPEN", "CUT-OFF", "SETTLE")
SEGMENTS = {
    "0": 0x3F,
    "1": 0x06,
    "2": 0x5B,
    "3": 0x4F,
    "4": 0x66,
    "5": 0x6D,
    "6": 0x7D,
    "7": 0x07,
    "8": 0x7F,
    "9": 0x6F,
    "A": 0x77,
    "B": 0x7C,
    "C": 0x39,
    "D": 0x5E,
    "E": 0x79,
    "F": 0x71,
    "-": 0x40,
}


class PanelError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PanelController:
    """Read-only instrumentation plus modeled switches and memory service controls.

    The panel cannot post, reverse, settle or mutate ledger positions. Its
    deposit control is wired only to reserved diagnostic scratch cells.
    """

    def __init__(self, machine: DecimalMachine):
        self.machine = machine
        self._lock = threading.RLock()
        self.selected_register = "AC"
        self.selected_member = "FI01"

    @staticmethod
    def _display_digits(value: int, width: int) -> str:
        sign = "-" if value < 0 else ""
        magnitude = str(abs(value)).rjust(width - len(sign), "0")
        return (sign + magnitude)[-width:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock, self.machine._lock:
            cpu = self.machine.cpu
            summary = self.machine.summary()
            positions = summary["positions"]
            if self.selected_member not in positions and self.selected_member != "FI01":
                self.selected_member = next(iter(positions), "FI01")
            register_values = {
                "PC": (cpu.pc, 3),
                "AR": (cpu.ar, 3),
                "IR": (cpu.ir, 2),
                "AC": (cpu.accumulator, 12),
                "POSITION": (positions.get(self.selected_member, 0), 12),
            }
            value, width = register_values[self.selected_register]
            digits = self._display_digits(value, width)
            address = cpu.ar
            memory_window = []
            for location in range(max(0, address - 8), min(256, address + 8)):
                cell = cpu.examine(location)
                memory_window.append(
                    {
                        "address": location,
                        "character": f"{cell.character:X}",
                        "wordmark": cell.wordmark,
                        "negative": cell.negative,
                    }
                )
            meter_value = positions.get(self.selected_member, 0)
            scale = max(1, self.machine.overdraft_limit_minor)
            deflection = max(-100.0, min(100.0, meter_value * 100.0 / scale))
            return {
                "processor": {
                    "phase": summary["phase"],
                    "business_date": summary["business_date"],
                    "key_position": summary["key_position"],
                    "beacon_on": summary["beacon_on"],
                    "journal_events": summary["journal_events"],
                    "journal_head": summary["journal_head"],
                },
                "registers": {
                    "PC": cpu.pc,
                    "AR": cpu.ar,
                    "IR": cpu.ir,
                    "AC": cpu.accumulator,
                    "zero": cpu.zero_flag,
                    "negative": cpu.negative_flag,
                    "carry": cpu.carry_flag,
                    "overflow": cpu.overflow_flag,
                    "halted": cpu.halted,
                    "instruction_count": cpu.instruction_count,
                    "alu_digit_cycles": cpu.alu_digit_cycles,
                    "last_instruction": cpu.last_mnemonic,
                    "fault": cpu.fault,
                },
                "selector": {"register": self.selected_register, "member": self.selected_member},
                "display": {
                    "value": value,
                    "digits": digits,
                    "segments": [SEGMENTS.get(character.upper(), 0) for character in digits],
                    "width": width,
                },
                "wordmark_window": memory_window,
                "meter": {
                    "member": self.selected_member,
                    "value_minor": meter_value,
                    "scale_minor": scale,
                    "deflection_percent": deflection,
                },
                "limits": {"scratch_start": PANEL_SCRATCH_START, "memory_size": 256},
            }

    def control(self, body: dict[str, Any]) -> dict[str, Any]:
        action = str(body.get("action", "")).lower()
        with self._lock, self.machine._lock:
            if action == "key":
                position = str(body.get("position", "")).upper()
                if position not in KEY_POSITIONS:
                    raise PanelError("BAD_KEY_POSITION", "key position must be CLOSED, OPEN, CUT-OFF or SETTLE")
                result = self.machine.command(f"KEY {position}")
                return {"result": result.code, "message": result.message, "snapshot": self.snapshot()}
            if action == "register":
                register = str(body.get("register", "")).upper()
                if register not in REGISTER_NAMES:
                    raise PanelError("BAD_REGISTER", "register must be PC, AR, IR, AC or POSITION")
                self.selected_register = register
                return {"result": "SELECTED", "snapshot": self.snapshot()}
            if action == "meter":
                member = str(body.get("member", "")).upper()
                if member not in self.machine.positions:
                    raise PanelError("UNKNOWN_MEMBER", "meter member has no processor position word")
                self.selected_member = member
                return {"result": "SELECTED", "snapshot": self.snapshot()}
            if action == "examine":
                address = self._integer(body, "address", 0, 255)
                cell = self.machine.cpu.examine(address)
                return {
                    "result": "EXAMINED",
                    "cell": {
                        "address": address,
                        "character": f"{cell.character:X}",
                        "wordmark": cell.wordmark,
                        "negative": cell.negative,
                    },
                }
            if action == "deposit":
                address = self._integer(body, "address", PANEL_SCRATCH_START, 255)
                character = self._integer(body, "character", 0, 15)
                self.machine.cpu.deposit_scratch(address, character)
                return {"result": "DEPOSITED", "snapshot": self.snapshot()}
            raise PanelError("UNKNOWN_CONTROL", "supported controls: key, register, meter, examine, deposit")

    @staticmethod
    def _integer(body: dict[str, Any], field: str, minimum: int, maximum: int) -> int:
        value = body.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise PanelError("BAD_CONTROL_VALUE", f"{field} must be an integer from {minimum} through {maximum}")
        return value
