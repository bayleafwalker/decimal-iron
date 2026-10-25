"""A serialized payment client that knows only the terminal byte stream."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from .protocol import result_line
from .terminal import TerminalSession


class TerminalTimeout(TimeoutError):
    pass


class ByteTerminal(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float = 2.0) -> bytes: ...


class MemoryTerminalChannel:
    """Local terminal transport used by the adapter and deterministic demos."""

    def __init__(self, session: TerminalSession):
        self.session = session
        self.session.take_output()  # discard the initial banner before first request

    def write(self, data: bytes) -> None:
        self.session.feed(data)

    def read(self, timeout: float = 2.0) -> bytes:
        del timeout
        data = self.session.take_output()
        if not data:
            raise TerminalTimeout("terminal did not return a screen frame")
        return data


class PaymentRejected(RuntimeError):
    pass


class UnknownOutcome(RuntimeError):
    """The terminal could not prove whether a submitted payment was accepted."""


@dataclass(frozen=True)
class PaymentReceipt:
    payment_id: str
    journal_sequence: int
    resolution: str


class TerminalPaymentAdapter:
    """Single-cursor payment adapter; it has no machine or journal reference."""

    def __init__(self, terminal: ByteTerminal):
        self.terminal = terminal
        self._cursor = threading.Lock()

    def _exchange(self, command: str) -> str:
        if "\r" in command or "\n" in command:
            raise ValueError("terminal commands must be a single line")
        self.terminal.write(command.encode("ascii") + b"\r")
        return result_line(self.terminal.read())

    def processor_status(self) -> str:
        """Read the phase through the same serialized operator terminal cursor."""
        with self._cursor:
            response = self._exchange("STATUS")
        parts = response.split()
        if len(parts) != 3 or parts[:2] != ["RESULT", "STATUS"]:
            raise UnknownOutcome(f"unexpected processor status response: {response}")
        return parts[2]

    @staticmethod
    def _receipt(line: str, payment_id: str, resolution: str) -> PaymentReceipt:
        parts = line.split()
        if len(parts) < 5 or parts[0:3] != ["RESULT", "INQUIRY", "POSTED"] or parts[3] != payment_id:
            raise UnknownOutcome(f"unexpected inquiry response: {line}")
        if parts[4] != "SEQ" or len(parts) != 6 or not parts[5].isdigit():
            raise UnknownOutcome(f"malformed inquiry response: {line}")
        return PaymentReceipt(payment_id, int(parts[5]), resolution)

    def post_payment(
        self,
        payment_id: str,
        source: str,
        destination: str,
        amount_minor: int,
        *,
        currency: str = "FIM",
        override_reason: str = "",
    ) -> PaymentReceipt:
        """Post once, resolving lost replies with inquiry and same-key retry."""
        payment_id = payment_id.upper()
        command = f"PAY {payment_id} {source.upper()} {destination.upper()} {currency.upper()} {amount_minor}"
        if override_reason:
            if "\r" in override_reason or "\n" in override_reason:
                raise ValueError("override reason must be one line")
            command += f" {override_reason}"
        with self._cursor:
            try:
                response = self._exchange(command)
                return self._payment_response(response, payment_id, "ACKNOWLEDGED")
            except (OSError, ValueError, UnknownOutcome) as exc:
                return self._recover(payment_id, command, exc)

    def _payment_response(self, response: str, payment_id: str, resolution: str) -> PaymentReceipt:
        parts = response.split()
        if len(parts) == 5 and parts[:2] == ["RESULT", "POSTED"] and parts[2] == payment_id and parts[3] == "SEQ" and parts[4].isdigit():
            return PaymentReceipt(payment_id, int(parts[4]), resolution)
        if len(parts) == 5 and parts[:2] == ["RESULT", "DUPLICATE"] and parts[2] == payment_id and parts[3] == "SEQ" and parts[4].isdigit():
            return PaymentReceipt(payment_id, int(parts[4]), "IDEMPOTENT_DUPLICATE")
        if response.startswith("RESULT ERROR "):
            raise PaymentRejected(response.removeprefix("RESULT ERROR "))
        raise UnknownOutcome(f"unexpected payment response: {response}")

    def _recover(self, payment_id: str, command: str, original_error: Exception) -> PaymentReceipt:
        try:
            inquiry = self._exchange(f"INQUIRE {payment_id}")
        except (OSError, ValueError, UnknownOutcome) as exc:
            raise UnknownOutcome(f"inquiry also timed out for {payment_id}") from exc
        if inquiry.startswith(f"RESULT INQUIRY POSTED {payment_id} "):
            return self._receipt(inquiry, payment_id, "RECOVERED_BY_INQUIRY")
        if inquiry != f"RESULT INQUIRY NOT_FOUND {payment_id}":
            raise UnknownOutcome(f"inquiry could not resolve {payment_id}: {inquiry}") from original_error
        try:
            response = self._exchange(command)  # same identity and payload; never mint a new id
            return self._payment_response(response, payment_id, "RETRIED_AFTER_NOT_FOUND")
        except (OSError, ValueError, UnknownOutcome) as retry_error:
            try:
                inquiry = self._exchange(f"INQUIRE {payment_id}")
            except (OSError, ValueError, UnknownOutcome) as inquiry_error:
                raise UnknownOutcome(f"outcome remains unknown for {payment_id}") from inquiry_error
            if inquiry.startswith(f"RESULT INQUIRY POSTED {payment_id} "):
                return self._receipt(inquiry, payment_id, "RECOVERED_AFTER_RETRY")
            if inquiry == f"RESULT INQUIRY NOT_FOUND {payment_id}":
                raise UnknownOutcome(f"payment {payment_id} was not found after retry") from retry_error
            raise UnknownOutcome(f"inquiry could not resolve {payment_id}: {inquiry}") from retry_error
