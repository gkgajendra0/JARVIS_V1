"""Repeatable synthetic memory lifecycle probe; never a Librarian quality claim.

The full real service can be plugged in by mapping its documented MCP tool names
and record-result schema. No owner data, live Jarvis runtime, model or API keys.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .bridge import (
    ExperimentConfig,
    LibrarianError,
    LibrarianExperiment,
    McpStdioClient,
)


def decode_records(result: dict[str, Any]) -> list[dict[str, str]]:
    """Narrow fixture result contract, not a claimed universal Librarian schema."""
    if "structuredContent" in result:
        data = result["structuredContent"]
    else:
        blocks = result.get("content")
        if not isinstance(blocks, list) or len(blocks) != 1:
            raise LibrarianError("Unrecognized recall result content shape")
        block = blocks[0]
        if not isinstance(block, dict) or block.get("type") != "text":
            raise LibrarianError("Unrecognized recall result block")
        value = block.get("text")
        if not isinstance(value, str) or len(value) > 262144:
            raise LibrarianError("Recall payload absent or too large")
        try:
            data = json.loads(value)
        except ValueError as exc:
            raise LibrarianError("Recall payload not structured JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise LibrarianError("Recall output needs verified records mapping")
    records: list[dict[str, str]] = []
    for record in data["records"]:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("source"), str)
            or not isinstance(record.get("text"), str)
        ):
            raise LibrarianError("Recall record missing source/text")
        records.append({"source": record["source"], "text": record["text"]})
    return records


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percent
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo), 3)


def run_probe(
    config: ExperimentConfig,
    client_factory: Callable[..., McpStdioClient] = McpStdioClient,
) -> dict[str, Any]:
    """Run fictional memory operations in a fresh namespace with no side effects on Jarvis."""
    nonce = uuid.uuid4().hex[:12]
    travel = "synthetic-" + nonce + "-travel"
    study = "synthetic-" + nonce + "-study"
    checks: list[dict[str, Any]] = []
    measurements: list[float] = []
    started = time.time()

    def execute(
        adapter: LibrarianExperiment,
        operation: str,
        *,
        project: str,
        query: str = "",
        text: str = "",
        source: str = "",
        target: str = "",
    ) -> list[dict[str, str]]:
        response, latency_ms = adapter.invoke(
            operation,
            project=project,
            query=query,
            text=text,
            source=source,
            target=target,
            allow_synthetic_write=True,
        )
        measurements.append(latency_ms)
        return decode_records(response) if operation == "recall" else []

    def record(name: str, condition: bool) -> None:
        checks.append({"check": name, "passed": bool(condition)})

    try:
        with client_factory(config.command, config.cwd, config.timeout) as client:
            adapter = LibrarianExperiment(config, client)
            for operation in ("remember", "recall", "correct", "forget"):
                if operation not in config.operations:
                    raise LibrarianError("Missing required operation: " + operation)

            execute(
                adapter, "remember", project=travel,
                source="fixture-" + nonce + "-1", text="vehicle: Jimny",
            )
            initial = execute(adapter, "recall", project=travel, query="vehicle")
            record(
                "remember_and_recall",
                len(initial) == 1
                and initial[0] == {
                    "source": "fixture-" + nonce + "-1",
                    "text": "vehicle: Jimny",
                },
            )
            separated = execute(adapter, "recall", project=study, query="vehicle")
            record("cross_project_isolation", separated == [])

            execute(
                adapter, "correct", project=travel,
                source="fixture-" + nonce + "-2",
                target="fixture-" + nonce + "-1",
                text="vehicle: corrected synthetic 4x4",
            )
            corrected = execute(adapter, "recall", project=travel, query="vehicle")
            record(
                "superseded_fact_absent",
                corrected == [{
                    "source": "fixture-" + nonce + "-2",
                    "text": "vehicle: corrected synthetic 4x4",
                }],
            )

            execute(
                adapter, "forget", project=travel,
                source="fixture-" + nonce + "-3",
                target="fixture-" + nonce + "-2",
            )
            deleted = execute(adapter, "recall", project=travel, query="vehicle")
            record("forget_removes_fact", deleted == [])
    except (LibrarianError, OSError, ValueError, TimeoutError) as exc:
        # Never put arbitrary server strings, queries, text, or credentials into report.
        checks.append({
            "check": "transport_or_contract",
            "passed": False,
            "error_type": type(exc).__name__,
        })
    return {
        "schema": "jarvis.synthetic_mcp_probe.v1",
        "backend_verified": False,
        "official_librarian_quality_measured": False,
        "synthetic_only": True,
        "started_unix": started,
        "duration_ms": round((time.time() - started) * 1000, 3),
        "status": "PASS" if len(checks) == 4 and all(c["passed"] for c in checks)
        else "FAIL",
        "checks": checks,
        "latency_ms": {
            "count": len(measurements),
            "p50": percentile(measurements, 0.5),
            "p95": percentile(measurements, 0.95),
            "mean": round(statistics.mean(measurements), 3)
            if measurements else None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic MCP protocol probe")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = ExperimentConfig.from_file(args.config)
        report = run_probe(config)
        if args.output.exists():
            raise LibrarianError("Report path already exists (no overwrite)")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
        print(json.dumps({
            "status": report["status"],
            "checks_passed": sum(c["passed"] for c in report["checks"]),
            "checks_total": len(report["checks"]),
            "report_written": True,
        }))
        return 0 if report["status"] == "PASS" else 1
    except (LibrarianError, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "FAIL", "error_type": type(exc).__name__
        }), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
