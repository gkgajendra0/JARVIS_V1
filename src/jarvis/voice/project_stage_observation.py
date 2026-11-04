"""Nested wall-clock spans in the explicitly invoked sequential text lab only."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from functools import wraps

STATUSES = frozenset(
    {
        "complete",
        "partial",
        "selected",
        "denied",
        "no_match",
        "unavailable",
        "invalid_selection",
        "not_requested",
        "clarification_required",
    }
)
_ACTIVE_OBSERVATION = ContextVar("project_lab_stage_observation", default=None)


def tool_outcomes(context):
    if context is None:
        return {"personal_status": "unobserved", "tools": []}
    body = json.loads(context)

    def status(value):
        return value if isinstance(value, str) and value in STATUSES else "unobserved"

    return {
        "personal_status": status(body.get("personal", {}).get("status")),
        "tools": [
            {
                "tool": r["tool"]
                if r.get("tool") in {"personal", "search", "read"}
                else "unobserved",
                "status": status(r.get("status")),
                "source_count": len(r.get("source_ids", [])),
            }
            for r in body.get("retrieval", [])
        ],
    }


@contextmanager
def observe_stages(targets, *, clock=time.perf_counter):
    """Wrap fixed internal methods; preserve their results/exceptions and restore all."""
    rows, installed = [], []
    lock = threading.Lock()
    origin = clock()
    identity = object()
    token = _ACTIVE_OBSERVATION.set(identity)

    def wrap(original, stage, asynchronous):
        def begin(start):
            row = {
                "stage": stage,
                "start_ms": (start - origin) * 1000,
                "duration_ms": None,
                "outcome": "running",
            }
            with lock:
                rows.append(row)
            return row

        def record(pending, start, outcome, result=None, error=None):
            with suppress(Exception):
                end = clock()
                row = {
                    "stage": stage,
                    "start_ms": (start - origin) * 1000,
                    "duration_ms": (end - start) * 1000,
                    "outcome": outcome,
                }
                if stage == "hello_verification" and outcome == "returned":
                    value = getattr(getattr(result, "status", None), "value", None)
                    if value in {
                        "verified",
                        "canceled",
                        "failed",
                        "retries_exhausted",
                        "not_configured",
                        "unavailable",
                        "error",
                    }:
                        row["verification_status"] = value
                if stage == "fresh_owner_authorization" and error is not None:
                    known = {
                        "user_canceled",
                        "helper_timeout",
                        "helper_launch_failed",
                        "helper_invalid_output",
                        "helper_not_configured",
                        "helper_not_found",
                        "verifier_error",
                        "insufficient_trust",
                        "approval_invalid",
                        "approval_required",
                        "owner_attention_required",
                        "actor_ambiguous",
                        "policy_engine_exception",
                    }
                    reason = str(error).rsplit(": ", 1)[-1]
                    row["authorization_reason"] = (
                        reason if reason in known else "unclassified"
                    )
                with lock:
                    pending.update(row)

        @wraps(original)
        async def async_call(*args, **kwargs):
            if _ACTIVE_OBSERVATION.get() is not identity:
                return await original(*args, **kwargs)
            start, outcome = clock(), "raised"
            pending = begin(start)
            try:
                result = await original(*args, **kwargs)
                outcome = "returned"
                return result
            finally:
                record(pending, start, outcome)

        @wraps(original)
        def sync_call(*args, **kwargs):
            if _ACTIVE_OBSERVATION.get() is not identity:
                return original(*args, **kwargs)
            start, outcome = clock(), "raised"
            pending = begin(start)
            result = error = None
            try:
                result = original(*args, **kwargs)
                outcome = "returned"
                return result
            except BaseException as exc:
                error = exc
                raise
            finally:
                record(pending, start, outcome, result, error)

        return async_call if asynchronous else sync_call

    try:
        for owner, name, stage, asynchronous in targets:
            original = getattr(owner, name)
            own = name in vars(owner)
            installed.append((owner, name, original, own))
            setattr(owner, name, wrap(original, stage, asynchronous))
        yield rows
    finally:
        _ACTIVE_OBSERVATION.reset(token)
        for owner, name, original, own in reversed(installed):
            if own:
                setattr(owner, name, original)
            else:
                delattr(owner, name)


def lab_stage_targets(coordinator, provider):
    from jarvis.authority.verifier import WindowsHelloVerifier
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.voice.personal_context import PersonalContextSession
    from jarvis.voice.project_memory_tools import ProjectMemoryTools

    return [
        (coordinator, "prepare_reply", "prepare", True),
        (coordinator, "_build_packet", "context_build", True),
        (coordinator, "_capture_tool", "tool_journal", True),
        (coordinator, "validate_for_release", "release_validation", True),
        (coordinator, "record_assistant", "assistant_commit", True),
        (provider, "step", "provider_step", True),
        (PersonalContextSession, "query_for_question", "personal_tool", True),
        (PersonalContextSession, "_authorize", "personal_authorization", True),
        (
            CapabilityRuntime,
            "authorize_personal_context",
            "fresh_owner_authorization",
            False,
        ),
        (WindowsHelloVerifier, "verify", "hello_verification", False),
        (ProjectMemoryTools, "search_conversation_memory", "archive_search", True),
        (ProjectMemoryTools, "read_conversation_sources", "archive_read", True),
    ]
