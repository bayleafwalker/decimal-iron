"""Exact, bounded FIM-to-EUR statement conversion; never a posting ledger.

The fixed rate is 1 EUR = 5.94573 FIM. Integer penni therefore convert to
integer euro cents by multiplying by 100000 / 594573, rounded to nearest
cent with exact halves away from zero. The scenario compares separately
rounded line items with a rounded aggregate and declares the residue.
"""

from __future__ import annotations

from typing import Iterable

RATE_NUMERATOR = 100_000
RATE_DENOMINATOR = 594_573
ROUNDING_POLICY = "nearest-cent-half-away-from-zero-v1"


def fim_minor_to_eur_minor(amount_minor: int) -> int:
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise ValueError("FIM amount must be an integer number of penni")
    numerator = abs(amount_minor) * RATE_NUMERATOR
    result = (2 * numerator + RATE_DENOMINATOR) // (2 * RATE_DENOMINATOR)
    return -result if amount_minor < 0 else result


def prepare_euro_statement(amounts_fim_minor: Iterable[int], treatment: str) -> dict[str, object]:
    """Calculate a statement from source posting amounts, without an oracle."""
    if treatment not in {"OMIT", "ACCOUNT"}:
        raise ValueError("residue treatment must be OMIT or ACCOUNT")
    source = list(amounts_fim_minor)
    converted = [fim_minor_to_eur_minor(amount) for amount in source]
    item_total = sum(converted)
    aggregate = fim_minor_to_eur_minor(sum(source))
    residue = item_total - aggregate
    adjustment = -residue if treatment == "ACCOUNT" else 0
    return {
        "source_currency": "FIM",
        "source_unit": "penni",
        "currency": "EUR",
        "unit": "cent",
        "rate_fim_per_eur": "5.94573",
        "rounding_policy": ROUNDING_POLICY,
        "source_amounts_minor": source,
        "item_amounts_minor": converted,
        "item_total_minor": item_total,
        "aggregate_total_minor": aggregate,
        "residue_minor": residue,
        "residue_treatment": treatment,
        "rounding_adjustment_minor": adjustment,
    }


def statement_difference(statement: dict[str, object]) -> int:
    """Compare two EUR controls; FIM balances never enter this subtraction."""
    if statement.get("currency") != "EUR" or statement.get("unit") != "cent":
        raise ValueError("statement must declare EUR cents")
    items = statement["item_amounts_minor"]
    adjustment = statement["rounding_adjustment_minor"]
    aggregate = statement["aggregate_total_minor"]
    if not isinstance(items, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in items):
        raise ValueError("statement items must be integer euro cents")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (adjustment, aggregate)):
        raise ValueError("statement controls must be integer euro cents")
    return sum(items) + adjustment - aggregate
