"""Small standard-library WebSocket client for the processor terminal stream."""

from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import ssl
from urllib.parse import urlsplit

from .adapter import TerminalTimeout

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_FRAME = 64 * 1024


class WebSocketTerminal:
    """A reconnecting binary WebSocket transport for :class:`TerminalPaymentAdapter`.

    It carries only terminal bytes. A reconnect creates a new terminal cursor;
    the adapter resolves any uncertain payment outcome with the same id and an
    ``INQUIRE`` command before considering a retry.
    """

    def __init__(self, url: str, *, connect_timeout: float = 5.0):
        parsed = urlsplit(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("terminal URL must use ws:// or wss:// and include a host")
        self.url = url
        self._parsed = parsed
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._reader = None
        self._connect()
        # The terminal sends one initial screen frame on every new cursor.
        self.read(timeout=connect_timeout)

    def _connect(self) -> None:
        self.close()
        host = self._parsed.hostname
        port = self._parsed.port or (443 if self._parsed.scheme == "wss" else 80)
        raw = socket.create_connection((host, port), timeout=self._connect_timeout)
        if self._parsed.scheme == "wss":
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self._sock = raw
        self._reader = raw.makefile("rb")
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = self._parsed.path or "/"
        if self._parsed.query:
            path += "?" + self._parsed.query
        host_header = host if self._parsed.port is None else f"{host}:{self._parsed.port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        try:
            raw.sendall(request.encode("ascii"))
            status = self._reader.readline().decode("ascii", "replace").strip()
            headers: dict[str, str] = {}
            while True:
                line = self._reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
                name, separator, value = line.decode("ascii", "replace").partition(":")
                if separator:
                    headers[name.strip().lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
            if not status.startswith("HTTP/1.1 101 ") or headers.get("sec-websocket-accept") != expected:
                raise ConnectionError(f"terminal rejected WebSocket handshake: {status}")
        except (OSError, ValueError, ConnectionError):
            self.close()
            raise

    def _ensure_connected(self) -> None:
        if self._sock is None or self._reader is None:
            self._connect()
            self.read(timeout=self._connect_timeout)

    @staticmethod
    def _masked_frame(opcode: int, payload: bytes) -> bytes:
        if len(payload) > _MAX_FRAME:
            raise ValueError("terminal frame exceeds 64 KiB")
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        header.extend(mask)
        header.extend(value ^ mask[index % 4] for index, value in enumerate(payload))
        return bytes(header)

    def write(self, data: bytes) -> None:
        self._ensure_connected()
        assert self._sock is not None
        try:
            self._sock.sendall(self._masked_frame(0x2, data))
        except OSError:
            self.close()
            raise

    def read(self, timeout: float = 2.0) -> bytes:
        self._ensure_connected()
        assert self._sock is not None and self._reader is not None
        self._sock.settimeout(timeout)
        try:
            while True:
                header = self._read_exact(2)
                first, second = header
                if not first & 0x80:
                    raise ConnectionError("fragmented terminal frames are unsupported")
                opcode = first & 0x0F
                masked = bool(second & 0x80)
                length = second & 0x7F
                if length == 126:
                    length = int.from_bytes(self._read_exact(2), "big")
                elif length == 127:
                    length = int.from_bytes(self._read_exact(8), "big")
                if length > _MAX_FRAME:
                    raise ConnectionError("terminal frame exceeds 64 KiB")
                mask = self._read_exact(4) if masked else b""
                payload = self._read_exact(length)
                if masked:
                    payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
                if opcode == 0x8:
                    raise ConnectionError("terminal closed the WebSocket")
                if opcode == 0x9:
                    self._send_control(0xA, payload[:125])
                    continue
                if opcode == 0xA:
                    continue
                if opcode not in (0x1, 0x2):
                    raise ConnectionError(f"unsupported terminal WebSocket opcode {opcode}")
                return payload
        except socket.timeout as exc:
            # A late screen from a timed-out command has no request id and
            # could be mistaken for the following inquiry response. Discard
            # this cursor; the adapter reconnects, drains its banner, and
            # resolves the command using the durable payment identity.
            self.close()
            raise TerminalTimeout("terminal screen read timed out") from exc
        except (OSError, ConnectionError, ValueError):
            self.close()
            raise

    def _read_exact(self, count: int) -> bytes:
        assert self._reader is not None
        data = self._reader.read(count)
        if len(data) != count:
            raise ConnectionError("terminal closed during WebSocket frame")
        return data

    def _send_control(self, opcode: int, payload: bytes) -> None:
        if self._sock is not None:
            self._sock.sendall(self._masked_frame(opcode, payload))

    def close(self) -> None:
        reader, sock = self._reader, self._sock
        self._reader = None
        self._sock = None
        if reader is not None:
            try:
                reader.close()
            except OSError:
                pass
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def __enter__(self) -> "WebSocketTerminal":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
