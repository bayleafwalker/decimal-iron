#!/usr/bin/env python3
"""Run shared transfer vectors against the RTL when Icarus Verilog is present."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    vectors = json.loads((ROOT / "vectors" / "transaction_vectors.json").read_text(encoding="ascii"))
    compiler, runtime = shutil.which("iverilog"), shutil.which("vvp")
    if not compiler or not runtime:
        print("SKIP: iverilog and vvp are required to run the RTL testbench.")
        print(f"Reference vectors available: {len(vectors)}")
        return 0
    with tempfile.TemporaryDirectory(prefix="decimal-iron-rtl-") as directory:
        executable = Path(directory) / "decimal-core.vvp"
        subprocess.run(
            [compiler, "-g2012", "-s", "decimal_core_tb", "-o", str(executable),
             str(ROOT / "rtl" / "decimal_core.sv"), str(ROOT / "rtl" / "tb" / "decimal_core_tb.sv")],
            check=True,
        )
        for vector in vectors:
            expected_source = vector["source_balance"] - vector["amount_minor"]
            expected_destination = vector["destination_balance"] + vector["amount_minor"]
            output = subprocess.run(
                [runtime, str(executable), f"+SRC={vector['source_balance']}",
                 f"+DST={vector['destination_balance']}", f"+AMOUNT={vector['amount_minor']}"],
                check=True,
                text=True,
                capture_output=True,
                timeout=10,
            ).stdout
            result_line = next((line for line in output.splitlines() if line.startswith("RESULT ")), None)
            if result_line is None:
                raise RuntimeError(f"RTL testbench returned no result for {vector['name']}: {output}")
            fields = result_line.split()
            source, destination = int(fields[1]), int(fields[2])
            if source != expected_source or destination != expected_destination:
                raise AssertionError(f"{vector['name']}: got {source}/{destination}, expected {expected_source}/{expected_destination}")
            print(f"PASS: {vector['name']} -> source={source}, destination={destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
