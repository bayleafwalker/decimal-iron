# Architecture and invariants

## Fiction and system boundary

A central institution clears payments for member banks. The model is inspired by Finnish banking-group settlement structures, but deliberately counterfactual: a 1982 machine implements modern ideas such as idempotency, immutable posting journals, compensating reversals and continuous gross posting. External settlement can remain deferred.

```text
Synthetic member banks (Kubernetes)
  -> message queue / API
  -> terminal automation adapter (one cursor, serialized commands)
  -> 24x80 byte-stream session
  -> decimal clearing processor (authority)
  -> append-only journal + derived positions
  -> terminal response / printed report
  -> screen parser -> modern projections
```

The terminal is the only application-facing integration path. The Kubernetes
gateway transforms requests and submits terminal bytes through one serialized
cursor; its separate durable outbox is delivery state. Hardware service/debug
channels may exist but cannot bypass posting authority.

## Decimal processor

IBM 1401-*inspired*, not instruction-compatible: character-addressed memory with word marks, BCD decimal arithmetic, variable-length fields, microcoded ALU, simple branches, a few index registers, and record-oriented channels. Avoid MMU and general-purpose OS.

Design the front panel concurrently with the ISA. Expose actual operand digits, position fields, address, word marks and channel state. Do not animate unrelated lights. The current web panel and RTL connector are preliminary signal models, not a physical panel.

## Core invariants

1. The accepted journal is append-only. A reversal adds a compensating record.
2. Each posting has a stable idempotency identity. Retries never double-post.
3. Money is integer minor units; currency is explicit; no floating-point ledger arithmetic.
4. The old processor alone decides posting outcomes.
5. A business-day transition is requested by a maintained physical switch, but checked by the processor state machine.
6. Cut-off forbids ordinary new-day postings until the next opening.
7. The red beacon is exactly `reconciliation_break != 0`; all other failures use console/status indicators.
8. Replaying a closed-day journal reproduces the same closing balances and report.
9. The 24x80 protocol has no browser, CSS, HTTP or terminal-specific assumptions.
10. All traffic is synthetic, and no external banking endpoints are configured.

## Failure and recovery

Journal before acknowledgement. On crash, replay journal and rebuild positions. The adapter may retry a command only with the same idempotency identity. Preserve an explicit unknown-outcome state until a terminal inquiry resolves it. Store deterministic input seeds and closing artifacts. Never automatically override a nonzero reconciliation break.

## Scope of rules

Duplicates, limits, cut-off, reversal, and override-with-reason; plus conservation and reconciliation. Avoid expanding into customer banking, AML, fraud scoring or full payment standards.
