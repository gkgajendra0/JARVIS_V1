"""Offline/zero-cost Hindsight import archive preflight.

Requires no Hindsight SDK, Google/OpenAI keys, Ollama, Docker, server, or DB.
Prints only aggregate counts, hash and safety flags. No network call or
file write. This is NOT a real Hindsight import or consolidation test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jarvis.memory.hindsight_transfer_shadow import (
    build_synthetic_external_fact_zip,
    inspect_synthetic_archive,
)


def main() -> None:
    archive = build_synthetic_external_fact_zip()
    print(json.dumps(inspect_synthetic_archive(archive), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
