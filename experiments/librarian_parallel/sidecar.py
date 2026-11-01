"""Separate replayable synthetic Librarian sidecar; never imported by production Jarvis.

Processes an independently supplied fictional conversation/event stream. Returns a
bounded, source-identified candidate context for a future Jarvis A/B runner.
Does not perform model inference, route voice, or grant tool/action authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from .bridge import (
    WRITE_OPERATIONS,
    ExperimentConfig,
    LibrarianError,
    LibrarianExperiment,
    McpStdioClient,
)
from .fingerprints import config_fingerprint, fingerprint
from .scenario_runner import decode_records

EVENT_KEYS = frozenset(
    {"case_id", "operation", "project", "text", "query", "source", "target"}
)
EVENT_OPERATIONS = frozenset({"recall", "remember", "correct", "forget"})
CASE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_EVENTS = 100
MAX_BYTES = 250000
MAX_CONTEXT_CHARS = 4096


def read_synthetic_events(path: Path) -> list[dict[str, str]]:
    if path.stat().st_size > MAX_BYTES:
        raise LibrarianError("Input fixture exceeds synthetic test size limit")
    events: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise LibrarianError("Invalid synthetic event JSON") from exc
        if not isinstance(event, dict) or not set(event).issubset(EVENT_KEYS):
            raise LibrarianError("Unknown or malformed event fields")
        if not all(isinstance(v, str) for v in event.values()):
            raise LibrarianError("Event fields must be strings")
        if (
            not CASE_ID.fullmatch(event.get("case_id", ""))
            or event.get("operation") not in EVENT_OPERATIONS
        ):
            raise LibrarianError("Event case ID or operation not permitted")
        if not event.get("project", "").startswith("synthetic-"):
            raise LibrarianError("Event project must be synthetic-*")
        if len(event.get("query", "")) > 500 or len(event.get("text", "")) > 2000:
            raise LibrarianError("Event query/text length exceeded")
        if event["operation"] in WRITE_OPERATIONS and not event.get(
            "source", ""
        ).startswith("fixture-"):
            raise LibrarianError("Write event requires fixture-* source")
        events.append(event)
        if len(events) > MAX_EVENTS:
            raise LibrarianError("Too many synthetic events")
    if not events:
        raise LibrarianError("Synthetic event stream is empty")
    return events


def replay(
    config: ExperimentConfig,
    events: list[dict[str, str]],
    *,
    allow_synthetic_write: bool = False,
) -> dict[str, Any]:
    """Replay a sequence in one external MCP session; never touch the Jarvis DB."""
    outputs: list[dict[str, Any]] = []
    with McpStdioClient(config.command, config.cwd, config.timeout) as client:
        advertised_tools_digest = fingerprint(client.list_tools())
        adapter = LibrarianExperiment(config, client)
        for event in events:
            op = event["operation"]
            if op in WRITE_OPERATIONS and not allow_synthetic_write:
                raise LibrarianError("Explicit synthetic write opt-in required")
            result, ms = adapter.invoke(
                op,
                project=event["project"],
                query=event.get("query", ""),
                text=event.get("text", ""),
                source=event.get("source", ""),
                target=event.get("target", ""),
                allow_synthetic_write=allow_synthetic_write,
            )
            item: dict[str, Any] = {
                "case_id": event["case_id"],
                "operation": op,
                "project": event["project"],
                "elapsed_ms": ms,
                "result_type": "write_receipt"
                if op in WRITE_OPERATIONS
                else "retrieval",
            }
            if op == "recall":
                records = decode_records(result)
                if sum(len(rec["text"]) for rec in records) > MAX_CONTEXT_CHARS:
                    raise LibrarianError("Retrieved context exceeds bounded budget")
                if len(records) > 20:
                    raise LibrarianError("Too many retrieved context records")
                # Source-identified untrusted candidate only; never system instructions.
                item["candidate_context"] = records
            outputs.append(item)
    return {
        "schema": "jarvis.librarian_sidecar_fixture.v1",
        "run_id": uuid.uuid4().hex,
        "synthetic_only": True,
        "fixture_digest": fingerprint(events),
        "config_digest": config_fingerprint(config),
        "mcp_tool_schema_digest": advertised_tools_digest,
        "actual_librarian_backend_verified": False,
        "jarvis_response_generated": False,
        "events": outputs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated synthetic memory sidecar")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-synthetic-write", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = ExperimentConfig.from_file(args.config)
        events = read_synthetic_events(args.events)
        report = replay(
            config, events, allow_synthetic_write=args.allow_synthetic_write
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "events": len(events),
                    "synthetic_only": True,
                    "output_written": True,
                }
            )
        )
        return 0
    except (LibrarianError, OSError, ValueError) as exc:
        print(
            json.dumps({"status": "FAIL", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
