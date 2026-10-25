"""The small, versioned byte grammar used by the 24x80 console.

The processor emits an ANSI-shaped subset. Input is plain printable ASCII plus
CR/LF and backspace bytes. Transport framing (WebSocket today, a UART bridge
later) is deliberately outside this grammar.
"""

from __future__ import annotations

import re
from typing import Iterable

ROWS = 24
COLUMNS = 80
CELLS = ROWS * COLUMNS
ESC = b"\x1b"
_CSI = re.compile(rb"\x1b\[([0-9;?]*)([A-Za-z])")


def clear_screen() -> bytes:
    return ESC + b"[2J"


def cursor(row: int, column: int) -> bytes:
    if not 1 <= row <= ROWS or not 1 <= column <= COLUMNS:
        raise ValueError("cursor is outside the 24x80 terminal")
    return ESC + f"[{row};{column}H".encode("ascii")


def erase_to_end() -> bytes:
    return ESC + b"[K"


def render_cells(cells: Iterable[str]) -> bytes:
    """Serialize exactly 1920 ASCII cells as terminal control bytes."""
    flat = list(cells)
    if len(flat) != CELLS:
        raise ValueError(f"screen must contain exactly {CELLS} cells")
    if any(len(ch) != 1 or not (0x20 <= ord(ch) <= 0x7E) for ch in flat):
        raise ValueError("screen cells must be printable single-byte ASCII")
    out = bytearray(clear_screen())
    for row in range(ROWS):
        start = row * COLUMNS
        out.extend(cursor(row + 1, 1))
        out.extend("".join(flat[start : start + COLUMNS]).encode("ascii"))
    return bytes(out)


def decode_screen(stream: bytes) -> tuple[str, ...]:
    """Apply this protocol's output grammar and return the final 24 screen rows.

    A stream may contain several complete screen refreshes. The latest one is
    returned, which is useful when a terminal receives a burst of key bytes.
    """
    cells = [" "] * CELLS
    row = column = 0
    i = 0
    while i < len(stream):
        if stream[i : i + 2] == ESC + b"[":
            match = _CSI.match(stream, i)
            if not match:
                raise ValueError("incomplete or unsupported terminal escape")
            params = match.group(1).decode("ascii")
            command = match.group(2)
            if command == b"J" and params == "2":
                cells = [" "] * CELLS
                row = column = 0
            elif command == b"H":
                parts = params.split(";") if params else ["1", "1"]
                if len(parts) != 2:
                    raise ValueError("cursor position needs row and column")
                row, column = int(parts[0] or "1") - 1, int(parts[1] or "1") - 1
                if not (0 <= row < ROWS and 0 <= column < COLUMNS):
                    raise ValueError("cursor is outside the 24x80 terminal")
            elif command == b"K" and params in ("", "0"):
                start = row * COLUMNS + column
                end = (row + 1) * COLUMNS
                cells[start:end] = [" "] * (end - start)
            else:
                raise ValueError(f"unsupported terminal control ESC[{params}{command.decode('ascii')}")
            i = match.end()
            continue
        byte = stream[i]
        if byte < 0x20 or byte > 0x7E:
            raise ValueError(f"unsupported output byte 0x{byte:02x}")
        if row < ROWS and column < COLUMNS:
            cells[row * COLUMNS + column] = chr(byte)
            column += 1
            if column == COLUMNS:
                column = COLUMNS - 1
        i += 1
    return tuple("".join(cells[r * COLUMNS : (r + 1) * COLUMNS]) for r in range(ROWS))


def result_line(stream: bytes) -> str:
    """Return the machine-readable RESULT row from the most recent frame."""
    for line in decode_screen(stream):
        if line.startswith("RESULT "):
            return line.rstrip()
    raise ValueError("terminal response did not contain a RESULT line")
