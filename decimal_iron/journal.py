"""Append-only, hash-chained JSONL journal with deterministic replay input."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class JournalCorruption(RuntimeError):
    pass


class Journal:
    """A durable journal; each accepted event is fsynced before acknowledgement."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict[str, Any]] = []
        self.head = GENESIS
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        previous = GENESIS
        loaded: list[dict[str, Any]] = []
        raw_lines = self.path.read_bytes().splitlines()
        for expected_seq, raw in enumerate(raw_lines, start=1):
            if not raw:
                raise JournalCorruption(f"empty journal record at line {expected_seq}")
            try:
                entry = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalCorruption(f"invalid JSON at journal line {expected_seq}") from exc
            supplied_hash = entry.pop("hash", None)
            if entry.get("seq") != expected_seq or entry.get("prev_hash") != previous:
                raise JournalCorruption(f"broken journal sequence or chain at line {expected_seq}")
            calculated = hashlib.sha256(canonical_json(entry)).hexdigest()
            if supplied_hash != calculated:
                raise JournalCorruption(f"journal hash mismatch at line {expected_seq}")
            entry["hash"] = supplied_hash
            loaded.append(entry)
            previous = supplied_hash
        self.entries = loaded
        self.head = previous

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "seq": len(self.entries) + 1,
            "kind": kind,
            "payload": payload,
            "prev_hash": self.head,
        }
        digest = hashlib.sha256(canonical_json(body)).hexdigest()
        entry = {**body, "hash": digest}
        encoded = canonical_json(entry) + b"\n"
        if self.path is not None:
            fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            try:
                offset = 0
                while offset < len(encoded):
                    offset += os.write(fd, encoded[offset:])
                os.fsync(fd)
            finally:
                os.close(fd)
        self.entries.append(entry)
        self.head = digest
        return entry
