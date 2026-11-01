"""Offline contract tests for experimental MCP adapter (no model, secrets or DB)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.librarian_parallel.bridge import (
    ExperimentConfig,
    LibrarianError,
    LibrarianExperiment,
    McpStdioClient,
)

ROOT = Path(__file__).resolve().parents[2]
SERVER = [sys.executable, "-m", "experiments.librarian_parallel.fixture_mcp_server"]
OPERATIONS = {
    "recall": {
        "tool": "fixture_recall",
        "arguments": {"project": "{project}", "query": "{query}"},
    },
    "remember": {
        "tool": "fixture_remember",
        "arguments": {"project": "{project}", "text": "{text}", "source": "{source}"},
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


def fixture_content(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


class TransportTests(unittest.TestCase):
    def test_initialize_discovery_and_unknown_tool_fails_closed(self) -> None:
        with McpStdioClient(SERVER, str(ROOT), timeout=5) as client:
            self.assertIn("fixture_recall", client.list_tools())
            with self.assertRaisesRegex(LibrarianError, "not advertised"):
                client.call_tool("made_up_tool", {})

    def test_missing_executable_fails(self) -> None:
        with self.assertRaises(OSError):
            with McpStdioClient(["this-command-does-not-exist-for-test-1234"]):
                pass

    def test_timeout_is_bounded(self) -> None:
        with self.assertRaises(LibrarianError):
            McpStdioClient(SERVER, timeout=0)

    def test_no_shell_execution(self) -> None:
        with self.assertRaises(LibrarianError):
            McpStdioClient("python -c print(1)")  # type: ignore[arg-type]


class ConfigTests(unittest.TestCase):
    def _load(self, value: dict) -> ExperimentConfig:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return ExperimentConfig.from_file(path)

    def test_requires_explicit_synthetic_mode(self) -> None:
        with self.assertRaisesRegex(LibrarianError, "synthetic-only"):
            self._load({"command": SERVER, "operations": {}})

    def test_requires_scoped_operations(self) -> None:
        with self.assertRaisesRegex(LibrarianError, "project scope"):
            self._load(
                {
                    "mode": "synthetic-only",
                    "command": SERVER,
                    "operations": {
                        "recall": {
                            "tool": "fixture_recall",
                            "arguments": {"query": "{query}"},
                        }
                    },
                }
            )

    def test_write_source_must_be_explicit(self) -> None:
        with self.assertRaisesRegex(LibrarianError, "source ID"):
            self._load(
                {
                    "mode": "synthetic-only",
                    "command": SERVER,
                    "operations": {
                        "remember": {
                            "tool": "fixture_remember",
                            "arguments": {"project": "{project}", "text": "{text}"},
                        }
                    },
                }
            )


class ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = McpStdioClient(SERVER, str(ROOT), timeout=5)
        self.client.__enter__()
        self.adapter = LibrarianExperiment(
            ExperimentConfig(SERVER, str(ROOT), 5, OPERATIONS), self.client
        )

    def tearDown(self) -> None:
        self.client.close()

    def test_synthetic_scoping_and_write_guard(self) -> None:
        with self.assertRaisesRegex(LibrarianError, "opt-in"):
            self.adapter.invoke(
                "remember", project="synthetic-nepal", text="Jimny", source="fixture-a"
            )
        with self.assertRaisesRegex(LibrarianError, "synthetic"):
            self.adapter.invoke("recall", project="real-person", query="vehicle")
        with self.assertRaisesRegex(LibrarianError, "fixture"):
            self.adapter.invoke(
                "remember",
                project="synthetic-nepal",
                text="Jimny",
                source="unverified",
                allow_synthetic_write=True,
            )

        self.adapter.invoke(
            "remember",
            project="synthetic-nepal",
            text="vehicle: Jimny",
            source="fixture-a",
            allow_synthetic_write=True,
        )
        nepal, latency = self.adapter.invoke(
            "recall", project="synthetic-nepal", query="vehicle"
        )
        other, _ = self.adapter.invoke(
            "recall", project="synthetic-interview", query="vehicle"
        )
        self.assertEqual(len(fixture_content(nepal)["records"]), 1)
        self.assertEqual(fixture_content(other)["records"], [])
        self.assertGreaterEqual(latency, 0)

    def test_correction_and_forgetting_are_isolated(self) -> None:
        self.adapter.invoke(
            "remember",
            project="synthetic-nepal",
            text="vehicle: first",
            source="fixture-1",
            allow_synthetic_write=True,
        )
        self.adapter.invoke(
            "correct",
            project="synthetic-nepal",
            text="vehicle: corrected",
            source="fixture-2",
            target="fixture-1",
            allow_synthetic_write=True,
        )
        result, _ = self.adapter.invoke("recall", project="synthetic-nepal", query="")
        self.assertEqual(
            fixture_content(result)["records"],
            [{"source": "fixture-2", "text": "vehicle: corrected"}],
        )
        self.adapter.invoke(
            "forget",
            project="synthetic-nepal",
            source="fixture-3",
            target="fixture-2",
            allow_synthetic_write=True,
        )
        result, _ = self.adapter.invoke("recall", project="synthetic-nepal", query="")
        self.assertEqual(fixture_content(result)["records"], [])

    def test_unknown_mapping_and_template_rejected(self) -> None:
        with self.assertRaisesRegex(LibrarianError, "not mapped"):
            self.adapter.invoke("search_unconfigured", project="synthetic-nepal")
        bad = LibrarianExperiment(
            ExperimentConfig(
                SERVER,
                str(ROOT),
                5,
                {
                    "recall": {
                        "tool": "fixture_recall",
                        "arguments": {"project": "{project}", "query": "{missing}"},
                    }
                },
            ),
            self.client,
        )
        with self.assertRaisesRegex(LibrarianError, "Unprovided"):
            bad.invoke("recall", project="synthetic-nepal")


if __name__ == "__main__":
    unittest.main()
