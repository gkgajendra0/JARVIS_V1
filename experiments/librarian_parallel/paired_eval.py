"""Paired A/B report from independently reviewed Jarvis answer receipts.

Does not execute Jarvis, generate answers, or claim real Librarian results.
Requires same cases, same model/config and explicit independent judgments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bridge import LibrarianError
from .scenario_runner import percentile

REQUIRED = frozenset(
    {
        "case_id",
        "fixture_digest",
        "model_id",
        "model_config_digest",
        "completed",
        "correct",
        "supported",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "reviewer_id",
    }
)


def load_reviewed_receipts(path: Path) -> dict[str, dict[str, Any]]:
    if path.stat().st_size > 200000:
        raise LibrarianError("Receipt file exceeds size limit")
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise LibrarianError("Invalid A/B receipt JSON") from exc
        if not isinstance(row, dict) or set(row) != REQUIRED:
            raise LibrarianError("A/B receipt requires exact reviewed schema")
        case_id = row["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in rows:
            raise LibrarianError("Duplicate or invalid case ID")
        for field in (
            "fixture_digest",
            "model_id",
            "model_config_digest",
            "reviewer_id",
        ):
            if not isinstance(row[field], str) or not row[field]:
                raise LibrarianError("Required comparable metadata missing")
        for field in ("completed", "correct", "supported"):
            if type(row[field]) is not bool:
                raise LibrarianError(
                    "Answer judgments must be reviewer-supplied booleans"
                )
        if not row["completed"] and (row["correct"] or row["supported"]):
            raise LibrarianError("Incomplete answer cannot be correct or supported")
        for field in ("latency_ms", "input_tokens", "output_tokens"):
            v = row[field]
            if type(v) not in (int, float) or v < 0 or v > 100000000:
                raise LibrarianError("Invalid timing/token measurement")
        rows[case_id] = row
        if len(rows) > 500:
            raise LibrarianError("A/B case limit exceeded")
    if not rows:
        raise LibrarianError("A/B receipts cannot be empty")
    return rows


def score_pair(
    baseline: dict[str, dict[str, Any]], augmented: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if set(baseline) != set(augmented):
        raise LibrarianError("A/B cases must match exactly (no silently missing cases)")
    for case_id, a in baseline.items():
        b = augmented[case_id]
        for field in ("fixture_digest", "model_id", "model_config_digest"):
            if a[field] != b[field]:
                raise LibrarianError("A/B runs are not comparable: " + field)

    def summarize(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
        ordered = [rows[key] for key in sorted(rows)]
        complete = [r for r in ordered if r["completed"]]
        latencies = [r["latency_ms"] for r in complete]
        return {
            "total": len(ordered),
            "completed": len(complete),
            "correct": sum(r["completed"] and r["correct"] for r in ordered),
            "supported": sum(r["completed"] and r["supported"] for r in ordered),
            "incorrect_or_incomplete": sum(
                not r["completed"] or not r["correct"] for r in ordered
            ),
            "latency_p50_ms": percentile(latencies, 0.5),
            "latency_p95_ms": percentile(latencies, 0.95),
            "input_tokens_total": sum(r["input_tokens"] for r in ordered),
            "output_tokens_total": sum(r["output_tokens"] for r in ordered),
        }

    a, b = summarize(baseline), summarize(augmented)
    improved = [
        case_id
        for case_id in sorted(baseline)
        if not baseline[case_id]["correct"] and augmented[case_id]["correct"]
    ]
    regressed = [
        case_id
        for case_id in sorted(baseline)
        if baseline[case_id]["correct"] and not augmented[case_id]["correct"]
    ]
    return {
        "schema": "jarvis.parallel_reviewed_ab.v1",
        "reviewed_receipts_only": True,
        "creator_librarian_backend_verified": False,
        "actual_librarian_performance_claimed": False,
        "model_id": next(iter(baseline.values()))["model_id"],
        "baseline": a,
        "augmented": b,
        "correctness_delta_cases": b["correct"] - a["correct"],
        "correctness_improvements": improved,
        "correctness_regressions": regressed,
        "note": (
            "A scoring tool cannot independently establish reviewer accuracy, "
            "randomization, or actual Librarian installation."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strict independently reviewed A/B receipts"
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--augmented", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = score_pair(
            load_reviewed_receipts(args.baseline),
            load_reviewed_receipts(args.augmented),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
        print(
            json.dumps(
                {
                    "status": "SCORED",
                    "cases": report["baseline"]["total"],
                    "actual_librarian_performance_claimed": False,
                }
            )
        )
        return 0
    except (LibrarianError, OSError, ValueError) as exc:
        print(
            json.dumps({"status": "FAILED", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
