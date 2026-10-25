# Protocol strata

The cluster demo shows successive message shapes in one process. The formats
are explicit project fixtures; they are not real FIM clearing standards.

| Layer | Representation | Responsibility |
| --- | --- | --- |
| Modern bank | `cloud-json-v1` | Typed payment identity, member accounts, FIM, integer penni |
| Early integration bridge | `xml-clearing-2001` | Named fields and a carried idempotency key |
| Host batch record | `fixed-host-record-1982` | 96 ASCII columns, fixed offsets and SHA-256-derived check field |
| Processor boundary | `terminal-24x80-v1` | `PAY id source destination FIM amount` as terminal keyboard bytes |

The fixed record contains a 74-column body, a 16-column checksum and six blank
reserved columns. Payment identity, source, destination, currency and amount
are checked after decoding. The terminal adapter then sends the decoded
business fields to the 24×80 stream and reads the processor's result row.

The gateway's SQLite outbox records delivery state and allows a bounded queue
to recover after process restart. It is not a posting ledger. A worker restart
resubmits the same payment id; the terminal adapter inquires and retries with
that id, and the processor journal remains authoritative for whether it posted.

The gateway accepts only payment intents. It has no interface to processor
positions, journals, day switches, reversals, settlement or reconciliation.
`/payments/{id}` reports the gateway's delivery status and protocol trace, not
an independently computed ledger view.

## Local smoke path

Run the processor and gateway in separate terminals:

```sh
python -m decimal_iron serve --host 127.0.0.1 --journal data/processor.jsonl
python -m decimal_iron gateway --terminal-url ws://127.0.0.1:8080/terminal --state data/gateway.sqlite3
```

Open `http://127.0.0.1:8080/`, select the day key to `OPEN`, then enter the
business date. Submit one synthetic request to the gateway:

```sh
curl -sS -X POST http://127.0.0.1:8090/payments \
  -H 'content-type: application/json' \
  -d '{"payment_id":"BANK-1-000000000001","bank_id":"BANK-1","source":"FI01","destination":"FI02","currency":"FIM","amount_minor":1200}'
```

Poll the returned payment id at `/payments/{id}`. The request receives HTTP
202 while queued; a `POSTED` status includes the processor's terminal journal
sequence. `REJECTED` and `UNKNOWN_OUTCOME` remain visible rather than being
silently retried with a new identity.

The gateway root page shows recent outbox state and the processor phase read
through the same serialized terminal cursor. It is a delivery projection and
does not derive balances or posting decisions.
