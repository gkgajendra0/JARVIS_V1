"""Offline accounting for project-memory TEXT lab console logs; no Jarvis imports.

Output contains validated receipt/diagnostic metadata, never conversation text.
Console evidence is untrusted: this does not grade answers, verify the database,
or reconstruct unreported provider attempts, token usage or account billing.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

TOKEN_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "tool_use_tokens",
        "audio_input_tokens",
        "audio_output_tokens",
        "text_input_tokens",
        "text_output_tokens",
        "image_input_tokens",
        "video_input_tokens",
    }
)
STAGES = frozenset(
    {
        "idle",
        "authorizing",
        "routing",
        "recording",
        "retrieving",
        "generating",
        "tool_personal",
        "tool_search",
        "tool_read",
        "answer_ready",
        "retention_paused",
        "source_not_eligible",
    }
)
ERRORS = frozenset(
    {
        "ValueError",
        "PermissionError",
        "RuntimeError",
        "OSError",
        "StructuredOutputError",
        "ValidationError",
        "TimeoutError",
        "ConnectionError",
        "LocalOpaError",
        "ClientError",
        "ServerError",
    }
)


def _uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("invalid metadata identity")
    if str(UUID(value)) != value:
        raise ValueError("noncanonical metadata identity")
    return value


def _receipt(row, *, allow_omission=False):
    allowed = {"committed", "omitted"} if allow_omission else {"committed"}
    if not isinstance(row, dict) or row.get("status") not in allowed:
        raise ValueError("uncommitted receipt")
    if any(type(row.get(k)) is not int or row[k] < 1 for k in ("sequence", "revision")):
        raise ValueError("invalid receipt order")
    return {
        "event_id": _uuid(row.get("event_id")),
        "thread_id": _uuid(row.get("thread_id")),
        "sequence": row["sequence"],
        "revision": row["revision"],
        "status": row["status"],
    }


def _latency(value):
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if value >= 0 and math.isfinite(value) else None
    except OverflowError:
        return None


def _usage(rows):
    if rows is None:
        return None
    if not isinstance(rows, list):
        return [{"invalid": True}]
    if not rows:
        return None
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            result.append({"invalid": True})
            continue
        operation = row.get("operation")
        if (
            not isinstance(operation, str)
            or not re.fullmatch(r"reply-[0-9]{1,2}", operation)
            or operation in seen
        ):
            result.append({"invalid": True})
            continue
        seen.add(operation)
        observed = row.get("observed")
        raw = row.get("usage")
        valid = type(observed) is bool and isinstance(raw, dict)
        metrics = {}
        if valid and observed:
            for key in TOKEN_KEYS & raw.keys():
                value = raw[key]
                if type(value) is int and value >= 0:
                    metrics[key] = value
                else:
                    valid = False
        result.append(
            {
                "operation": operation,
                "observed": observed is True and valid,
                "metrics": metrics if valid else {},
                "latency_ms": _latency(row.get("latency_ms")),
                "invalid": not valid,
            }
        )
    return result


def _reject_constant(_):
    raise ValueError("nonfinite JSON metadata")


class AcceptanceLog:
    def __init__(self):
        self.completed = {}
        self.failed = {}
        self.conflicts = set()
        self.duplicate_completed = 0
        self.duplicate_failed = 0
        self.invalid = 0
        self.uncorrelated = Counter()

    def _record(self, destination, request_id, record):
        if request_id in destination:
            if destination[request_id] != record:
                self.conflicts.add(request_id)
            elif destination is self.completed:
                self.duplicate_completed += 1
            else:
                self.duplicate_failed += 1
        else:
            destination[request_id] = record
        if request_id in self.completed and request_id in self.failed:
            self.conflicts.add(request_id)

    def feed(self, line):
        text = line.strip().lstrip("\ufeff")
        failure = text.startswith("NOT COMPLETED: ")
        if not failure and (
            not text.startswith("{")
            or not any(key in text for key in ('"user_receipt"', '"assistant_receipt"'))
        ):
            return
        try:
            if failure:
                decoder = json.JSONDecoder(parse_constant=_reject_constant)
                row, end = decoder.raw_decode(text[len("NOT COMPLETED: ") :])
                match = re.search(
                    r"; error=([A-Za-z_][A-Za-z_0-9]*)(?:\.|$)",
                    text[len("NOT COMPLETED: ") + end :],
                )
                error = match[1] if match and match[1] in ERRORS else "other"
                stage = row.get("stage")
                diagnostic = {
                    "stage": stage if stage in STAGES else "other",
                    "error": error,
                }
                if "request_id" in row and row["request_id"] is None:
                    self.uncorrelated[(diagnostic["stage"], error)] += 1
                else:
                    self._record(self.failed, _uuid(row.get("request_id")), diagnostic)
                return
            row = json.loads(text, parse_constant=_reject_constant)
            if not isinstance(row, dict) or not any(
                k in row for k in ("user_receipt", "assistant_receipt")
            ):
                return
            request_id = _uuid(row.get("request_id"))
            revision = row.get("context_revision")
            if not isinstance(revision, str) or not re.fullmatch(
                r"[a-f0-9]{64}", revision
            ):
                raise ValueError("invalid context revision")
            user, assistant = (
                _receipt(row.get("user_receipt")),
                _receipt(row.get("assistant_receipt"), allow_omission=True),
            )
            if (
                user["thread_id"] != assistant["thread_id"]
                or user["event_id"] == assistant["event_id"]
                or assistant["sequence"] <= user["sequence"]
                or assistant["revision"] <= user["revision"]
            ):
                raise ValueError("inconsistent receipt pair")
            self._record(
                self.completed,
                request_id,
                {
                    "context_revision": revision,
                    "user": user,
                    "assistant": assistant,
                    "usage": _usage(row.get("usage")),
                },
            )
        except (ValueError, TypeError, AttributeError, RecursionError):
            self.invalid += 1

    def summary(self):
        totals, samples, failures = Counter(), Counter(), Counter()
        thread_events = defaultdict(dict)
        event_requests = defaultdict(set)
        latencies = []
        reported = observed = unobserved = invalid_usage = missing_usage = omissions = 0
        for request_id, row in self.completed.items():
            if request_id in self.conflicts:
                continue
            omissions += row["assistant"]["status"] == "omitted"
            for receipt in (row["user"], row["assistant"]):
                thread_events[receipt["thread_id"]][receipt["event_id"]] = receipt[
                    "sequence"
                ]
                event_requests[receipt["event_id"]].add(request_id)
            if row["usage"] is None:
                missing_usage += 1
                continue
            for step in row["usage"]:
                invalid_usage += step["invalid"]
                if "operation" not in step:
                    continue
                reported += 1
                observed += step["observed"]
                unobserved += not step["observed"]
                if step["latency_ms"] is not None:
                    latencies.append(step["latency_ms"])
                for key, value in step["metrics"].items():
                    totals[key] += value
                    samples[key] += 1
        for request_id, row in self.failed.items():
            if request_id not in self.conflicts:
                failures[(row["stage"], row["error"])] += 1
        latencies.sort()
        return {
            "format": "jarvis-project-memory-log-summary-v1",
            "evidence_scope": "reported_console_metadata_only",
            "answer_quality": "not_evaluated",
            "billing_complete": False,
            "completed_requests": len(self.completed),
            "requests_with_assistant_omission": omissions,
            "failed_requests": len(self.failed),
            "reported_provider_steps": reported,
            "usage_observed_steps": observed,
            "usage_unobserved_steps": unobserved,
            "invalid_usage_steps": invalid_usage,
            "requests_missing_usage": missing_usage,
            "failed_requests_usage_unknown": len(self.failed),
            "uncorrelated_failure_lines": sum(self.uncorrelated.values()),
            "uncorrelated_failure_counts": [
                {"stage": stage, "error": error, "lines": count}
                for (stage, error), count in sorted(self.uncorrelated.items())
            ],
            "known_token_totals": dict(sorted(totals.items())),
            "token_metric_samples": dict(sorted(samples.items())),
            "provider_latency_ms": {
                "samples": len(latencies),
                "p50": latencies[math.ceil(len(latencies) * 0.5) - 1]
                if latencies
                else None,
                "p95": latencies[math.ceil(len(latencies) * 0.95) - 1]
                if latencies
                else None,
            },
            "failure_counts": [
                {"stage": stage, "error": error, "count": count}
                for (stage, error), count in sorted(failures.items())
            ],
            "threads": [
                {
                    "thread_id": key,
                    "reported_receipt_events": len(events),
                    "last_reported_sequence": max(events.values()),
                }
                for key, events in sorted(thread_events.items())
            ],
            "duplicate_completed_records": self.duplicate_completed,
            "duplicate_failure_records": self.duplicate_failed,
            "conflicting_request_ids": sorted(self.conflicts),
            "event_id_conflicts": [
                {"event_id": key, "request_ids": sorted(ids)}
                for key, ids in sorted(event_requests.items())
                if len(ids) > 1
            ],
            "invalid_metadata_records": self.invalid,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Create a new metadata-only JSON report; existing files are never overwritten.",
    )
    args = parser.parse_args(argv)
    log = AcceptanceLog()
    try:
        for path in args.logs:
            with path.open("rb") as stream:
                prefix = stream.read(4)
                stream.seek(0)
                encoding = (
                    "utf-16"
                    if prefix.startswith((b"\xff\xfe", b"\xfe\xff"))
                    else "utf-8-sig"
                )
                with io.TextIOWrapper(stream, encoding=encoding) as text:
                    for line in text:
                        log.feed(line)
        report = log.summary()
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
        else:
            sys.stdout.write(rendered)
    except (OSError, UnicodeError, ValueError):
        print(
            "Unable to read logs or create a new report; check encoding and choose an unused output path.",
            file=sys.stderr,
        )
        return 2
    return (
        2
        if not (report["completed_requests"] or report["failed_requests"])
        or report["invalid_metadata_records"]
        or report["invalid_usage_steps"]
        or report["uncorrelated_failure_lines"]
        or report["conflicting_request_ids"]
        or report["event_id_conflicts"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
