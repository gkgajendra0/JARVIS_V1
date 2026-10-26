"""Bounded numeric-only provider usage evidence; never financial authority."""

import json

from jarvis.model_routing.live_policy import DIMENSIONS

COUNTERS = (
    "prompt_token_count",
    "response_token_count",
    "thoughts_token_count",
    "total_token_count",
    "cached_content_token_count",
    "tool_use_prompt_token_count",
)
DETAILS = ("prompt_tokens_details", "response_tokens_details")
MODALITIES = {
    "TEXT",
    "AUDIO",
    "IMAGE",
    "VIDEO",
    "DOCUMENT",
    "MODALITY_UNSPECIFIED",
    "OTHER",
}
REASONS = {
    "invalid_count",
    "invalid_modalities",
    "unsupported_or_duplicate_modality",
    "unsupported_tool_billing",
    "contradictory_prompt_total",
    "contradictory_response_total",
    "contradictory_total",
    "contradictory_cache",
    "invalid_usage_shape",
    "invalid_usage_metadata",
}
ISSUES = {"invalid_" + name for name in DETAILS} | {
    "truncated_" + name for name in DETAILS
}


def numeric(value):
    return type(value) is int and -(2**63) <= value < 2**63


def validate_usage_diagnostics(value):
    """Reject arbitrary fields before evidence enters the encrypted journal."""
    keys = {
        "schema_version",
        "counts",
        "details",
        "missing_counts",
        "invalid_counts",
        "missing_dimensions",
        "normalization_reason",
        "issues",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("Invalid numeric usage diagnostics schema")
    counts = value["counts"]
    if (
        not isinstance(counts, dict)
        or set(counts) != set(COUNTERS)
        or any(v is not None and not numeric(v) for v in counts.values())
    ):
        raise ValueError("Invalid diagnostic counters")
    details = value["details"]
    if not isinstance(details, dict) or set(details) != set(DETAILS):
        raise ValueError("Invalid diagnostic detail fields")
    for rows in details.values():
        if rows is None:
            continue
        if not isinstance(rows, list) or len(rows) > 16:
            raise ValueError("Unbounded diagnostic modality rows")
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != {"modality", "token_count"}
                or row["modality"] not in MODALITIES
                or (row["token_count"] is not None and not numeric(row["token_count"]))
            ):
                raise ValueError("Invalid diagnostic modality row")
    for name, allowed in (
        ("missing_counts", set(COUNTERS)),
        ("invalid_counts", set(COUNTERS)),
        ("missing_dimensions", set(DIMENSIONS)),
        ("issues", ISSUES),
    ):
        entries = value[name]
        if (
            not isinstance(entries, list)
            or len(entries) > len(allowed)
            or any(type(v) is not str or v not in allowed for v in entries)
            or len(set(entries)) != len(entries)
        ):
            raise ValueError("Invalid diagnostic field list")
    if (
        value["normalization_reason"] is not None
        and value["normalization_reason"] not in REASONS
    ):
        raise ValueError("Invalid diagnostic normalization reason")
    encoded = json.dumps(value, allow_nan=False)
    if len(encoded) > 8192:
        raise ValueError("Unbounded usage diagnostics")
    return json.loads(encoded)
