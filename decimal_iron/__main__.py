"""Command line entry point for the Decimal Iron reference machine."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .bank import run_synthetic_bank
from .demo import run_demo
from .gateway import serve_gateway
from .machine import DecimalMachine
from .web import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="decimal-iron", description="Run the synthetic decimal clearing machine")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="serve the browser byte-stream terminal")
    serve_parser.add_argument("--journal", default="data/ledger.jsonl", help="append-only journal path")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)

    gateway_parser = subparsers.add_parser("gateway", help="serve the bounded terminal-only payment gateway")
    gateway_parser.add_argument("--host", default="0.0.0.0")
    gateway_parser.add_argument("--port", type=int, default=8090)
    gateway_parser.add_argument("--terminal-url", default=os.environ.get("DECIMAL_IRON_TERMINAL_URL", "ws://127.0.0.1:8080/terminal"))
    gateway_parser.add_argument("--max-queue", type=int, default=32)
    gateway_parser.add_argument("--state", default="data/gateway.sqlite3")

    bank_parser = subparsers.add_parser("bank", help="send a finite synthetic payment batch to the gateway")
    bank_parser.add_argument("--gateway-url", default=os.environ.get("DECIMAL_IRON_GATEWAY_URL", "http://127.0.0.1:8090"))
    bank_parser.add_argument("--bank-id", default=os.environ.get("POD_NAME", "BANK-1"))
    bank_parser.add_argument("--max-requests", type=int, default=12)
    bank_parser.add_argument("--interval-seconds", type=float, default=2.0)
    bank_parser.add_argument("--seed", default="decimal-iron")
    bank_parser.add_argument("--idle-seconds", type=float, default=0.0)
    bank_parser.add_argument("--wait-for-open-seconds", type=float, default=0.0)

    demo_parser = subparsers.add_parser("demo", help="run the deterministic end-of-day demonstration")
    demo_parser.add_argument("--output", default="artifacts/clearing-day", help="new or empty output directory")

    args = parser.parse_args()
    if args.command in (None, "serve"):
        journal = Path(args.journal if args.command == "serve" else "data/ledger.jsonl")
        host = args.host if args.command == "serve" else "127.0.0.1"
        port = args.port if args.command == "serve" else 8080
        serve(DecimalMachine(journal), host=host, port=port)
    elif args.command == "demo":
        summary = run_demo(args.output)
        print(f"Closing report: {Path(args.output) / 'closing-report.txt'}")
        print(f"Journal: {Path(args.output) / 'journal.jsonl'}")
        print(f"Replay matches: {summary['replay_matches']}")
    elif args.command == "gateway":
        serve_gateway(
            host=args.host,
            port=args.port,
            terminal_url=args.terminal_url,
            max_queue=args.max_queue,
            state_path=args.state,
        )
    elif args.command == "bank":
        run_synthetic_bank(
            gateway_url=args.gateway_url,
            bank_id=args.bank_id,
            max_requests=args.max_requests,
            interval_seconds=args.interval_seconds,
            seed=args.seed,
            idle_seconds=args.idle_seconds,
            wait_for_open_seconds=args.wait_for_open_seconds,
        )


if __name__ == "__main__":
    main()
