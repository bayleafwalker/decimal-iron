"""Command line entry point for the Decimal Iron reference machine."""

from __future__ import annotations

import argparse
from pathlib import Path

from .demo import run_demo
from .machine import DecimalMachine
from .web import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="decimal-iron", description="Run the synthetic decimal clearing machine")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="serve the browser byte-stream terminal")
    serve_parser.add_argument("--journal", default="data/ledger.jsonl", help="append-only journal path")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)

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


if __name__ == "__main__":
    main()
