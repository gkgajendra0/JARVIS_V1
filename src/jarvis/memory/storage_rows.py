from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .assertions import SemanticAssertionRecord
from .types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)

SEMANTIC_ASSERTION_COLUMNS_SQL = """
    assertion_id,
    subject_scope,
    subject,
    predicate,
    value_type,
    value_json,
    normalized_text,
    source_id,
    valid_from,
    valid_to,
    system_from,
    system_to,
    last_verified_at,
    state,
    supersedes_id,
    verification_state,
    confidence,
    freshness_class,
    sensitivity,
    created_at,
    updated_at
"""


def _parse_time(value: Any, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise ValueError("required memory timestamp is null")
        return None
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def semantic_assertion_record_from_row(
    row: Sequence[Any],
) -> SemanticAssertionRecord:
    if len(row) != 21:
        raise ValueError(f"expected 21 semantic assertion columns, got {len(row)}")

    system_from = _parse_time(row[10], required=True)
    created_at = _parse_time(row[19], required=True)
    updated_at = _parse_time(row[20], required=True)
    assert system_from is not None
    assert created_at is not None
    assert updated_at is not None

    return SemanticAssertionRecord(
        assertion_id=str(row[0]),
        subject_scope=str(row[1]),
        subject=str(row[2]),
        predicate=str(row[3]),
        value_type=ValueType(str(row[4])),
        value=json.loads(str(row[5])),
        normalized_text=str(row[6]),
        source_id=str(row[7]),
        valid_from=_parse_time(row[8]),
        valid_to=_parse_time(row[9]),
        system_from=system_from,
        system_to=_parse_time(row[11]),
        last_verified_at=_parse_time(row[12]),
        state=AssertionState(str(row[13])),
        supersedes_id=None if row[14] is None else str(row[14]),
        verification_state=VerificationState(str(row[15])),
        confidence=None if row[16] is None else float(row[16]),
        freshness_class=FreshnessClass(str(row[17])),
        sensitivity=Sensitivity(str(row[18])),
        created_at=created_at,
        updated_at=updated_at,
    )
