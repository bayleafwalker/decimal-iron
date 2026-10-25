"""Bounded synthetic member-bank payment producer for local and cluster demos."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from .strata import PaymentInstruction


def _request(url: str, *, method: str = "GET", body: object | None = None, timeout: float = 8.0) -> tuple[int, dict[str, object]]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("ascii")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except (ValueError, json.JSONDecodeError):
            payload = {"error": str(exc)}
        return exc.code, payload


def run_synthetic_bank(
    *,
    gateway_url: str,
    bank_id: str,
    max_requests: int = 12,
    interval_seconds: float = 2.0,
    seed: str = "decimal-iron",
    members: tuple[str, ...] = ("FI01", "FI02", "FI03", "FI04"),
    idle_seconds: float = 0.0,
    wait_for_open_seconds: float = 0.0,
) -> dict[str, int]:
    """Send a finite, reproducible traffic batch; optionally remain idle for a pod."""
    bank_id = bank_id.upper()
    if not 1 <= max_requests <= 10_000:
        raise ValueError("max_requests must be between 1 and 10000")
    if not 0 <= interval_seconds <= 3600:
        raise ValueError("interval_seconds must be between 0 and 3600")
    if not 0 <= idle_seconds <= 86_400:
        raise ValueError("idle_seconds must be between 0 and 86400")
    if not 0 <= wait_for_open_seconds <= 86_400:
        raise ValueError("wait_for_open_seconds must be between 0 and 86400")
    if len(members) < 2:
        raise ValueError("at least two participant accounts are required")
    rng = random.Random(f"{seed}:{bank_id}")
    accepted = rejected = unknown = 0
    base = gateway_url.rstrip("/")
    if wait_for_open_seconds:
        deadline = time.monotonic() + wait_for_open_seconds
        while True:
            status_code, status = _request(f"{base}/readyz")
            if status_code == 200 and status.get("processor_phase") == "OPEN":
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("processor did not reach OPEN before the synthetic bank wait expired")
            time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))
    for ordinal in range(1, max_requests + 1):
        source_index = (ordinal - 1 + sum(bank_id.encode("ascii"))) % len(members)
        source = members[source_index]
        destination = members[(source_index + 1) % len(members)]
        payment_id = f"{bank_id}-{ordinal:012d}"
        request = PaymentInstruction(
            payment_id=payment_id,
            bank_id=bank_id,
            source=source,
            destination=destination,
            amount_minor=rng.randint(100, 5_000),
        )
        payload = request.fields()
        response: dict[str, object] = {}
        for attempt in range(4):
            status_code, response = _request(f"{base}/payments", method="POST", body=payload)
            if status_code == 202:
                break
            if status_code != 503 or attempt == 3:
                rejected += 1
                break
            time.sleep(0.25 * (2**attempt))
        else:
            rejected += 1
        if response.get("status") == "POSTED":
            accepted += 1
        elif response.get("status") == "REJECTED":
            rejected += 1
        elif response.get("status") == "UNKNOWN_OUTCOME":
            unknown += 1
        elif status_code == 202:
            # The queue acknowledgement is not a posting receipt. Poll only the
            # gateway projection; it never reads the processor ledger.
            final: dict[str, object] | None = None
            for _ in range(120):
                time.sleep(0.25)
                _, final = _request(f"{base}/payments/{quote(payment_id)}")
                if final.get("status") in {"POSTED", "REJECTED", "UNKNOWN_OUTCOME", "FAILED"}:
                    break
            if final and final.get("status") == "POSTED":
                accepted += 1
            elif final and final.get("status") == "REJECTED":
                rejected += 1
            else:
                unknown += 1
        print(json.dumps({"bank_id": bank_id, "payment_id": payment_id, "result": response.get("status", response.get("error", "UNKNOWN"))}, sort_keys=True))
        if ordinal < max_requests and interval_seconds:
            time.sleep(interval_seconds)
    summary = {"sent": max_requests, "posted": accepted, "rejected": rejected, "unknown": unknown}
    print(json.dumps({"bank_id": bank_id, **summary}, sort_keys=True))
    if idle_seconds:
        time.sleep(idle_seconds)
    return summary
