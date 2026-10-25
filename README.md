# Decimal Iron

**A modern financial settlement engine trapped in 1982 hardware, subsequently made cloud-native.**

An Over-Engineering Chronicles hobby installation: a fictional Finnish banking-group central clearing processor, designed by engineers with 2026 knowledge but constrained to early-1980s hardware. Decades later, Kubernetes, screen scrapers and gateways have accumulated around an authoritative decimal machine.

This is a working-machine project, not a historical replica or production payment system. All banks, balances and payments are synthetic.

## The installation

- **1982:** FPGA character-oriented BCD processor, journal, fixed records, decimal register panel, business-day key switch, 24×80 console and exception printer.
- **2026:** Kubernetes-hosted synthetic banks, traffic generators, a terminal automation adapter and observability.
- **Between:** intentionally thin, labelled protocol translators representing accumulated integration eras.

The old machine is the ledger authority. The cluster knows what it submitted; the settlement processor knows what posted. A red beacon illuminates **only** when the reconciled balance difference is nonzero.

## Run the software reference stack

Python 3.11+ is sufficient; the reference machine and terminal server use only the standard library.

```sh
python -m decimal_iron serve
```

Open <http://127.0.0.1:8080/>. The browser is a 24×80 renderer for the processor's byte stream. It sends keyboard bytes; it has no payment or ledger API. Use `Ctrl+C` to stop the server. The append-only journal is written to `data/ledger.jsonl` and replayed at startup.

The server has no authentication or TLS; keep it on loopback or a trusted
private network. Setting `--host` to a non-loopback address exposes the
synthetic command interface to reachable clients. A file-backed journal is
single-process: its first server holds an exclusive OS lock until it stops,
and a second server using the same journal path is refused.

The `/panel` page shows register, word-mark, position-meter and reconciliation
signals from modeled processor state. Its examine and deposit controls are
limited to observation and reserved scratch cells.

Run the scripted end-of-day demonstration:

```sh
python -m decimal_iron demo --output artifacts/clearing-day
```

The output directory must be empty or new. The demo covers guarded day transitions, synthetic member payments, a reasoned limit override, idempotent reversal, a lost acknowledgement resolved by inquiry, net settlement, an injected reconciliation break, beacon recovery and journal replay. It writes a closing report and journal.

## Run the terminal gateway locally

In a second terminal, start the bounded gateway with its own delivery outbox:

```sh
python -m decimal_iron gateway \
  --terminal-url ws://127.0.0.1:8080/terminal \
  --state data/gateway.sqlite3
```

Open the processor day through the terminal screen before sending traffic. The
gateway exposes `POST /payments`, `GET /payments/{id}`, `/healthz`, and
`/readyz`; its worker translates JSON through XML and a fixed host record,
then uses the terminal-only adapter. A deterministic producer is available:

```sh
python -m decimal_iron bank --bank-id BANK-1 --max-requests 4 --interval-seconds 0
```

## Kubernetes scaffold

Build `decimal-iron:dev` and make that image available to the cluster, then
apply the scaffold:

```sh
docker build -t decimal-iron:dev .
kubectl apply -k deploy/kubernetes
```

The manifests define one processor with a persistent journal, one gateway with
a persistent bounded outbox, three finite seeded synthetic bank producers and
network policies that route bank traffic only to the gateway and gateway
traffic only to the processor terminal. Bank pods wait for the operator to
open a business day before producing their bounded batch. With a local port
forward to the gateway service, its root page shows queue and delivery
projections; the processor panel remains at `/panel` on the processor service.

The manifests are a deployment scaffold. No container build or Kubernetes
cluster deployment has been run as part of this preliminary implementation.

Terminal commands and the exact output-byte grammar are specified in [the protocol contract](docs/terminal-protocol.md). See [architecture](docs/architecture.md), [interfaces](docs/interfaces.md), [protocol strata](docs/protocol-strata.md), [panel and FPGA scaffold](docs/hardware-panel.md), and [roadmap](docs/roadmap.md).

## Non-goals

No actual banking connectivity; no genuine customer information; no production payment claims; no elaborate compliance or fraud simulator; no full IBM 1401 binary compatibility; no dependency on Kubernetes for the core to function.

## Status

The preliminary stack includes the M0 reference machine and demo, a
state-derived virtual panel, an original 256-cell decimal CPU software model,
board-neutral SystemVerilog core and panel signal contracts, shared transfer
vectors, a terminal-only payment gateway with bounded persistent outbox,
visible protocol translations, synthetic bank producers and Kubernetes
manifests. FPGA synthesis, board wiring, container build, and cluster
deployment remain unvalidated. The project is synthetic and is not a payment
service.

## License

MIT (see LICENSE).
