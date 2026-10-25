"""Dependency-free HTTP shell and binary WebSocket terminal transport."""

from __future__ import annotations

import base64
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .machine import DecimalMachine
from .terminal import TerminalSession

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_FRAME = 64 * 1024


class _TerminalGate:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = False

    def acquire(self) -> bool:
        with self.lock:
            if self.active:
                return False
            self.active = True
            return True

    def release(self) -> None:
        with self.lock:
            self.active = False


def make_handler(machine: DecimalMachine, gate: _TerminalGate | None = None):
    gate = gate or _TerminalGate()

    class Handler(BaseHTTPRequestHandler):
        server_version = "DecimalIron/0.1"

        def log_message(self, format: str, *args: object) -> None:
            print(f"[{self.log_date_time_string()}] {format % args}")

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/terminal":
                self._websocket()
                return
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/static/style.css": ("style.css", "text/css; charset=utf-8"),
                "/static/terminal.js": ("terminal.js", "text/javascript; charset=utf-8"),
            }
            if path not in assets:
                self.send_error(404)
                return
            name, content_type = assets[path]
            content = (Path(__file__).parent / "static" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def _websocket(self) -> None:
            if self.headers.get("Upgrade", "").lower() != "websocket":
                self.send_error(400, "WebSocket upgrade required")
                return
            if not gate.acquire():
                self.send_error(409, "The single terminal cursor is already in use")
                return
            try:
                key = self.headers.get("Sec-WebSocket-Key")
                if not key or self.headers.get("Sec-WebSocket-Version") != "13":
                    self.send_error(400, "Invalid WebSocket handshake")
                    return
                accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
                self.send_response(101, "Switching Protocols")
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                self.wfile.flush()
                self.connection.settimeout(300)
                session = TerminalSession(machine)
                self._send_frame(session.take_output())
                while True:
                    opcode, payload = self._read_frame()
                    if opcode == 0x8:
                        self._send_frame(payload[:125], opcode=0x8)
                        return
                    if opcode == 0x9:
                        self._send_frame(payload[:125], opcode=0xA)
                        continue
                    if opcode not in (0x1, 0x2, 0x0):
                        self._send_frame(b"unsupported opcode", opcode=0x8)
                        return
                    if opcode == 0x0:
                        # Fragmented input is intentionally unsupported; the
                        # browser sends one complete keystroke chunk per frame.
                        self._send_frame(b"fragmented input unsupported", opcode=0x8)
                        return
                    if len(payload) > _MAX_FRAME:
                        self._send_frame(b"frame too large", opcode=0x8)
                        return
                    if opcode != 0x2:
                        self._send_frame(b"terminal input must be a binary byte stream", opcode=0x8)
                        return
                    session.feed(payload)
                    output = session.take_output()
                    if output:
                        self._send_frame(output)
            except (ConnectionError, OSError, ValueError):
                return
            finally:
                gate.release()

        def _read_frame(self) -> tuple[int, bytes]:
            header = self.rfile.read(2)
            if len(header) != 2:
                raise ConnectionError("short WebSocket frame")
            first, second = header
            if not first & 0x80:
                raise ValueError("fragmented WebSocket frames are unsupported")
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                extra = self.rfile.read(2)
                if len(extra) != 2:
                    raise ConnectionError("short WebSocket length")
                length = int.from_bytes(extra, "big")
            elif length == 127:
                extra = self.rfile.read(8)
                if len(extra) != 8:
                    raise ConnectionError("short WebSocket length")
                length = int.from_bytes(extra, "big")
            if length > _MAX_FRAME:
                raise ValueError("frame too large")
            if not masked:
                raise ValueError("client frames must be masked")
            mask = self.rfile.read(4)
            payload = self.rfile.read(length)
            if len(mask) != 4 or len(payload) != length:
                raise ConnectionError("short WebSocket payload")
            return opcode, bytes(value ^ mask[index % 4] for index, value in enumerate(payload))

        def _send_frame(self, payload: bytes, *, opcode: int = 0x2) -> None:
            length = len(payload)
            header = bytearray([0x80 | opcode])
            if length < 126:
                header.append(length)
            elif length <= 0xFFFF:
                header.append(126)
                header.extend(length.to_bytes(2, "big"))
            else:
                header.append(127)
                header.extend(length.to_bytes(8, "big"))
            self.wfile.write(header + payload)
            self.wfile.flush()

    return Handler


def serve(machine: DecimalMachine, host: str = "127.0.0.1", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(machine))
    try:
        print(f"Decimal Iron terminal listening at http://{host}:{port}/")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping terminal server.")
    finally:
        server.server_close()
        machine.close()
