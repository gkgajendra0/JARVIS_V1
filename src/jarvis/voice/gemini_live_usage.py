"""Pure qualified metadata conversion; no missing-field or finality guesses."""

from collections.abc import Mapping

from jarvis.model_routing.live_policy import LiveUsageProfile, LiveUsageReport
from jarvis.model_routing.live_usage_evidence import (
    COUNTERS,
    DETAILS,
    MODALITIES,
    REASONS,
    numeric,
    validate_usage_diagnostics,
)


def _get(raw, name):
    return raw.get(name) if isinstance(raw, Mapping) else getattr(raw, name, None)


def _count(value):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("invalid_count")
    return value


def _details(raw):
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise TypeError("invalid_modalities")
    result = {}
    for item in raw:
        modality = _get(item, "modality")
        modality = getattr(modality, "value", modality)
        n = _count(_get(item, "token_count"))
        if modality not in {"TEXT", "AUDIO"} or modality in result or n is None:
            raise ValueError("unsupported_or_duplicate_modality")
        result[modality] = n
    return result


def usage_diagnostics(raw, report):
    """Retain numeric SDK evidence even when normalization rejects a report."""
    counts, missing, invalid, details, issues = {}, [], [], {}, []
    for name in COUNTERS:
        value = _get(raw, name)
        counts[name] = value if numeric(value) else None
        if value is None:
            missing.append(name)
        elif not numeric(value):
            invalid.append(name)
    for name in DETAILS:
        rows = _get(raw, name)
        if rows is None:
            details[name] = None
            continue
        if not isinstance(rows, (tuple, list)):
            details[name] = None
            issues.append("invalid_" + name)
            continue
        if len(rows) > 16:
            issues.append("truncated_" + name)
        safe = []
        for row in rows[:16]:
            modality = _get(row, "modality")
            modality = getattr(modality, "value", modality)
            value = _get(row, "token_count")
            safe.append(
                {
                    "modality": modality
                    if type(modality) is str and modality in MODALITIES
                    else "OTHER",
                    "token_count": value if numeric(value) else None,
                }
            )
        details[name] = safe
    return validate_usage_diagnostics(
        {
            "schema_version": 1,
            "counts": counts,
            "details": details,
            "missing_counts": missing,
            "invalid_counts": invalid,
            "missing_dimensions": [
                name
                for name in (
                    "input_tokens",
                    "input_audio_tokens",
                    "output_tokens",
                    "output_audio_tokens",
                )
                if name not in report.usage
            ],
            "normalization_reason": report.unknown_reason,
            "issues": issues,
        }
    )


def normalize_operational_usage(
    raw, *, profile, round_id, sequence, after_round_complete, last_output_sequence
):
    if not isinstance(profile, LiveUsageProfile):
        raise TypeError("Explicit usage profile required")
    usage, unknown = {}, None
    complete = False
    try:
        counts = {}
        for name in (
            "prompt_token_count",
            "response_token_count",
            "thoughts_token_count",
            "total_token_count",
            "cached_content_token_count",
            "tool_use_prompt_token_count",
        ):
            value = _get(raw, name)
            if value is None and name in profile.zero_rules:
                value = 0
            counts[name] = _count(value)
        ins = _details(_get(raw, "prompt_tokens_details"))
        outs = _details(_get(raw, "response_tokens_details"))
        for dimension, path in profile.field_map.items():
            bucket, modality = path.split(".")
            details = ins if bucket == "prompt_tokens_details" else outs
            if details is not None and modality in details:
                if dimension == "output_tokens":
                    # Known response TEXT is a lower bound even if thoughts are
                    # absent; completeness still requires every original field.
                    usage[dimension] = details[modality] + (
                        counts["thoughts_token_count"] or 0
                    )
                else:
                    usage[dimension] = details[modality]
        prompt, response, thoughts, total, cached, tools = counts.values()
        if tools is not None and tools != 0:
            raise ValueError("unsupported_tool_billing")
        if ins is not None and prompt is not None and sum(ins.values()) != prompt:
            raise ValueError("contradictory_prompt_total")
        if outs is not None and response is not None and sum(outs.values()) != response:
            raise ValueError("contradictory_response_total")
        if (
            None not in (prompt, response, thoughts, total)
            and prompt + response + thoughts != total
        ):
            raise ValueError("contradictory_total")
        if cached is not None and prompt is not None and cached > prompt:
            raise ValueError("contradictory_cache")
        complete = (
            all(v is not None for v in counts.values())
            and len(usage) == 4
            and after_round_complete
            and sequence >= last_output_sequence
        )
    except ValueError as exc:
        # Report only our own fixed reason codes, never raw provider strings.
        unknown = str(exc) if str(exc) in REASONS else "invalid_usage_metadata"
    except (TypeError, AttributeError) as exc:
        unknown = str(exc) if str(exc) in REASONS else "invalid_usage_shape"
    return LiveUsageReport(
        round_id,
        sequence,
        usage,
        bool(complete and unknown is None),
        profile.fingerprint,
        after_round_complete,
        last_output_sequence,
        unknown,
    )
