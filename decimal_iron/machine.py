"""Deterministic software reference machine for synthetic FIM clearing."""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .journal import Journal, JournalCorruption

MAX_PAYMENT_MINOR = 5_000_000  # FIM 50,000.00; hard processor limit.
DEFAULT_OVERDRAFT_LIMIT_MINOR = 100_000  # FIM 1,000.00 per member.
RESERVED_ACCOUNTS = {"SETTLEMENT"}
_IDENTIFIER = re.compile(r"^[A-Z0-9_-]{1,32}$")
_MEMBER = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
_PHASES = {"CLOSED", "OPEN", "CUT-OFF", "SETTLED"}
_KEY_POSITIONS = {"CLOSED", "OPEN", "CUT-OFF", "SETTLE"}


class RuleViolation(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CommandResult:
    code: str
    message: str
    data: dict[str, Any]

    def terminal_line(self) -> str:
        if self.code == "ERROR":
            return f"RESULT ERROR {self.data['error_code']}"
        if self.code in {"POSTED", "DUPLICATE"}:
            return f"RESULT {self.code} {self.data['id']} SEQ {self.data['seq']:06d}"
        if self.code == "INQUIRY":
            if not self.data["found"]:
                return f"RESULT INQUIRY NOT_FOUND {self.data['id']}"
            return f"RESULT INQUIRY POSTED {self.data['id']} SEQ {self.data['seq']:06d}"
        if self.code == "REVERSED":
            return f"RESULT REVERSED {self.data['reversal_id']} SEQ {self.data['seq']:06d}"
        if self.code == "REVERSAL_DUPLICATE":
            return f"RESULT REVERSAL_DUPLICATE {self.data['reversal_id']} SEQ {self.data['seq']:06d}"
        if self.code in {"STATUS", "REPORT"}:
            return f"RESULT {self.code} {self.data.get('phase', self.data.get('seq', 'OK'))}"
        return f"RESULT {self.code}"


def format_minor(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    value = abs(amount)
    whole, fraction = divmod(value, 100)
    return f"{sign}{whole:,}.{fraction:02d} FIM"


class DecimalMachine:
    """Journal-first ledger and guarded business-day state machine.

    The journal is the durable authority. Positions, idempotency indexes,
    switch state and the reconciliation register are projections rebuilt by
    replaying it at startup.
    """

    def __init__(
        self,
        journal_path: str | Path | None = None,
        *,
        overdraft_limit_minor: int = DEFAULT_OVERDRAFT_LIMIT_MINOR,
    ):
        if overdraft_limit_minor < 0:
            raise ValueError("overdraft limit must be non-negative")
        self.journal = Journal(journal_path)
        self.overdraft_limit_minor = overdraft_limit_minor
        self._lock = threading.RLock()
        self.phase = "CLOSED"
        self.key_position = "CLOSED"
        self.business_date: str | None = None
        self.positions: dict[str, int] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.reversals: dict[str, dict[str, Any]] = {}
        self.reversed_originals: set[str] = set()
        self.settlement_net_before: dict[str, int] = {}
        self.external_discrepancy_minor = 0
        self.reconciliation_break_minor = 0
        self.reconciliation_current = False
        self._replay()

    @property
    def beacon_on(self) -> bool:
        """The red output is driven only by the reconciliation register."""
        return self.reconciliation_break_minor != 0

    @property
    def journal_head(self) -> str:
        return self.journal.head

    def close(self) -> None:
        """Release the exclusive lock held by this machine's file-backed journal."""
        self.journal.close()

    def _replay(self) -> None:
        with self._lock:
            for entry in self.journal.entries:
                self._apply(entry)

    def _append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self.journal.append(kind, payload)
        self._apply(entry)
        return entry

    def _apply(self, entry: dict[str, Any]) -> None:
        kind = entry["kind"]
        payload = entry["payload"]
        if kind == "KEY_SWITCHED":
            self.key_position = payload["position"]
        elif kind == "DAY_OPENED":
            self.business_date = payload["business_date"]
            self.phase = "OPEN"
            self.settlement_net_before = {}
            self.external_discrepancy_minor = 0
            self.reconciliation_break_minor = 0
            self.reconciliation_current = False
        elif kind == "PAYMENT_POSTED":
            source, destination = payload["source"], payload["destination"]
            amount = payload["amount_minor"]
            self.positions[source] = self.positions.get(source, 0) - amount
            self.positions[destination] = self.positions.get(destination, 0) + amount
            self.transactions[payload["id"]] = {**payload, "seq": entry["seq"]}
            self.reconciliation_current = False
        elif kind == "PAYMENT_REVERSED":
            original = self.transactions[payload["original_id"]]
            amount = payload["amount_minor"]
            self.positions[original["source"]] = self.positions.get(original["source"], 0) + amount
            self.positions[original["destination"]] = self.positions.get(original["destination"], 0) - amount
            self.reversals[payload["reversal_id"]] = {**payload, "seq": entry["seq"]}
            self.reversed_originals.add(payload["original_id"])
            self.reconciliation_current = False
        elif kind == "DAY_CUTOFF":
            self.phase = "CUT-OFF"
        elif kind == "DAY_SETTLED":
            self.settlement_net_before = dict(payload["net_positions"])
            for item in payload["adjustments"]:
                member, delta = item["member"], item["delta_minor"]
                self.positions[member] = self.positions.get(member, 0) + delta
                self.positions["SETTLEMENT"] = self.positions.get("SETTLEMENT", 0) - delta
            self.phase = "SETTLED"
            self.reconciliation_current = False
        elif kind == "RECON_BREAK_INJECTED":
            self.external_discrepancy_minor += payload["amount_minor"]
            self.reconciliation_current = False
        elif kind == "RECON_BREAK_CLEARED":
            self.external_discrepancy_minor = 0
            self.reconciliation_current = False
        elif kind == "RECONCILED":
            self.reconciliation_break_minor = payload["difference_minor"]
            self.reconciliation_current = True
        elif kind == "DAY_CLOSED":
            self.phase = "CLOSED"
        else:
            raise JournalCorruption(f"unknown event kind {kind!r} at sequence {entry['seq']}")

    @staticmethod
    def _require_identifier(value: str, field: str) -> str:
        value = value.upper()
        if not _IDENTIFIER.fullmatch(value):
            raise RuleViolation("BAD_IDENTIFIER", f"{field} must use 1-32 ASCII letters, digits, _ or -")
        return value

    @staticmethod
    def _require_member(value: str) -> str:
        value = value.upper()
        if not _MEMBER.fullmatch(value) or value in RESERVED_ACCOUNTS:
            raise RuleViolation("BAD_MEMBER", f"invalid member account {value!r}")
        return value

    def command(self, command: str) -> CommandResult:
        """Execute one terminal command and return a stable, printable result."""
        with self._lock:
            try:
                return self._dispatch(command.strip())
            except RuleViolation as exc:
                return CommandResult("ERROR", exc.message, {"error_code": exc.code})
            except (ValueError, OverflowError):
                return CommandResult("ERROR", "invalid command argument", {"error_code": "BAD_ARGUMENT"})

    def _dispatch(self, command: str) -> CommandResult:
        if not command:
            return CommandResult("READY", "ready", {})
        parts = command.split(maxsplit=6)
        operation = parts[0].upper()
        if operation == "HELP":
            return CommandResult("HELP", "command list displayed", {})
        if operation == "KEY" and len(parts) == 2:
            position = parts[1].upper()
            if position not in _KEY_POSITIONS:
                raise RuleViolation("BAD_KEY_POSITION", "key position must be CLOSED, OPEN, CUT-OFF or SETTLE")
            entry = self._append("KEY_SWITCHED", {"position": position})
            return CommandResult("KEY", f"day key moved to {position}", {"seq": entry["seq"], "position": position})
        if operation == "OPEN" and len(parts) == 2:
            return self._open_day(parts[1])
        if operation == "PAY" and len(parts) >= 6:
            return self._post_payment(parts)
        if operation == "INQUIRE" and len(parts) == 2:
            payment_id = self._require_identifier(parts[1], "payment id")
            transaction = self.transactions.get(payment_id)
            return CommandResult(
                "INQUIRY",
                "payment found" if transaction else "payment not found",
                {
                    "id": payment_id,
                    "found": transaction is not None,
                    "seq": transaction["seq"] if transaction else None,
                    "transaction": transaction,
                },
            )
        if operation == "REV" and len(parts) >= 3:
            return self._reverse(parts)
        if operation in {"CUTOFF", "CUT-OFF"} and len(parts) == 1:
            if self.phase != "OPEN" or self.key_position != "CUT-OFF":
                raise RuleViolation("TRANSITION_GUARD", "set KEY CUT-OFF while the day is OPEN before requesting CUTOFF")
            entry = self._append("DAY_CUTOFF", {"business_date": self.business_date})
            return CommandResult("CUTOFF", "ordinary postings are now closed", {"seq": entry["seq"]})
        if operation == "SETTLE" and len(parts) == 1:
            return self._settle()
        if operation in {"RECON", "RECONCILE"} and len(parts) == 1:
            return self._reconcile()
        if operation == "BREAK" and len(parts) == 2:
            return self._inject_break(parts[1])
        if operation in {"CLEARBREAK", "CLEAR-BREAK"} and len(parts) == 1:
            if self.phase not in {"SETTLED", "CLOSED"}:
                raise RuleViolation("DAY_NOT_SETTLED", "reconciliation input can be changed only after settlement")
            entry = self._append("RECON_BREAK_CLEARED", {"business_date": self.business_date})
            return CommandResult("BREAK_CLEARED", "synthetic statement discrepancy cleared", {"seq": entry["seq"]})
        if operation == "REPORT" and len(parts) == 1:
            if self.phase not in {"SETTLED", "CLOSED"}:
                raise RuleViolation("DAY_NOT_SETTLED", "closing report is available after settlement")
            return CommandResult("REPORT", "closing report is ready", {"phase": self.phase, "seq": len(self.journal.entries)})
        if operation == "CLOSE" and len(parts) == 1:
            return self._close_day()
        if operation == "STATUS" and len(parts) == 1:
            return CommandResult("STATUS", "machine status", {"phase": self.phase})
        raise RuleViolation("UNKNOWN_COMMAND", "unknown command; type HELP")

    def _open_day(self, day_text: str) -> CommandResult:
        if self.phase != "CLOSED" or self.key_position != "OPEN":
            raise RuleViolation("TRANSITION_GUARD", "set KEY OPEN while the machine is CLOSED before requesting OPEN")
        try:
            parsed = date.fromisoformat(day_text)
        except ValueError as exc:
            raise RuleViolation("BAD_DATE", "business date must be YYYY-MM-DD") from exc
        if parsed.isoformat() != day_text:
            raise RuleViolation("BAD_DATE", "business date must be YYYY-MM-DD")
        if self.business_date is not None and parsed <= date.fromisoformat(self.business_date):
            raise RuleViolation("BAD_DATE_ORDER", "business date must be later than the last closed date")
        entry = self._append("DAY_OPENED", {"business_date": day_text})
        return CommandResult("OPENED", f"business day {day_text} is open", {"seq": entry["seq"], "business_date": day_text})

    def _post_payment(self, parts: list[str]) -> CommandResult:
        # PAY id source destination currency amount_minor [override reason]
        payment_id = self._require_identifier(parts[1], "payment id")
        source = self._require_member(parts[2])
        destination = self._require_member(parts[3])
        currency = parts[4].upper()
        amount_text = parts[5]
        override_reason = parts[6].strip() if len(parts) == 7 else ""
        if currency != "FIM":
            raise RuleViolation("UNSUPPORTED_CURRENCY", "the reference machine posts FIM only")
        if source == destination:
            raise RuleViolation("SAME_ACCOUNT", "source and destination must differ")
        if not amount_text.isascii() or not amount_text.isdigit():
            raise RuleViolation("BAD_AMOUNT", "amount must be a positive integer number of penni")
        amount = int(amount_text)
        if not 1 <= amount <= MAX_PAYMENT_MINOR:
            raise RuleViolation("HARD_AMOUNT_LIMIT", f"amount must be between 1 and {MAX_PAYMENT_MINOR} penni")
        if len(override_reason) > 80:
            raise RuleViolation("OVERRIDE_REASON_TOO_LONG", "override reason is limited to 80 characters")
        identity = {
            "id": payment_id,
            "source": source,
            "destination": destination,
            "currency": currency,
            "amount_minor": amount,
            "override_reason": override_reason,
        }
        existing = self.transactions.get(payment_id)
        if existing is not None:
            fields = ("source", "destination", "currency", "amount_minor", "override_reason")
            if any(existing[field] != identity[field] for field in fields):
                raise RuleViolation("IDEMPOTENCY_CONFLICT", "payment id already exists with a different request")
            return CommandResult("DUPLICATE", "retry matched the original durable posting", {"id": payment_id, "seq": existing["seq"]})
        if self.phase != "OPEN":
            raise RuleViolation("DAY_NOT_OPEN", "new payments are accepted only while the business day is OPEN")
        if self.positions.get(source, 0) - amount < -self.overdraft_limit_minor and not override_reason.strip():
            raise RuleViolation("OVERRIDE_REASON_REQUIRED", "member debit limit exceeded; provide a non-empty override reason")
        entry = self._append("PAYMENT_POSTED", {**identity, "business_date": self.business_date})
        return CommandResult("POSTED", "payment durably posted", {"id": payment_id, "seq": entry["seq"]})

    def _reverse(self, parts: list[str]) -> CommandResult:
        original_id = self._require_identifier(parts[1], "original payment id")
        reversal_id = self._require_identifier(parts[2], "reversal id")
        reason = " ".join(parts[3:]).strip() if len(parts) >= 4 else ""
        if len(reason) > 80:
            raise RuleViolation("OVERRIDE_REASON_TOO_LONG", "reversal reason is limited to 80 characters")
        existing = self.reversals.get(reversal_id)
        if existing is not None:
            if existing["original_id"] != original_id or existing["reason"] != reason:
                raise RuleViolation("IDEMPOTENCY_CONFLICT", "reversal id already exists with a different request")
            return CommandResult("REVERSAL_DUPLICATE", "retry matched the original reversal", {"reversal_id": reversal_id, "seq": existing["seq"]})
        if self.phase != "OPEN":
            raise RuleViolation("DAY_NOT_OPEN", "new reversals are accepted only while the business day is OPEN")
        original = self.transactions.get(original_id)
        if original is None:
            raise RuleViolation("ORIGINAL_NOT_FOUND", "original payment does not exist")
        if original_id in self.reversed_originals:
            raise RuleViolation("ALREADY_REVERSED", "payment already has a compensating reversal")
        payload = {
            "original_id": original_id,
            "reversal_id": reversal_id,
            "amount_minor": original["amount_minor"],
            "reason": reason,
            "business_date": self.business_date,
        }
        entry = self._append("PAYMENT_REVERSED", payload)
        return CommandResult("REVERSED", "compensating journal record posted", {"reversal_id": reversal_id, "seq": entry["seq"]})

    def _settle(self) -> CommandResult:
        if self.phase != "CUT-OFF" or self.key_position != "SETTLE":
            raise RuleViolation("TRANSITION_GUARD", "set KEY SETTLE after CUTOFF before requesting SETTLE")
        members = sorted(name for name in self.positions if name != "SETTLEMENT")
        total = sum(self.positions.get(name, 0) for name in members)
        if total != 0:
            raise RuleViolation("LEDGER_NOT_CONSERVED", "participant positions do not sum to zero")
        net = {name: self.positions.get(name, 0) for name in members}
        adjustments = [{"member": name, "delta_minor": -net[name]} for name in members if net[name] != 0]
        entry = self._append(
            "DAY_SETTLED",
            {"business_date": self.business_date, "net_positions": net, "adjustments": adjustments},
        )
        return CommandResult("SETTLED", "net positions settled to zero", {"seq": entry["seq"], "participants": len(members)})

    def _inject_break(self, amount_text: str) -> CommandResult:
        if self.phase not in {"SETTLED", "CLOSED"}:
            raise RuleViolation("DAY_NOT_SETTLED", "reconciliation input can be changed only after settlement")
        if not re.fullmatch(r"-?[0-9]+", amount_text, flags=re.ASCII):
            raise RuleViolation("BAD_AMOUNT", "break amount must be an integer number of penni")
        amount = int(amount_text)
        if amount == 0:
            raise RuleViolation("BAD_AMOUNT", "break amount must be nonzero")
        entry = self._append("RECON_BREAK_INJECTED", {"amount_minor": amount, "business_date": self.business_date})
        return CommandResult("BREAK_INJECTED", "synthetic external statement discrepancy recorded", {"seq": entry["seq"], "amount_minor": amount})

    def _reconcile(self) -> CommandResult:
        if self.phase not in {"SETTLED", "CLOSED"}:
            raise RuleViolation("DAY_NOT_SETTLED", "reconciliation is available only after settlement")
        ledger_total = sum(self.positions.values())
        difference = ledger_total + self.external_discrepancy_minor
        entry = self._append(
            "RECONCILED",
            {
                "business_date": self.business_date,
                "ledger_total_minor": ledger_total,
                "external_discrepancy_minor": self.external_discrepancy_minor,
                "difference_minor": difference,
            },
        )
        state = "BREAK" if difference else "CLEAR"
        return CommandResult("RECONCILED", f"reconciliation {state.lower()}", {"seq": entry["seq"], "difference_minor": difference})

    def _close_day(self) -> CommandResult:
        if self.phase != "SETTLED" or self.key_position != "CLOSED":
            raise RuleViolation("TRANSITION_GUARD", "set KEY CLOSED after settlement before requesting CLOSE")
        if not self.reconciliation_current:
            raise RuleViolation("RECONCILIATION_REQUIRED", "run RECONCILE against the current settled state before CLOSE")
        if self.reconciliation_break_minor != 0:
            raise RuleViolation("RECONCILIATION_BREAK", "day cannot close while the reconciliation difference is nonzero")
        entry = self._append("DAY_CLOSED", {"business_date": self.business_date})
        return CommandResult("CLOSED", "business day closed", {"seq": entry["seq"]})

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "phase": self.phase,
                "business_date": self.business_date or "---- -- --",
                "key_position": self.key_position,
                "beacon_on": self.beacon_on,
                "reconciliation_break_minor": self.reconciliation_break_minor,
                "reconciliation_current": self.reconciliation_current,
                "positions": dict(sorted(self.positions.items())),
                "journal_events": len(self.journal.entries),
                "journal_head": self.journal.head,
            }

    def report_text(self) -> str:
        """Build a stable closing artifact without wall-clock metadata."""
        with self._lock:
            date_text = self.business_date or "NOT OPENED"
            payments = [p for p in self.transactions.values() if p.get("business_date") == self.business_date]
            reversals = [r for r in self.reversals.values() if r.get("business_date") == self.business_date]
            lines = [
                "DECIMAL IRON - CLOSING REPORT",
                f"Business date: {date_text}",
                f"Processor phase: {self.phase}",
                "Currency: FIM (integer penni; 100 penni = 1 FIM)",
                f"Journal events: {len(self.journal.entries)}",
                f"Journal head: sha256:{self.journal.head}",
                f"Payments posted: {len(payments)}",
                f"Compensating reversals: {len(reversals)}",
                "",
                "Net positions immediately before settlement:",
            ]
            if self.settlement_net_before:
                lines.extend(f"  {member:<10} {format_minor(amount)}" for member, amount in sorted(self.settlement_net_before.items()))
            else:
                lines.append("  (none)")
            lines.extend(["", "Positions after settlement:"])
            visible = {name: amount for name, amount in self.positions.items() if name != "SETTLEMENT"}
            if visible:
                lines.extend(f"  {member:<10} {format_minor(amount)}" for member, amount in sorted(visible.items()))
            else:
                lines.append("  (none)")
            lines.extend(
                [
                    "",
                    f"Reconciliation difference: {format_minor(self.reconciliation_break_minor)}",
                    f"Reconciliation status: {'CURRENT' if self.reconciliation_current else 'NOT CURRENT'}",
                    f"Red beacon: {'ON' if self.beacon_on else 'OFF'}",
                    "",
                ]
            )
            return "\n".join(lines)

    def report_digest(self) -> str:
        return hashlib.sha256(self.report_text().encode("ascii")).hexdigest()


__all__ = ["CommandResult", "DecimalMachine", "JournalCorruption", "RuleViolation", "format_minor"]
