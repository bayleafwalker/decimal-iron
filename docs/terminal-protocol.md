# Terminal protocol v1

The terminal is an ordered byte stream with a fixed 24-row by 80-column ASCII
screen. The WebSocket is only a transport for that stream. No account,
transaction, database, JSON or HTML interface crosses the processor boundary.

## Processor to terminal

Printable bytes are ASCII `0x20` through `0x7e`. The processor supports this
control subset only:

| Bytes | Meaning |
| --- | --- |
| `ESC [ 2 J` | Clear all 1920 cells and home the cursor |
| `ESC [ r ; c H` | Move cursor to one-based row `r`, column `c` |
| `ESC [ K` | Erase from the cursor through the end of its row |

The reference renderer sends a full frame after each input chunk: clear, then
24 cursor-positioned rows of exactly 80 printable bytes. The golden banner
fixture is `tests/fixtures/banner-screen.txt`: each line contains exactly 80
cells, with `_` marking an ASCII blank so trailing spaces remain visible in
version control. The protocol test expands those markers and checks all 1920
cells against the emitted byte stream.

## Terminal to processor

Input is plain printable ASCII, `CR` or `LF` to submit the current line, and
`BS` or `DEL` to erase its last character. Input framing is not semantically
significant: a command may arrive as one chunk or as individual keyboard
bytes. Escape sequences are not accepted as commands.

The result line is one of the fixed screen rows and begins with `RESULT `. It
is a terminal response, not a second API. The payment adapter reads it by
decoding the screen bytes it received.

## Command records

```text
KEY CLOSED|OPEN|CUT-OFF|SETTLE
OPEN YYYY-MM-DD
PAY id source destination FIM amount-in-penni [override reason]
INQUIRE id
REV original-id reversal-id [reason]
CUTOFF
SETTLE
RECONCILE
BREAK signed-penni
CLEARBREAK
REPORT
CLOSE
STATUS
```

The hardware-compatible key input and processor transition request are
separate commands. For example, `KEY CUT-OFF` only moves the simulated switch;
`CUTOFF` still fails unless the machine is open. `BREAK` and `CLEARBREAK` are
synthetic reconciliation-fixture controls, not payment operations.

## Golden screen

`tests/fixtures/banner-screen.txt` is the browser-independent golden screen.
`tests/test_protocol.py` checks that it contains exactly 1920 cells and that
it serializes to and decodes from the byte grammar without changing any cell.
