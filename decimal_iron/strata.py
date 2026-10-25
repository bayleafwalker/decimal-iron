"""Visible, reversible protocol strata for the synthetic clearing path.

These byte layouts are project fixtures inspired by successive integration
eras. They are not copies of a real bank or historical clearing protocol.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .adapter import PaymentReceipt, TerminalPaymentAdapter
from .machine import MAX_PAYMENT_MINOR

_IDENTIFIER = re.compile(r"^[A-Z0-9_-]{1,32}$", re.ASCII)
_BANK_ID = re.compile(r"^[A-Z0-9_-]{1,8}$", re.ASCII)
_MEMBER = re.compile(r"^[A-Z][A-Z0-9]{1,7}$", re.ASCII)
HOST_RECORD_LENGTH = 96


@dataclass(frozen=True)
class PaymentInstruction:
    payment_id: str
    bank_id: str
    source: str
    destination: str
    amount_minor: int
    currency: str = "FIM"

    @classmethod
    def from_mapping(cls, value: object) -> "PaymentInstruction":
        if not isinstance(value, dict):
            raise ValueError("payment body must be a JSON object")
        allowed = {"payment_id", "bank_id", "source", "destination", "amount_minor", "currency"}
        if set(value) - allowed:
            raise ValueError("payment body contains unsupported fields")
        for field in ("payment_id", "bank_id", "source", "destination", "currency"):
            if not isinstance(value.get(field), str) or not value[field].isascii():
                raise ValueError(f"{field} must be an ASCII string")
        payment_id = value["payment_id"].upper()
        bank_id = value["bank_id"].upper()
        source = value["source"].upper()
        destination = value["destination"].upper()
        currency = value["currency"].upper()
        amount = value.get("amount_minor")
        if not _IDENTIFIER.fullmatch(payment_id):
            raise ValueError("payment_id must contain 1-32 ASCII letters, digits, _ or -")
        if not _BANK_ID.fullmatch(bank_id):
            raise ValueError("bank_id must contain 1-8 ASCII letters, digits, _ or -")
        if not _MEMBER.fullmatch(source) or not _MEMBER.fullmatch(destination):
            raise ValueError("source and destination must be 2-8 ASCII member-account characters")
        if source == destination:
            raise ValueError("source and destination must differ")
        if currency != "FIM":
            raise ValueError("currency must be FIM")
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= MAX_PAYMENT_MINOR:
            raise ValueError(f"amount_minor must be an integer from 1 through {MAX_PAYMENT_MINOR}")
        return cls(payment_id, bank_id, source, destination, amount, currency)

    def fields(self) -> dict[str, object]:
        return {
            "payment_id": self.payment_id,
            "bank_id": self.bank_id,
            "source": self.source,
            "destination": self.destination,
            "currency": self.currency,
            "amount_minor": self.amount_minor,
        }


@dataclass(frozen=True)
class ProtocolTrace:
    cloud_json: str
    clearing_xml: str
    host_record: str
    terminal_command: str
    host_checksum: str

    def summary(self) -> dict[str, object]:
        return {
            "layers": [
                {
                    "name": "cloud-json-v1",
                    "sha256": hashlib.sha256(self.cloud_json.encode("ascii")).hexdigest(),
                    "record": self.cloud_json,
                },
                {
                    "name": "xml-clearing-2001",
                    "sha256": hashlib.sha256(self.clearing_xml.encode("ascii")).hexdigest(),
                    "record": self.clearing_xml,
                },
                {
                    "name": "fixed-host-record-1982",
                    "length": len(self.host_record),
                    "checksum": self.host_checksum,
                    "record": self.host_record,
                },
                {"name": "terminal-24x80-v1", "command": self.terminal_command},
            ]
        }


def build_protocol_trace(instruction: PaymentInstruction) -> ProtocolTrace:
    """Translate one payment while preserving its identity and integer amount."""
    cloud = json.dumps(
        {"schema": "decimal-iron/payment.v1", **instruction.fields()},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    xml_root = ET.Element(
        "clearing-payment",
        {"version": "2001", "idempotency-key": instruction.payment_id},
    )
    for tag, field in (
        ("origin-bank", "bank_id"),
        ("debit-account", "source"),
        ("credit-account", "destination"),
        ("currency", "currency"),
        ("amount-minor", "amount_minor"),
    ):
        ET.SubElement(xml_root, tag).text = str(instruction.fields()[field])
    xml = ET.tostring(xml_root, encoding="unicode", short_empty_elements=True)

    prefix = (
        "P01"
        f"{instruction.bank_id:<8}"
        f"{instruction.payment_id:<32}"
        f"{instruction.source:<8}"
        f"{instruction.destination:<8}"
        f"{instruction.currency:<3}"
        f"{instruction.amount_minor:012d}"
    )
    if len(prefix) != 74:
        raise AssertionError("fixed host-record field map drifted")
    checksum = hashlib.sha256(prefix.encode("ascii")).hexdigest()[:16].upper()
    record = prefix + checksum + (" " * 6)
    command = (
        f"PAY {instruction.payment_id} {instruction.source} {instruction.destination} "
        f"{instruction.currency} {instruction.amount_minor}"
    )
    return ProtocolTrace(cloud, xml, record, command, checksum)


def decode_host_record(record: str) -> PaymentInstruction:
    """Decode and verify the fixed record before handing it to the terminal layer."""
    if not isinstance(record, str) or len(record) != HOST_RECORD_LENGTH or not record.isascii():
        raise ValueError(f"host record must be exactly {HOST_RECORD_LENGTH} ASCII columns")
    prefix, checksum = record[:74], record[74:90]
    if record[90:] != " " * 6:
        raise ValueError("host record reserved columns must be blank")
    expected = hashlib.sha256(prefix.encode("ascii")).hexdigest()[:16].upper()
    if checksum != expected:
        raise ValueError("host record checksum mismatch")
    if prefix[:3] != "P01":
        raise ValueError("unsupported fixed host record type or version")
    amount_text = prefix[62:74]
    if not amount_text.isdigit():
        raise ValueError("host record amount must be twelve decimal digits")
    return PaymentInstruction.from_mapping(
        {
            "bank_id": prefix[3:11].rstrip(),
            "payment_id": prefix[11:43].rstrip(),
            "source": prefix[43:51].rstrip(),
            "destination": prefix[51:59].rstrip(),
            "currency": prefix[59:62].rstrip(),
            "amount_minor": int(amount_text),
        }
    )


class ProtocolPipeline:
    """Expose protocol translations, then submit only through the terminal adapter."""

    def __init__(self, adapter: TerminalPaymentAdapter):
        self.adapter = adapter

    def submit(self, instruction: PaymentInstruction) -> tuple[PaymentReceipt, ProtocolTrace]:
        trace = build_protocol_trace(instruction)
        decoded = decode_host_record(trace.host_record)
        if decoded != instruction:
            raise ValueError("fixed host record changed payment identity or fields")
        receipt = self.adapter.post_payment(
            decoded.payment_id,
            decoded.source,
            decoded.destination,
            decoded.amount_minor,
            currency=decoded.currency,
        )
        return receipt, trace
