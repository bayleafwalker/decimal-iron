# Shared scenarios and replay evidence

An exhibit displays observations from this implementation. It does not carry
an independently maintained payment engine.

## The executable contract

`decimal_iron/fixtures/replay-scenarios.json` contains bounded declarative
commands and payment intents, named transport interruptions, and independent
expected results. `decimal_iron/replay.py` runs it through `DecimalMachine`,
`TerminalSession`, the byte protocol and `TerminalPaymentAdapter`, using a real
temporary file-backed journal. No fixture field is executed as Python; the
exporter makes no network requests.

| Scenario | What is checked |
| --- | --- |
| `lost-acknowledgement` | The commit precedes the lost reply. Inquiry resolves the original identity, and repeating it does not post again. |
| `interrupted-before-delivery` | The interrupted write produces no posting. Inquiry returns not found and the adapter retries the same identity and payload. |
| `euro-rounding-residue` | Journal-derived EUR items differ from the aggregate. Reconciliation detects the omitted residue, closing is refused, and an explicit adjustment clears the matching scope. |

Transport checkpoints have their own fixture expectations. A committed
payment with no acknowledgement has `terminal_result: null`; the trace does
not pretend the client had received information available only in the ledger.
At the end of each scenario the original journal owner closes, a new machine
replays the file, and state and closing-report bytes must match.

The runner also executes three deliberately wrong implementations: a retry
that invents a new identity, a converter that omits the declared rounding
adjustment, and a reconciliation routine that suppresses the EUR difference.
The same fixture expectations must reject all three. A negative control passes
only when its intended invariant fails, and the export includes those failed
assertions. This is a bounded check of specific failure modes, not a claim
that arbitrary implementation changes are covered.

## EUR is a statement scope

The historical fixed rate is [1 EUR = FIM 5.94573](https://www.ecb.europa.eu/euro/exchange/fi/html/index.en.html).
Finland adopted the euro in 1999 and introduced euro cash in 2002; see the
[European Commission's chronology](https://economy-finance.ec.europa.eu/euro/eu-countries-and-euro/finland-and-euro_en).
The fixture's `2002-01-02` is a fictional **business date for this machine's
integration**, not the date the rate was fixed.

The conversion routine uses the exact integer ratio `100000 / 594573` from
FIM penni to EUR cents. The declared scenario policy rounds to the nearest
cent, with exact halves away from zero. No binary floating-point arithmetic
participates. Signed reversals are negative statement items.

Three posted FIM 1.00 items each convert to EUR 0.17. Their item total is
51 cents. Converting their aggregate FIM 3.00 produces 50 cents. In this
scenario, the aggregate is the declared control; a minus-one-cent adjustment
is therefore required alongside the separately rounded items. Choosing which
control governs is explicit scenario policy, not a claim about every real
conversion or settlement agreement.

`CONVERT EUR OMIT` appends the broken statement; `CONVERT EUR ACCOUNT` appends
one with the adjustment. Both derive the same current-day payment and reversal
records from the actual journal. Statement metadata identifies the source
entry sequences and journal head. Settlement transfers are excluded: the
basis is signed payment turnover, not a second ledger of participant balances.

The FIM posting and settlement core remains unchanged in denomination. The
extension adds `EUR_STATEMENT_PREPARED` and `EUR_RECONCILED` journal events and
separate EUR-cent reconciliation state. It never writes cents to the FIM
register. Summary, terminal, panel and report label the units.

The beacon is the OR of retained nonzero scope results. Preparing a new EUR
statement only makes that scope stale. A clear EUR reconciliation cannot hide
a FIM break, and a clear FIM reconciliation cannot hide a EUR break. `CLOSE`
requires current and clear FIM plus current and clear EUR whenever EUR is
active. A later `OPEN` also refuses outstanding or stale previous-day results.

## Export and pin

```sh
python -m unittest discover -v
python -m decimal_iron replay --output artifacts/replay.json
python -m decimal_iron replay --check artifacts/replay.json
```

The default command checks that the executed source and fixture bytes match
`HEAD`. It refuses uncommitted implementation changes. `--allow-uncommitted`
is available for development and sets `verification.status` to `draft`; it
cannot produce a clean verification claim. A site publishing the trace must
require `implementation.clean: true` and `verification.status: passed`, pin
the immutable revision, and verify the fixture and source digests. `clean`
refers to the listed execution inputs, not unrelated files in the checkout.

The JSON contract is `decimal-iron-replay/v1`:

- `implementation`: repository, immutable revision, source-file SHA-256 map,
  digest of its canonical JSON, and committed-byte status.
- `fixture`: repository-relative path, schema and SHA-256 of the exact file.
- `verification`: overall status, mutation rejection evidence, and separate
  execution targets with `passed` or `skipped` results.
- `scenarios`: title, summary, checked steps and journal-replay evidence.
- Each step: stable `id`, source `fixture_step`, declarative `action`, label,
  `checkpoint`, actual terminal result, machine state and expected/observed
  assertions. Payment steps also include the adapter receipt and transport
  counters. Expected outcomes are only compared after execution.

Encoding has sorted keys and no wall-clock timestamp or temporary path. The
same committed implementation produces identical export bytes. `--check`
executes the scenarios again and compares canonical JSON values, allowing a
site formatter to change whitespace or object-key order. Changed values and
JSON types still fail; for example, `true` cannot replace integer `1`.

The browser should offer a checkpoint selector or step controls over these
observations. An era selection should advance to the EUR statement and its
reconciliation evidence; it must not assign the lamp directly. A static trace
is evidence of the identified revision, not a live claim about later code.

## Execution boundaries and rollback

The Python reference target is exercised. A hardware or KESKUS adapter can
consume the same declarative fixture, but no such adapter is executed here.
Those targets are `skipped`, as are physical meters, printer output, UART
timing and a 300-baud connection. Separate CPU transfer-vector conformance
does not qualify the full scenario or the installation.

Old FIM-only journals still replay. Once the new EUR journal events are used,
older versions do not understand them and intentionally refuse replay. Keep
the journal with its compatible implementation revision when rolling back;
do not delete or rewrite EUR events to make old code accept the journal.
Published site evidence can be rolled back by restoring its previous pinned
trace and fixture manifest together. The exporter does not touch a running
machine's journal.
