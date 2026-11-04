"""Content-free observation inside an explicitly invoked isolated text lab."""

from __future__ import annotations

import json
import re
from collections import Counter
from contextlib import contextmanager, suppress
from functools import wraps

from pydantic import ValidationError

from jarvis.hands.provider_adapters import (
    GeminiStructuredOutputClient,
    StructuredOutputError,
)
from jarvis.model_routing.invoker import RoutedInferenceFailure
from jarvis.personal_learning_scope import SUPPRESSION_KEYS
from jarvis.provider_resilience import ProviderFailureKind

ERROR_TYPES = frozenset(
    {
        "json_invalid",
        "missing",
        "extra_forbidden",
        "string_type",
        "string_too_short",
        "string_too_long",
        "list_type",
        "literal_error",
        "value_error",
        "too_short",
        "too_long",
        "model_type",
    }
)


def _diagnostic(exc):
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return {
            "reason": "missing_output"
            if str(exc) == "Gemini returned no structured Hands planner output"
            else "contract_failure"
        }
    # Inspect inputs only in memory; emit no values, messages, paths or arbitrary keys.
    errors = cause.errors(include_context=False, include_url=False)
    types = Counter(e["type"] if e["type"] in ERROR_TYPES else "other" for e in errors)
    target_types, scopes = set(), set()
    for error in errors[:32]:
        value = error.get("input")
        if not isinstance(value, dict) or "scope_key" not in value:
            continue
        scope = value["scope_key"]
        scopes.add(
            scope
            if isinstance(scope, str) and scope in SUPPRESSION_KEYS
            else "unregistered"
        )
        if "target_quote" in value:
            target = value["target_quote"]
            target_types.add(
                "null"
                if target is None
                else "string"
                if type(target) is str
                else "other"
            )
    return {
        "reason": "validation_failed",
        "validation_error_count": len(errors),
        "validation_error_types": dict(sorted(types.items())),
        "personal_scope_keys": sorted(scopes),
        "personal_target_types": sorted(target_types),
    }


@contextmanager
def observe_contract_failures(*, adapter_type=GeminiStructuredOutputClient, emit=print):
    """Observe before routing discards the cause; preserve normal calls and errors."""
    original = adapter_type.parse_with_telemetry
    observations = []

    @wraps(original)
    async def parse(self, **kwargs):
        try:
            return await original(self, **kwargs)
        except StructuredOutputError as exc:
            with suppress(Exception):
                diagnostic = _diagnostic(exc)
                observations.append(diagnostic)
                emit("DEVELOPMENT_CONTRACT " + json.dumps(diagnostic))
            raise

    adapter_type.parse_with_telemetry = parse
    try:
        yield observations
    finally:
        adapter_type.parse_with_telemetry = original


class DevelopmentCaseFailure(RuntimeError):
    def __init__(self, error, coordinator, observations):
        name = type(error).__name__
        stage = "setup_or_turn"
        with suppress(Exception):
            value = coordinator.diagnostics()["stage"]
            if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,48}", value):
                stage = value
        self.report = {
            "status": "failed",
            "error": name
            if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,127}", name)
            else "redacted",
            "stage": stage,
            "answer_quality": "not_evaluated",
            "usage": None,
            "contract_observations": list(observations),
        }
        spans = getattr(coordinator, "_lab_stage_spans", None)
        if isinstance(spans, list):
            self.report["stage_spans"] = [dict(row) for row in list(spans)]
            self.report["stage_spans_incomplete"] = any(
                row.get("outcome") == "running" for row in self.report["stage_spans"]
            )
            self.report["stage_span_semantics"] = (
                "Nested spans overlap; do not sum. Failed/canceled spans are not successful latency samples."
            )
        if isinstance(error, RoutedInferenceFailure) and isinstance(
            error.failure.kind, ProviderFailureKind
        ):
            self.report["routing_failure_kind"] = error.failure.kind.value
        super().__init__("development case failed")
