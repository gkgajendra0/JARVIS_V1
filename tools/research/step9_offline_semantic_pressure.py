"""Step 9: offline-only owner-machine baseline for harder memory retrieval.

An explicit future Hindsight scale importer is intentionally NOT included.
This CLI is safe to run with Python -I and never inspects Docker or localhost.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jarvis.memory.research_semantic_pressure import offline_report


def main() -> None:
    report = offline_report()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
