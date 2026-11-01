"""Synthetic-only end-to-end scenario runner checks."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from experiments.librarian_parallel.bridge import ExperimentConfig, LibrarianError
from experiments.librarian_parallel.scenario_runner import (
    decode_records,
    percentile,
    run_probe,
)

ROOT = Path(__file__).resolve().parents[2]
SERVER = [sys.executable, "-m", "experiments.librarian_parallel.fixture_mcp_server"]
OPS = {
    "recall": {
        "tool": "fixture_recall",
        "arguments": {"project": "{project}", "query": "{query}"},
    },
    "remember": {
        "tool": "fixture_remember",
        "arguments": {
            "project": "{project}",
            "text": "{text}",
            "source": "{source}",
        },
    },
    "correct": {
        "tool": "fixture_correct",
        "arguments": {
            "project": "{project}",
            "text": "{text}",
            "source": "{source}",
            "target": "{target}",
        },
    },
    "forget": {
        "tool": "fixture_forget",
        "arguments": {
            "project": "{project}",
            "source": "{source}",
            "target": "{target}",
        },
    },
}


class ScenarioTests(unittest.TestCase):
    def test_synthetic_lifecycle_passes_but_does_not_claim_real_librarian(self) -> None:
        report = run_probe(
            ExperimentConfig(SERVER, str(ROOT), 5, OPS), allow_synthetic_write=True
        )
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(len(report["checks"]), 4)
        self.assertTrue(all(row["passed"] for row in report["checks"]))
        self.assertEqual(report["latency_ms"]["count"], 7)
        self.assertFalse(report["backend_verified"])
        self.assertFalse(report["official_librarian_quality_measured"])

    def test_writes_disabled_by_default(self) -> None:
        report = run_probe(ExperimentConfig(SERVER, str(ROOT), 5, OPS))
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"][0]["passed"])

    def test_missing_mappings_fails_without_fake_success(self) -> None:
        report = run_probe(
            ExperimentConfig(SERVER, str(ROOT), 5, {"recall": OPS["recall"]}),
            allow_synthetic_write=True,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"][0]["passed"])

    def test_failures_do_not_include_owner_memory_or_raw_model_output(self) -> None:
        config = ExperimentConfig(["no-such-jarvis-executable-xyz"], str(ROOT), 5, OPS)
        report = run_probe(config, allow_synthetic_write=True)
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn("vehicle: Jimny", json.dumps(report))

    def test_strict_recall_shape(self) -> None:
        records = decode_records(
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"records":[{"source":"fixture-1","text":"hello"}]}',
                    }
                ]
            }
        )
        self.assertEqual(records, [{"source": "fixture-1", "text": "hello"}])
        with self.assertRaisesRegex(LibrarianError, "verified records"):
            decode_records({"structuredContent": {"matches": []}})
        with self.assertRaisesRegex(LibrarianError, "too large"):
            decode_records({"content": [{"type": "text", "text": "x" * 262145}]})

    def test_percentile_is_deterministic(self) -> None:
        self.assertIsNone(percentile([], 0.5))
        self.assertEqual(percentile([10, 20, 30, 40, 50], 0.95), 48)


if __name__ == "__main__":
    unittest.main()
