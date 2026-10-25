"""Bounded, durable delivery gateway whose only processor path is the terminal."""

from __future__ import annotations

import hashlib
import json
import queue
import sqlite3
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .adapter import PaymentRejected, TerminalPaymentAdapter, UnknownOutcome
from .strata import PaymentInstruction, ProtocolPipeline, ProtocolTrace, build_protocol_trace
from .websocket_client import WebSocketTerminal


@dataclass(frozen=True)
class _QueuedPayment:
    payment_id: str
    instruction: PaymentInstruction
    trace: ProtocolTrace


class GatewayService:
    """Persistent outbox with a bounded pending queue and one terminal worker.

    The SQLite file stores delivery state only. Accepted postings, balances,
    reversals and business-day state remain solely in the processor journal.
    """

    def __init__(self, adapter: TerminalPaymentAdapter, *, max_queue: int = 32, state_path: str | Path | None = None):
        if max_queue < 1:
            raise ValueError("max_queue must be positive")
        self.max_queue = max_queue
        self.pipeline = ProtocolPipeline(adapter)
        self._queue: queue.Queue[_QueuedPayment] = queue.Queue(maxsize=max_queue)
        self._lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._closing = False
        self._close_db_when_worker_exits = False
        self._db_closed = False
        if state_path is not None:
            Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(state_path) if state_path is not None else ":memory:", check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                request_json TEXT NOT NULL,
                status TEXT NOT NULL,
                receipt_json TEXT,
                trace_json TEXT NOT NULL,
                error TEXT
            )"""
        )
        self._db.execute("UPDATE payments SET status='QUEUED' WHERE status='PROCESSING'")
        self._db.commit()
        self._thread: threading.Thread | None = None
        with self._lock:
            for payment_id, request_json, trace_json in self._db.execute(
                "SELECT payment_id, request_json, trace_json FROM payments WHERE status='QUEUED' ORDER BY rowid"
            ):
                instruction = PaymentInstruction.from_mapping(json.loads(request_json))
                del trace_json
                trace = build_protocol_trace(instruction)
                try:
                    self._queue.put_nowait(_QueuedPayment(payment_id, instruction, trace))
                except queue.Full as exc:
                    raise ValueError("persisted pending payments exceed the configured queue bound") from exc

    def start(self) -> None:
        with self._lock:
            if self._closing or self._db_closed:
                raise RuntimeError("gateway service is closing or closed")
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._work, name="decimal-iron-terminal-worker", daemon=True)
            self._thread.start()

    def close(self, timeout: float = 5.0) -> bool:
        """Stop accepting work and wait up to ``timeout`` seconds for the worker.

        A timed-out worker keeps the SQLite connection until its current terminal
        operation returns. Pending queue rows remain QUEUED for recovery on the
        next start. The worker closes SQLite itself when it exits.
        """
        with self._lock:
            self._closing = True
            thread = self._thread
            if thread is not None and thread.is_alive():
                self._close_db_when_worker_exits = True
                self._stop_requested.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout)
            if thread.is_alive():
                return False
        with self._lock:
            self._close_db_locked()
        return True

    def _close_db_locked(self) -> None:
        if not self._db_closed:
            self._db.commit()
            self._db.close()
            self._db_closed = True

    def submit(self, body: object) -> tuple[int, dict[str, Any]]:
        try:
            instruction = PaymentInstruction.from_mapping(body)
        except ValueError as exc:
            return 400, {"error": "BAD_PAYMENT", "message": str(exc)}
        request_json = json.dumps(instruction.fields(), sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(request_json.encode("ascii")).hexdigest()
        trace = self.pipeline_trace(instruction)
        trace_json = json.dumps(trace.summary(), sort_keys=True, separators=(",", ":"))
        with self._lock:
            if self._closing or self._db_closed:
                return 503, {"error": "SERVICE_CLOSING", "retryable": True}
            existing = self._db.execute(
                "SELECT request_hash, status, receipt_json, trace_json, error FROM payments WHERE payment_id=?",
                (instruction.payment_id,),
            ).fetchone()
            if existing:
                if existing[0] != request_hash:
                    return 409, {"error": "IDEMPOTENCY_CONFLICT", "payment_id": instruction.payment_id}
                if existing[1] == "UNKNOWN_OUTCOME":
                    pending = self._db.execute("SELECT COUNT(*) FROM payments WHERE status='QUEUED'").fetchone()[0]
                    if pending >= self.max_queue:
                        return 503, {"error": "QUEUE_FULL", "retryable": True, "max_queue": self.max_queue}
                    item = _QueuedPayment(instruction.payment_id, instruction, trace)
                    self._db.execute(
                        "UPDATE payments SET status='QUEUED', receipt_json=NULL, error=NULL WHERE payment_id=?",
                        (instruction.payment_id,),
                    )
                    self._db.commit()
                    self._queue.put_nowait(item)
                    return 202, self.status(instruction.payment_id) or {"payment_id": instruction.payment_id, "status": "QUEUED"}
                return 202, self._status_payload(instruction.payment_id, *existing[1:])
            pending = self._db.execute("SELECT COUNT(*) FROM payments WHERE status='QUEUED'").fetchone()[0]
            if pending >= self.max_queue:
                return 503, {"error": "QUEUE_FULL", "retryable": True, "max_queue": self.max_queue}
            item = _QueuedPayment(instruction.payment_id, instruction, trace)
            self._db.execute(
                "INSERT INTO payments(payment_id, request_hash, request_json, status, trace_json) VALUES(?,?,?,?,?)",
                (instruction.payment_id, request_hash, request_json, "QUEUED", trace_json),
            )
            self._db.commit()
            # The database row is the outbox; a restart will refill this queue.
            self._queue.put_nowait(item)
        return 202, self.status(instruction.payment_id) or {"payment_id": instruction.payment_id, "status": "QUEUED"}

    def pipeline_trace(self, instruction: PaymentInstruction) -> ProtocolTrace:
        # The public trace and the submitted terminal request use the same
        # checked, reversible host record.
        return build_protocol_trace(instruction)

    def status(self, payment_id: str) -> dict[str, Any] | None:
        payment_id = payment_id.upper()
        with self._lock:
            row = self._db.execute(
                "SELECT status, receipt_json, trace_json, error FROM payments WHERE payment_id=?",
                (payment_id,),
            ).fetchone()
            if row is None:
                return None
            return self._status_payload(payment_id, *row)

    @staticmethod
    def _status_payload(payment_id: str, status: str, receipt_json: str | None, trace_json: str, error: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "payment_id": payment_id,
            "status": status,
            "protocol": json.loads(trace_json),
        }
        if receipt_json:
            payload["receipt"] = json.loads(receipt_json)
        if error:
            payload["error"] = error
        return payload

    def health(self) -> dict[str, Any]:
        with self._lock:
            pending = self._db.execute("SELECT COUNT(*) FROM payments WHERE status='QUEUED'").fetchone()[0]
            processing = self._db.execute("SELECT COUNT(*) FROM payments WHERE status='PROCESSING'").fetchone()[0]
        return {"status": "ok", "queue_depth": pending, "processing": processing, "max_queue": self.max_queue}

    def processor_phase(self) -> str:
        return self.pipeline.adapter.processor_status()

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 through 100")
        with self._lock:
            rows = self._db.execute(
                "SELECT payment_id, status, receipt_json, trace_json, error FROM payments ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._status_payload(payment_id, status, receipt, trace, error) for payment_id, status, receipt, trace, error in rows]

    def _work(self) -> None:
        try:
            while not self._stop_requested.is_set():
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    with self._lock:
                        if self._stop_requested.is_set():
                            return
                        self._db.execute("UPDATE payments SET status='PROCESSING' WHERE payment_id=?", (item.payment_id,))
                        self._db.commit()
                    try:
                        receipt, trace = self.pipeline.submit(item.instruction)
                        result_status = "POSTED"
                        receipt_data = {
                            "payment_id": receipt.payment_id,
                            "journal_sequence": receipt.journal_sequence,
                            "resolution": receipt.resolution,
                        }
                        error = None
                        trace_json = json.dumps(trace.summary(), sort_keys=True, separators=(",", ":"))
                    except PaymentRejected as exc:
                        result_status, receipt_data, error = "REJECTED", None, str(exc)
                        trace_json = json.dumps(item.trace.summary(), sort_keys=True, separators=(",", ":"))
                    except UnknownOutcome as exc:
                        result_status, receipt_data, error = "UNKNOWN_OUTCOME", None, str(exc)
                        trace_json = json.dumps(item.trace.summary(), sort_keys=True, separators=(",", ":"))
                    except Exception as exc:
                        result_status, receipt_data, error = "UNKNOWN_OUTCOME", None, f"terminal worker error: {exc}"
                        trace_json = json.dumps(item.trace.summary(), sort_keys=True, separators=(",", ":"))
                    with self._lock:
                        self._db.execute(
                            "UPDATE payments SET status=?, receipt_json=?, trace_json=?, error=? WHERE payment_id=?",
                            (
                                result_status,
                                json.dumps(receipt_data, sort_keys=True, separators=(",", ":")) if receipt_data else None,
                                trace_json,
                                error,
                                item.payment_id,
                            ),
                        )
                        self._db.commit()
                finally:
                    self._queue.task_done()
        finally:
            with self._lock:
                if self._close_db_when_worker_exits:
                    self._close_db_locked()


def make_gateway_handler(service: GatewayService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DecimalIronGateway/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[{self.log_date_time_string()}] {fmt % args}")

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._send_json(200, service.health())
                return
            if path == "/readyz":
                try:
                    phase = service.processor_phase()
                except Exception as exc:
                    self._send_json(503, {"status": "unavailable", "message": str(exc)})
                    return
                ready = phase == "OPEN"
                self._send_json(200 if ready else 503, {"status": "ready" if ready else "waiting", "processor_phase": phase})
                return
            if path == "/payments":
                raw_limit = parse_qs(urlsplit(self.path).query).get("limit", ["25"])[0]
                try:
                    result = service.recent(int(raw_limit))
                except (ValueError, TypeError) as exc:
                    self._send_json(400, {"error": "BAD_LIMIT", "message": str(exc)})
                    return
                self._send_json(200, {"payments": result})
                return
            prefix = "/payments/"
            if path.startswith(prefix):
                payment_id = unquote(path[len(prefix):]).upper()
                result = service.status(payment_id)
                if result is None:
                    self._send_json(404, {"error": "NOT_FOUND", "payment_id": payment_id})
                else:
                    self._send_json(200, result)
                return
            assets = {
                "/": ("gateway.html", "text/html; charset=utf-8"),
                "/static/gateway.css": ("gateway.css", "text/css; charset=utf-8"),
                "/static/gateway.js": ("gateway.js", "text/javascript; charset=utf-8"),
            }
            if path in assets:
                name, content_type = assets[path]
                payload = (Path(__file__).parent / "static" / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)
                return
            self._send_json(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/payments":
                self._send_json(404, {"error": "NOT_FOUND"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 4096:
                    raise ValueError("request body must be 1..4096 bytes")
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": "BAD_JSON", "message": str(exc)})
                return
            status, result = service.submit(body)
            self._send_json(status, result)

        def _send_json(self, status: int, value: object) -> None:
            payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def serve_gateway(
    *,
    host: str = "0.0.0.0",
    port: int = 8090,
    terminal_url: str = "ws://127.0.0.1:8080/terminal",
    max_queue: int = 32,
    state_path: str | Path = "data/gateway.sqlite3",
) -> None:
    terminal = WebSocketTerminal(terminal_url)
    service = GatewayService(TerminalPaymentAdapter(terminal), max_queue=max_queue, state_path=state_path)
    service.start()
    server = ThreadingHTTPServer((host, port), make_gateway_handler(service))
    try:
        print(f"Decimal Iron gateway listening at http://{host}:{port}/")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping gateway.")
    finally:
        server.server_close()
        service.close()
        terminal.close()
