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

## M1 — Physical legibility

- [ ] BCD register display and memory-field selector.
- [ ] Physical key switch, single-step, halt and examine.
- [ ] Moving-coil liquidity meter with real position-driven output.
- [ ] Scarce exception / closing printer.
- [ ] Accessible tablet enclosure.

## M2 — FPGA authority

- [ ] Character memory with word marks.
- [ ] Microcoded BCD ALU and addressing.
- [ ] Input/output channels.
- [ ] Run software-model and FPGA conformance vectors.
- [ ] Switch authority to FPGA with a documented software fallback.

## M3 — Cloud-native archaeology

- [ ] Synthetic member-bank Kubernetes deployments and traffic profiles.
- [ ] Single-cursor screen scraper with bounded queue and unknown-outcome reconciliation.
- [ ] Labelled intermediate translator strata.
- [ ] Replayable chaos scenarios and dashboard projections.

Do not build fictional strata as separate distributed services unless doing so creates measurable physical or educational value.
