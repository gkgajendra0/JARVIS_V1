"""Paired outcome report must not manufacture performance claims."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.librarian_parallel.bridge import LibrarianError
from experiments.librarian_parallel.paired_eval import (
    load_reviewed_receipts,
    score_pair,
)


def row(case_id: str, *, correct: bool = True) -> dict:
    return {
        "case_id": case_id,
        "fixture_digest": "sha256:fictional-test-fixture-1",
        "model_id": "same-synthetic-model",
        "model_config_digest": "sha256:fictional-config-1",
        "completed": True,
        "correct": correct,
        "supported": correct,
        "latency_ms": 100.0,
        "input_tokens": 10,
        "output_tokens": 10,
        "reviewer_id": "fictional-reviewer",
    }


class PairedTests(unittest.TestCase):
    def test_pair_accurate_counts_and_regressions(self) -> None:
        baseline = {"one": row("one", correct=False), "two": row("two")}
        augmented = {"one": row("one"), "two": row("two", correct=False)}
        result = score_pair(baseline, augmented)
        self.assertEqual(result["baseline"]["total"], 2)
        self.assertEqual(result["correctness_delta_cases"], 0)
        self.assertEqual(result["correctness_improvements"], ["one"])
        self.assertEqual(result["correctness_regressions"], ["two"])
        self.assertFalse(result["actual_librarian_performance_claimed"])

    def test_missing_case_or_different_model_refused(self) -> None:
        with self.assertRaisesRegex(LibrarianError, "exactly"):
            score_pair({"one": row("one")}, {"two": row("two")})
        changed = row("one")
        changed["model_id"] = "different-model"
        with self.assertRaisesRegex(LibrarianError, "not comparable"):
            score_pair({"one": row("one")}, {"one": changed})

    def test_duplicate_and_incomplete_receipt_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rows.jsonl"
            r = row("one")
            path.write_text(json.dumps(r) + "\n" + json.dumps(r), encoding="utf-8")
            with self.assertRaisesRegex(LibrarianError, "Duplicate"):
                load_reviewed_receipts(path)
            r["completed"] = False
            path.write_text(json.dumps(r), encoding="utf-8")
            with self.assertRaisesRegex(LibrarianError, "Incomplete"):
                load_reviewed_receipts(path)

    def test_no_implicit_or_self_generated_judgments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rows.jsonl"
            r = row("one")
            del r["reviewer_id"]
            path.write_text(json.dumps(r), encoding="utf-8")
            with self.assertRaisesRegex(LibrarianError, "reviewed schema"):
                load_reviewed_receipts(path)


if __name__ == "__main__":
    unittest.main()
