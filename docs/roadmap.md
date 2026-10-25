# Build roadmap

## M0 — Executable vertical slice

- [x] Define terminal byte grammar and golden 24×80 screen fixture.
- [x] Implement deterministic decimal machine model and journal.
- [x] Implement duplicate protection, debit limits, cut-off, reversal, reasoned override and conserved postings.
- [x] Add simulated key-switch transitions and reconciliation-only beacon.
- [x] Build browser terminal as a byte-stream renderer.
- [x] Build terminal-driving payment adapter with one serialized cursor.
- [x] Produce a deterministic end-of-day print artifact.
- [x] Demonstrate restart/replay and unknown-outcome recovery.

**Acceptance:** open day → submit payments → observe positions → cut off → settle → reconcile → print → close; an injected nonzero break illuminates only the beacon, and clearing/reconciling it turns the beacon off. Journal restart reproduces the final positions and report.

Run the reference implementation and demonstration:

```sh
python -m decimal_iron serve
python -m decimal_iron demo --output artifacts/clearing-day
python -m unittest discover -v
```

## M1 — Physical legibility (preliminary interface)

- [x] Model state-derived BCD register display, word-mark window, selectors, position-meter input and reconciliation beacon.
- [x] Define board-neutral register, key feedback, flags, word-mark and meter signals in `rtl/panel_connector.sv`.
- [x] Limit modeled deposit to reserved diagnostic cells; prevent panel controls from posting.
- [ ] Select physical display, switches, moving-coil meter and exception printer.
- [ ] Design and validate the accessible enclosure, pin assignments and electrical drivers.

See [hardware panel scaffold](hardware-panel.md). No physical panel has been built or validated.

## M2 — FPGA authority (preliminary RTL and software oracle)

- [x] Add a 256-cell character-memory RTL scaffold with word marks, signed BCD fields and a compact original ISA.
- [x] Add halt/run/single-step, examine/deposit and record-channel signals.
- [x] Share decimal transfer vectors with an optional Icarus Verilog testbench runner.
- [x] Keep a Python CPU oracle and route ledger transfers through it.
- [ ] Run the RTL testbench in an HDL simulator, synthesize and close timing.
- [ ] Validate FPGA conformance and establish hardware authority with a documented fallback.

The RTL and testbench are source-only scaffolding in this environment. They have not been synthesized or simulator-validated.

## M3 — Cloud-native archaeology (preliminary implementation)

- [x] Add three seeded, finite Kubernetes synthetic-bank producers with rate and request limits.
- [x] Add a bounded durable outbox, single terminal worker, inquiry-based recovery and status projection.
- [x] Add labeled JSON, XML, fixed-record and terminal translation layers with a checked host-record round trip.
- [x] Add network policies that allow bank-to-gateway and gateway-to-terminal traffic only.
- [ ] Deploy the manifest in a cluster and exercise restart, network and traffic scenarios.
- [ ] Add richer replayable chaos profiles and operator dashboard projections.

The strata are lightweight translators in the gateway process. They are visible for study and do not grant cloud components access to posting authority.
