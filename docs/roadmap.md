# Build roadmap

## M0 — Executable vertical slice

- [ ] Define terminal byte grammar and golden 24x80 fixtures.
- [ ] Implement deterministic decimal machine model and journal.
- [ ] Implement five core business rules and conserved postings.
- [ ] Add simulated key-switch transitions and reconciliation-only beacon.
- [ ] Build browser terminal as a byte-stream renderer.
- [ ] Build terminal-driving payment adapter (no direct ledger API).
- [ ] Produce a deterministic end-of-day print artifact.
- [ ] Demonstrate restart/replay and unknown-outcome recovery.

**Acceptance:** open day -> send payments -> observe position -> cut off -> settle -> reconcile -> print -> close; injected break illuminates only the beacon.

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
