"""Bounded read-only querying over the local structured operational log spool."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.observability.logging import default_jsonl_log_path
from jarvis.observability.redaction import redact_data

_MAX_RESULTS = 100
_MAX_SCAN_LINES = 20_000
_MAX_TEXT = 2_000


@dataclass(frozen=True, slots=True)
class EvidenceQueryResult:
    available: bool
    events: tuple[dict[str, Any], ...]
    scanned_lines: int
    truncated: bool
    log_files: tuple[str, ...]


def _timestamp_epoch(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _reverse_lines(path: Path, *, chunk_size: int = 64 * 1024) -> Iterator[str]:
    """Yield UTF-8 lines newest-first without loading a rotated log into memory."""

    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        remainder = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size) + remainder
            parts = chunk.split(b"\n")
            remainder = parts[0]
            for raw in reversed(parts[1:]):
                if raw:
                    yield raw.decode("utf-8", errors="replace")
        if remainder:
            yield remainder.decode("utf-8", errors="replace")


def _bounded_value(value: object) -> object:
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, (int, float, bool, type(None))):
        return value
    return str(value)[:_MAX_TEXT]


def _project_event(row: dict[str, Any], *, file_name: str) -> dict[str, Any]:
    keys = (
        "timestamp",
        "level",
        "logger",
        "event",
        "component_id",
        "reason_code",
        "result_state",
        "elapsed_ms",
        "status",
        "state",
        "operation",
        "reason",
        "session_id",
        "turn_id",
        "goal_id",
        "capability_id",
        "proposal_id",
        "incident_id",
        "exception",
    )
    projected = {
        key: _bounded_value(row[key])
        for key in keys
        if key in row and row[key] not in {None, ""}
    }
    projected["log_file"] = file_name
    return dict(redact_data(projected))


class LocalOperationalEvidenceQuery:
    """Query current + rotated JSONL logs with strict scan/result bounds."""

    def __init__(
        self,
        log_path: str | Path | None = None,
        *,
        backup_count: int = 4,
        max_scan_lines: int = _MAX_SCAN_LINES,
    ) -> None:
        if backup_count < 0:
            raise ValueError("backup_count must not be negative")
        if max_scan_lines < 1 or max_scan_lines > _MAX_SCAN_LINES:
            raise ValueError(f"max_scan_lines must be between 1 and {_MAX_SCAN_LINES}")
        self.path = (
            Path(log_path).expanduser()
            if log_path is not None
            else default_jsonl_log_path()
        )
        self.backup_count = backup_count
        self.max_scan_lines = max_scan_lines

    def _paths(self) -> tuple[Path, ...]:
        return (
            self.path,
            *(
                Path(f"{self.path}.{index}")
                for index in range(1, self.backup_count + 1)
            ),
        )

    def query(
        self,
        *,
        component_id: str = "",
        logger_prefixes: tuple[str, ...] = (),
        since_epoch: float | None = None,
        until_epoch: float | None = None,
        severity: str = "",
        reason_code: str = "",
        session_id: str = "",
        turn_id: str = "",
        incident_id: str = "",
        query: str = "",
        max_results: int = 30,
    ) -> EvidenceQueryResult:
        if max_results < 1 or max_results > _MAX_RESULTS:
            raise ValueError(f"max_results must be between 1 and {_MAX_RESULTS}")
        if (
            since_epoch is not None
            and until_epoch is not None
            and since_epoch > until_epoch
        ):
            raise ValueError("since_epoch must not be after until_epoch")

        normalized_component = str(component_id).strip().lower()
        normalized_prefixes = tuple(
            str(item).strip().lower() for item in logger_prefixes if str(item).strip()
        )
        normalized_severity = str(severity).strip().lower()
        normalized_reason = str(reason_code).strip().lower()
        normalized_session = str(session_id).strip()
        normalized_turn = str(turn_id).strip()
        normalized_incident = str(incident_id).strip()
        normalized_query = str(query).strip().casefold()

        existing = tuple(path for path in self._paths() if path.is_file())
        if not existing:
            return EvidenceQueryResult(False, (), 0, False, ())

        matches: list[tuple[float, dict[str, Any]]] = []
        scanned = 0
        scan_limit_hit = False

        for path in existing:
            for line in _reverse_lines(path):
                if scanned >= self.max_scan_lines:
                    scan_limit_hit = True
                    break
                scanned += 1
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    continue
                if not isinstance(row, dict):
                    continue

                timestamp = _timestamp_epoch(row.get("timestamp"))
                if since_epoch is not None and (
                    timestamp is None or timestamp < since_epoch
                ):
                    continue
                if until_epoch is not None and (
                    timestamp is None or timestamp > until_epoch
                ):
                    continue

                logger_name = str(row.get("logger") or "").strip().lower()
                row_component = str(row.get("component_id") or "").strip().lower()
                component_match = not normalized_component or (
                    row_component == normalized_component
                    or (
                        not row_component
                        and normalized_prefixes
                        and any(
                            logger_name.startswith(prefix)
                            for prefix in normalized_prefixes
                        )
                    )
                )
                if not component_match:
                    continue
                if normalized_severity and (
                    str(row.get("level") or "").strip().lower() != normalized_severity
                ):
                    continue
                if normalized_reason and (
                    str(row.get("reason_code") or "").strip().lower()
                    != normalized_reason
                ):
                    continue
                if (
                    normalized_session
                    and str(row.get("session_id") or "") != normalized_session
                ):
                    continue
                if normalized_turn and str(row.get("turn_id") or "") != normalized_turn:
                    continue
                if normalized_incident and (
                    str(row.get("incident_id") or "") != normalized_incident
                ):
                    continue
                if normalized_query:
                    haystack = " ".join(
                        str(row.get(key) or "")
                        for key in ("event", "reason", "reason_code", "exception")
                    ).casefold()
                    if normalized_query not in haystack:
                        continue

                matches.append(
                    (
                        timestamp if timestamp is not None else 0.0,
                        _project_event(row, file_name=path.name),
                    )
                )
            if scan_limit_hit:
                break

        matches.sort(key=lambda item: item[0], reverse=True)
        result_limit_hit = len(matches) > max_results
        events = tuple(item for _, item in matches[:max_results])
        return EvidenceQueryResult(
            available=True,
            events=events,
            scanned_lines=scanned,
            truncated=scan_limit_hit or result_limit_hit,
            log_files=tuple(path.name for path in existing),
        )


def recent_since_epoch(seconds: float, *, now_epoch: float | None = None) -> float:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    return (time.time() if now_epoch is None else now_epoch) - seconds
