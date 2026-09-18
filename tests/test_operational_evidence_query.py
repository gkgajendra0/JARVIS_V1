from __future__ import annotations

import json

from jarvis.observability.evidence_query import LocalOperationalEvidenceQuery


def _write(path, rows) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_bounded_evidence_query_filters_rotated_logs_by_component_and_reason(
    tmp_path,
) -> None:
    path = tmp_path / "jarvis.jsonl"
    _write(
        tmp_path / "jarvis.jsonl.1",
        [
            {
                "timestamp": "2026-09-18T08:00:00Z",
                "level": "warning",
                "logger": "jarvis.vision.pocket3_recovery",
                "event": "Pocket transport stale",
                "reason_code": "stale_transport_rx",
            }
        ],
    )
    _write(
        path,
        [
            {
                "timestamp": "2026-09-18T08:05:00Z",
                "level": "info",
                "logger": "jarvis.voice.runtime",
                "event": "Voice healthy",
            },
            {
                "timestamp": "2026-09-18T08:06:00Z",
                "level": "warning",
                "logger": "jarvis.vision.native_owner_tracking",
                "event": "Recovery triggered",
                "component_id": "vision.pocket3",
                "reason_code": "stale_transport_rx",
                "session_id": "s1",
            },
        ],
    )

    query = LocalOperationalEvidenceQuery(path, max_scan_lines=100)
    result = query.query(
        component_id="vision.pocket3",
        logger_prefixes=("jarvis.vision",),
        reason_code="stale_transport_rx",
        max_results=10,
    )

    assert result.available is True
    assert result.truncated is False
    assert result.scanned_lines == 3
    assert len(result.events) == 2
    assert result.events[0]["event"] == "Recovery triggered"
    assert result.events[1]["event"] == "Pocket transport stale"
    assert result.events[0]["log_file"] == "jarvis.jsonl"


def test_evidence_query_is_bounded_and_skips_invalid_json(tmp_path) -> None:
    path = tmp_path / "jarvis.jsonl"
    path.write_text(
        "{not-json}\n"
        + "\n".join(
            json.dumps(
                {
                    "timestamp": f"2026-09-18T08:00:{index:02d}Z",
                    "level": "info",
                    "logger": "jarvis.voice.runtime",
                    "event": f"event-{index}",
                }
            )
            for index in range(10)
        )
        + "\n",
        encoding="utf-8",
    )

    query = LocalOperationalEvidenceQuery(path, max_scan_lines=5)
    result = query.query(
        logger_prefixes=("jarvis.voice",),
        max_results=3,
    )

    assert result.truncated is True
    assert result.scanned_lines == 5
    assert len(result.events) <= 3
