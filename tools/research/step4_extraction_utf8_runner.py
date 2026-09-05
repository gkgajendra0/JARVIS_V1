"""Windows-safe UTF-8 launcher for the Step-4 extraction bake-off.

The underlying research harness intentionally prints one JSON document to stdout.
On Windows PowerShell, redirected native stdout can be displayed later using a
legacy code page even when Python emitted UTF-8. This launcher avoids shell text
encoding entirely: it starts the harness in Python UTF-8 mode, captures the raw
stdout bytes, and writes them directly to the requested result file.

Example::

    .\\.step4-extraction-venv\\Scripts\\python.exe \
        tools\research\\step4_extraction_utf8_runner.py \
        --output .step4-openai-full.json --providers openai

All arguments other than ``--output`` are passed through unchanged to
``step4_memory_extraction_bakeoff.py``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--output",
        required=True,
        help="UTF-8 JSON result file written from the child process stdout bytes.",
    )
    args, passthrough = parser.parse_known_args()

    harness = Path(__file__).with_name("step4_memory_extraction_bakeoff.py")
    command = [sys.executable, "-X", "utf8", str(harness), *passthrough]

    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=None,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode

    output_path = Path(args.output)
    output_path.write_bytes(completed.stdout)

    # Validate that the file is actually UTF-8 before reporting success.
    output_path.read_text(encoding="utf-8")
    print(f"Wrote UTF-8 result: {output_path} ({len(completed.stdout)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
