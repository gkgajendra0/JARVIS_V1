"""Bounded source material; originals remain evidence, never executable policy."""

from __future__ import annotations

import json
from datetime import UTC


def conservative_token_bound(text: str) -> int:
    """UTF-8 wire-byte upper estimate, matching the existing paid routing bound.

    Deliberately overestimates ordinary text; this is not a calibrated tokenizer
    or a report of provider usage. Actual provider usage is retained separately.
    """
    return len(text.encode("utf-8")) + 32


def build_project_context(snapshot, *, extra_sources=(), personal=None, retrieval=()):
    personal = personal or {"status": "not_requested", "facts": []}
    base = {
        "project_id": snapshot.selection.project_id,
        "thread_id": snapshot.selection.thread_id,
        "project_title": snapshot.title,
        "archive_revision": snapshot.archive_revision,
        "last_committed_sequence": snapshot.last_sequence,
        "coverage": snapshot.status,
        "omitted_source_count": snapshot.omissions,
        "personal": personal,
        "retrieval": list(retrieval),
        "sources": [],
        "omitted_source_ids": [],
    }
    # Recent uncovered discussion is independent of model-selected state patches.
    candidates = {s.event.event_id: s for s in (*snapshot.sources, *extra_sources)}
    selected = []
    # Search-selected originals are useful even when beyond the recent window.
    preferred = [*reversed(extra_sources), *reversed(snapshot.sources)]
    seen = set()
    for source in preferred:
        event = source.event
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        row = {
            "source_id": event.event_id,
            "thread_id": source.thread_id or snapshot.selection.thread_id,
            "sequence": source.sequence,
            "role": event.role,
            "accepted_at": event.accepted_at.astimezone(UTC).isoformat(),
            "delivery": event.delivery,
            "text": event.text,
        }
        trial = {**base, "sources": [*selected, row]}
        if conservative_token_bound(json.dumps(trial, ensure_ascii=False)) <= 5600:
            selected.append(row)
        else:
            base["omitted_source_ids"].append(event.event_id)
    selected.sort(key=lambda s: (s["accepted_at"], s["thread_id"], s["sequence"]))
    base["sources"] = selected
    if len(selected) < len(candidates):
        base["coverage"] = "partial"
    text = json.dumps(base, ensure_ascii=False, sort_keys=True)
    if conservative_token_bound(text) > 6000:
        # Never truncate personal values or source text invisibly.
        raise ValueError("personal/context metadata exceeds external budget")
    return (
        text,
        tuple(row["source_id"] for row in selected),
        conservative_token_bound(text),
    )
