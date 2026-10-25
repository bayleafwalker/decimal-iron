# Interface contracts

## Terminal

The terminal contract is version 1: a fixed **24 rows × 80 columns** of
single-byte ASCII cells carried in an ordered byte stream. The supported
processor-to-terminal escape grammar is `ESC[2J`, `ESC[row;columnH`, and
`ESC[K`; input is printable ASCII, CR/LF and backspace/delete. See
[terminal-protocol.md](terminal-protocol.md) for the complete grammar and
golden screen fixture.

The browser renders only this byte stream. Its static HTML is a transport
shell; no layout metadata, business command API, HTML, CSS or database access
crosses the processor boundary.

The terminal automation adapter owns one serialized cursor. It sends the same
text records as an operator, parses terminal bytes for the `RESULT` row,
inquires after an unknown outcome, and retries only with the original
idempotency identity. It has no ledger or journal reference.

## Payment record

The v1 terminal record is:

```text
PAY id source destination FIM amount-in-penni [override reason]
```

Ids are stable ASCII identities. FIM is explicit and amounts are positive
integer penni (100 penni = 1 FIM). Each member position is integer minor units;
no floating-point value participates in ledger arithmetic. A payment is
recorded durably before its terminal acknowledgement. A retry with the same
identity and same request returns the original journal sequence; reusing an id
with different fields is rejected. A reversal appends a compensating event.

The reference machine enforces a FIM 50,000.00 per-payment hard cap and a
FIM 1,000.00 member debit limit. Crossing the member limit requires a non-empty
reason, stored in the journal. The hard cap cannot be overridden. Closing
requires a current reconciliation for the settled journal and a zero
reconciliation difference.

## Physical controls

- Simulated day key positions: CLOSED / OPEN / CUT-OFF / SETTLE.
- The key input and transition request are separate; the processor checks
  state, key position, conservation and reconciliation before accepting.
- Processor controls for RUN / HALT / SINGLE STEP / EXAMINE / DEPOSIT remain
  hardware work; the software slice models only the business-day key.
- Beacon: `reconciliation_break_minor != 0`, sourced from the last
  reconciliation result only.
- Register and liquidity instrumentation must derive from real machine state.

## Recovery and closing report

The JSONL journal is append-only and hash-chained. Every event is fsynced
before acknowledgement. Startup validates sequence and hash links, then
rebuilds balances, switch state, idempotency indexes and the reconciliation
register. No wall-clock timestamp is included in the closing report, so a
replay with the same journal reproduces the same report bytes and digest.

A file-backed journal has one process owner at a time. The machine holds an
exclusive OS lock for its lifetime; close it before opening the same journal
for replay or recovery. A second process is refused before it can append from a
stale journal head.

The software adapter exposes an explicit unresolved outcome if both response
and inquiry paths fail. It never invents a new payment id to make progress.

## Deferred contracts

Currency conversion, external payment standards, 3270/VT bridges, FPGA channel
signals and Kubernetes protocol strata remain future work. No external banking
endpoint is configured.
