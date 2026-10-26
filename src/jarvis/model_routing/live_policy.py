"""Immutable operational allowance/reporting bindings, never financial authority."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType

DIMENSIONS = (
    "input_tokens",
    "input_audio_tokens",
    "output_tokens",
    "output_audio_tokens",
)
FIELD_MAP = dict(
    zip(
        DIMENSIONS,
        (
            "prompt_tokens_details.TEXT",
            "prompt_tokens_details.AUDIO",
            "response_tokens_details.TEXT",
            "response_tokens_details.AUDIO",
        ),
        strict=True,
    )
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError("Bounded nonempty identity required")
    return value


def hash_ref(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("SHA256 reference required")
    return value


def count(value, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("Nonnegative integer required")
    return value


def seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("Finite positive duration required")
    return value


class Payload:
    def to_payload(self):
        result = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Mapping):
                value = dict(value)
            elif isinstance(value, tuple):
                value = [v.to_payload() if isinstance(v, Payload) else v for v in value]
            result[f.name] = value
        return result

    @property
    def fingerprint(self):
        return digest(self.to_payload())


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalLivePolicy(Payload):
    provenance: str
    version: int = 1
    model_id: str = "gemini-3.8-live"
    allowance_minor: int = 1000
    soft_stop_minor: int = 800
    max_physical_seconds: float = 45
    setup_timeout_seconds: float = 5
    max_activity_seconds: float = 20
    output_token_limit: int = 1024
    max_tool_continuations: int = 2
    fast_tool_wait_seconds: float = 5
    final_usage_wait_seconds: float = 2

    def __post_init__(self):
        identity(self.provenance)
        count(self.version, positive=True)
        for name in ("allowance_minor", "soft_stop_minor", "output_token_limit"):
            count(getattr(self, name), positive=True)
        count(self.max_tool_continuations)
        for name in (
            "max_physical_seconds",
            "setup_timeout_seconds",
            "max_activity_seconds",
            "fast_tool_wait_seconds",
            "final_usage_wait_seconds",
        ):
            seconds(getattr(self, name))
        if (
            self.model_id != "gemini-3.8-live"
            or not 0 < self.soft_stop_minor < self.allowance_minor <= 35000
        ):
            raise ValueError("Unsupported operational model/allowance")
        if self.max_physical_seconds <= 3 or any(
            v >= self.max_physical_seconds - 3
            for v in (
                self.max_activity_seconds,
                self.setup_timeout_seconds,
                self.fast_tool_wait_seconds,
                self.final_usage_wait_seconds,
            )
        ):
            raise ValueError("Controls must fit original dispatch lifetime")
        if self.version == 1 and (
            self.allowance_minor,
            self.soft_stop_minor,
            self.max_physical_seconds,
            self.setup_timeout_seconds,
            self.max_activity_seconds,
            self.output_token_limit,
            self.max_tool_continuations,
            self.fast_tool_wait_seconds,
            self.final_usage_wait_seconds,
        ) != (1000, 800, 45, 5, 20, 1024, 2, 5, 2):
            raise ValueError("Changed operational controls require a new version")


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveUsageProfile(Payload):
    profile_id: str
    version: int
    model_id: str
    sdk_versions: Mapping[str, str]
    config_ref: str
    counter_scope: str
    field_map: Mapping[str, str]
    zero_rules: Mapping[str, str]
    transcription_mode: str
    terminal_mode: str
    source_refs: tuple[str, ...]
    evidence_digest: str

    def __post_init__(self):
        identity(self.profile_id)
        count(self.version, positive=True)
        hash_ref(self.config_ref)
        hash_ref(self.evidence_digest)
        if self.model_id != "gemini-3.8-live" or self.counter_scope not in {
            "generation",
            "connection",
        }:
            raise ValueError("Unsupported reporting model/counter scope")
        if self.transcription_mode != "response_text" or self.terminal_mode not in {
            "same_event",
            "post_turn_complete",
        }:
            raise ValueError("Unqualified transcription/finality interpretation")
        if (
            not self.sdk_versions
            or not self.source_refs
            or dict(self.field_map) != FIELD_MAP
        ):
            raise ValueError("Complete versioned modality reporting sources required")
        for k, v in self.sdk_versions.items():
            identity(k)
            identity(v)
        for ref in self.source_refs:
            identity(ref)
        for k, v in self.zero_rules.items():
            if (
                k
                not in {
                    "thoughts_token_count",
                    "cached_content_token_count",
                    "tool_use_prompt_token_count",
                }
                or v != "documented_omitted_zero"
            ):
                raise ValueError("Unsupported omitted-zero interpretation")
        for name in ("sdk_versions", "field_map", "zero_rules"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        object.__setattr__(self, "source_refs", tuple(self.source_refs))

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict) or set(payload) != {
            f.name for f in fields(cls)
        }:
            raise ValueError("Exact reporting profile schema required")
        try:
            return cls(**payload)
        except (TypeError, AttributeError) as exc:
            raise ValueError("Invalid reporting profile") from exc


@dataclass(frozen=True, slots=True)
class LiveUsageReport(Payload):
    round_id: str
    sequence: int
    usage: Mapping[str, int]
    complete: bool
    profile_ref: str
    after_round_complete: bool
    last_output_sequence: int
    unknown_reason: str | None = None

    def __post_init__(self):
        identity(self.round_id)
        hash_ref(self.profile_ref)
        count(self.sequence)
        count(self.last_output_sequence)
        if (
            type(self.complete) is not bool
            or type(self.after_round_complete) is not bool
        ):
            raise ValueError("Explicit usage finality required")
        if set(self.usage) - set(DIMENSIONS):
            raise ValueError("Unsupported billed dimension")
        for value in self.usage.values():
            count(value)
        if self.complete and (
            set(self.usage) != set(DIMENSIONS)
            or not self.after_round_complete
            or self.sequence < self.last_output_sequence
            or self.unknown_reason
        ):
            raise ValueError("Incomplete usage cannot be terminal")
        if self.unknown_reason is not None:
            identity(self.unknown_reason)
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))


@dataclass(frozen=True, slots=True)
class LiveTriggerPermit(Payload):
    reservation_id: str
    trigger_id: str
    kind: str
    round_id: str
    policy_ref: str
    profile_ref: str | None


@dataclass(frozen=True, slots=True)
class OperationalBudgetObservation(Payload):
    known_minor: int
    held_minor: int
    stop_required: bool
    unknown_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LiveReconciliationEvidence(Payload):
    reservation_id: str
    target_id: str
    policy_ref: str
    profile_ref: str
    price_ref: str
    reports: tuple[LiveUsageReport, ...]
    source_digest: str

    def __post_init__(self):
        identity(self.reservation_id)
        identity(self.target_id)
        for ref in (
            self.policy_ref,
            self.profile_ref,
            self.price_ref,
            self.source_digest,
        ):
            hash_ref(ref)
        if not self.reports or any(
            not isinstance(r, LiveUsageReport) for r in self.reports
        ):
            raise ValueError("Attributable usage reports required")
        object.__setattr__(self, "reports", tuple(self.reports))


@dataclass(frozen=True, slots=True)
class LiveExperimentAuthorization(Payload):
    authorization_id: str
    plan_ref: str
    session_id: str
    expires_at_epoch: float
    max_connections: int
    max_generations: int
    max_seconds: float
    price_ref: str
    policy_ref: str
    profile_ref: str | None
    fixture_ref: str
    scope: str
    nonce: str

    def __post_init__(self):
        for name in ("authorization_id", "session_id", "scope", "nonce"):
            identity(getattr(self, name))
        for name in ("plan_ref", "price_ref", "policy_ref", "fixture_ref"):
            hash_ref(getattr(self, name))
        if self.profile_ref is not None:
            hash_ref(self.profile_ref)
        seconds(self.expires_at_epoch)
        seconds(self.max_seconds)
        count(self.max_connections, positive=True)
        count(self.max_generations, positive=True)
