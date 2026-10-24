# Decimal Iron

**A modern financial settlement engine trapped in 1982 hardware, subsequently made cloud-native.**

An Over-Engineering Chronicles hobby installation: a fictional Finnish banking-group central clearing processor, designed by engineers with 2026 knowledge but constrained to early-1980s hardware. Decades later, Kubernetes, screen scrapers and gateways have accumulated around an authoritative decimal machine.

This is a working-machine project, not a historical replica or production payment system. All banks, balances and payments are synthetic.

## The installation

- **1982:** FPGA character-oriented BCD processor, journal, fixed records, decimal register panel, business-day key switch, 24×80 console and exception printer.
- **2026:** Kubernetes-hosted synthetic banks, traffic generators, a terminal automation adapter and observability.
- **Between:** intentionally thin, labelled protocol translators representing accumulated integration eras.

The old machine is the ledger authority. The cluster knows what it submitted; the settlement processor knows what posted. A red beacon illuminates **only** when the reconciled balance difference is nonzero.

## First runnable slice

1. Start a deterministic software model of the decimal machine.
2. Open a business day using a physical-key-compatible input.
3. Submit synthetic payments through a byte-stream terminal.
4. Observe real balance changes in a 24×80 display and decimal-register model.
5. Force cut-off, settle, reconcile and print a reproducible closing report.
6. Inject a reconciliation break; verify the beacon invariant.
7. Replace the software CPU with FPGA RTL without changing the terminal or settlement contracts.

See [architecture](docs/architecture.md), [interfaces](docs/interfaces.md), and [roadmap](docs/roadmap.md).

## Non-goals

No actual banking connectivity; no genuine customer information; no production payment claims; no elaborate compliance or fraud simulator; no full IBM 1401 binary compatibility; no dependency on Kubernetes for the core to function.

## Status

Design and initial project scaffold. No functional FPGA or settlement implementation is claimed yet.

## License

MIT (see LICENSE).
