# Interface contracts (provisional v0)

## Terminal

Fixed **24 rows × 80 columns** of single-byte characters. Transport is an ordered byte stream. No layout metadata crosses the boundary.

Minimal proposed control operations: clear, cursor position (row/column), erase to end of line, write characters, inbound attention/function key. Escape bytes and field encoding require a versioned conformance fixture before any hardware purchase. A real VT or 3270 terminal needs a suitable bridge; 3270 is block-mode, not a cable-only swap.

The terminal automation adapter is a **single-writer state machine**. It must serialize interactions, match replies to submitted references, handle timeout/unknown outcomes and use read-back inquiries before retrying.

## Payment record

Define a versioned fixed-column record containing business date, source, destination, sequence, currency, integer-minor-unit amount, reference, operation and check digits. FIM is the initial currency; EUR belongs only in later adapter strata. Currency conversions, if added, must use explicit rational rates and rounding rules.

## Physical controls

- Day switch: CLOSED / OPEN / CUT-OFF / SETTLE, interpreted as requested transitions.
- Processor controls: RUN / HALT / SINGLE STEP / EXAMINE / DEPOSIT.
- Beacon: a hardware output sourced only from the processor's reconciliation-break register.
- Analog meters: member available liquidity, scaled and calibrated from actual positions.

## Contract tests

Golden terminal frames (exactly 1920 cells), byte-stream cursor conformance, duplicate submission, lost acknowledgement, crash-after-journal-before-response, cut-off rejection, reversal, nonzero reconciliation break, replay identity and clean close.
