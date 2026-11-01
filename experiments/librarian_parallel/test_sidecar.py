"""Standalone sidecar replay tests; no real memory or model."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.librarian_parallel.bridge import ExperimentConfig, LibrarianError
from experiments.librarian_parallel.sidecar import read_synthetic_events, replay

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ExperimentConfig(
    [sys.executable, "-m", "experiments.librarian_parallel.fixture_mcp_server"],
    str(ROOT),
    5,
    {
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
    },
)


class SidecarTests(unittest.TestCase):
    def test_end_to_end_fictional_stream(self) -> None:
        events = read_synthetic_events(
            ROOT / "experiments/librarian_parallel/fixtures/fictional-nepal.jsonl"
        )
        result = replay(CONFIG, events, allow_synthetic_write=True)
        self.assertEqual(len(result["events"]), 7)
        self.assertEqual(
            result["events"][1]["candidate_context"],
            [
                {
                    "source": "fixture-101",
                    "text": "The vehicle is a fictional Jimny.",
                    "project": "synthetic-nepal",
                }
            ],
        )
        self.assertEqual(result["events"][2]["candidate_context"], [])
        self.assertEqual(
            result["events"][4]["candidate_context"],
            [
                {
                    "source": "fixture-102",
                    "text": "Corrected fictional vehicle is a test-only SUV.",
                    "project": "synthetic-nepal",
                }
            ],
        )
        self.assertEqual(result["events"][6]["candidate_context"], [])
        self.assertFalse(result["actual_librarian_backend_verified"])
        self.assertFalse(result["jarvis_response_generated"])

    def test_write_rejected_without_explicit_opt_in(self) -> None:
        events = read_synthetic_events(
            ROOT / "experiments/librarian_parallel/fixtures/fictional-nepal.jsonl"
        )
        with self.assertRaisesRegex(LibrarianError, "opt-in"):
            replay(CONFIG, events)

    def test_owner_project_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "bad.jsonl"
            file.write_text(
                json.dumps(
                    {
                        "case_id": "a01",
                        "operation": "recall",
                        "project": "my-real-nepal",
                        "query": "vehicle",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(LibrarianError, "synthetic"):
                read_synthetic_events(file)

    def test_event_limit_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "bad.jsonl"
            event = {
                "case_id": "a01",
                "operation": "recall",
                "project": "synthetic-test",
                "query": "q",
            }
            file.write_text((json.dumps(event) + "\n") * 101, encoding="utf-8")
            with self.assertRaisesRegex(LibrarianError, "Too many"):
                read_synthetic_events(file)
            event["secret_token"] = "fake"
            file.write_text(json.dumps(event), encoding="utf-8")
            with self.assertRaisesRegex(LibrarianError, "Unknown"):
                read_synthetic_events(file)


if __name__ == "__main__":
    unittest.main()
