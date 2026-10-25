# Decimal Iron

**A modern financial settlement engine trapped in 1982 hardware, subsequently made cloud-native.**

An Over-Engineering Chronicles hobby installation: a fictional Finnish banking-group central clearing processor, designed by engineers with 2026 knowledge but constrained to early-1980s hardware. Decades later, Kubernetes, screen scrapers and gateways have accumulated around an authoritative decimal machine.

This is a working-machine project, not a historical replica or production payment system. All banks, balances and payments are synthetic.

## The installation

- **1982:** FPGA character-oriented BCD processor, journal, fixed records, decimal register panel, business-day key switch, 24×80 console and exception printer.
- **2026:** Kubernetes-hosted synthetic banks, traffic generators, a terminal automation adapter and observability.
- **Between:** intentionally thin, labelled protocol translators representing accumulated integration eras.

The old machine is the ledger authority. The cluster knows what it submitted; the settlement processor knows what posted. A red beacon illuminates **only** when the reconciled balance difference is nonzero.

## Run the M0 software slice

Python 3.11+ is sufficient; the reference machine and terminal server use only the standard library.

```sh
python -m decimal_iron serve
```

Open <http://127.0.0.1:8080/>. The browser is a 24×80 renderer for the processor's byte stream. It sends keyboard bytes; it has no payment or ledger API. Use `Ctrl+C` to stop the server. The append-only journal is written to `data/ledger.jsonl` and replayed at startup.

The server has no authentication or TLS; keep it on loopback or a trusted private network. Setting `--host` to a non-loopback address exposes the synthetic command interface to reachable clients. A file-backed journal is single-process: the first server holds an exclusive OS lock until it stops, and a second server using the same journal path is refused.

Run the scripted end-of-day demonstration:

```sh
python -m decimal_iron demo --output artifacts/clearing-day
```

The output directory must be empty or new. The demo covers guarded day transitions, synthetic member payments, a reasoned limit override, idempotent reversal, a lost acknowledgement resolved by inquiry, net settlement, an injected reconciliation break, beacon recovery and journal replay. It writes a closing report and journal.

Terminal commands and the exact output-byte grammar are specified in [the protocol contract](docs/terminal-protocol.md). See [architecture](docs/architecture.md), [interfaces](docs/interfaces.md), and [roadmap](docs/roadmap.md).

## Non-goals

No actual banking connectivity; no genuine customer information; no production payment claims; no elaborate compliance or fraud simulator; no full IBM 1401 binary compatibility; no dependency on Kubernetes for the core to function.

## Status

M0 is implemented as a deterministic Python reference machine, hash-chained append-only journal, 24×80 byte-stream terminal, browser renderer, single-cursor payment adapter and replayable end-of-day demo. It is not FPGA hardware; M1–M3 remain roadmap work.

## License

MIT (see LICENSE).
