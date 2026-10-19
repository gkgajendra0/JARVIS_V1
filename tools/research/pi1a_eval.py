"""Offline PI-1A benchmark preflight; prints no conversation contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jarvis.memory.personal_eval import (
    corpus_manifest,
    validate_paired_annotations,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "tests" / "fixtures" / "personal_intelligence"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--annotations", type=Path, default=None,
        help="paired response annotations to validate, not automatic scoring",
    )
    args = parser.parse_args()
    cases = _FIXTURES / "pi1a_cases.json"
    gold = _FIXTURES / "pi1a_gold.json"
    result = (
        corpus_manifest(cases, gold)
        if args.annotations is None
        else validate_paired_annotations(cases, gold, args.annotations)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
