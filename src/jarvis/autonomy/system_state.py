"""Normalized read-only whole-JARVIS SystemState contracts and aggregation."""

from __future__ import annotations

import math
import time
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, Self

from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest

SYSTEM_STATE_SCHEMA_VERSION = "1"
SYSTEM_STATE_PRODUCER_VERSION = "phase10a.2.v1"


def _text(value: object, field: str, *, max_length: int = 1000) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _token(value: object, field: str, *, max_length: int = 200) -> str:
    return _text(value, field, max_length=max_length).casefold()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _epoch(
    value: object | None,
    field: str,
    *,
    optional: bool = False,
) -> float | None:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} must not be None")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _json_object(value: object, field: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a JSON object")
    canonical_digest(value)
    return deepcopy(value)


def _unique_tokens(
    values: tuple[str, ...] | list[str],
    field: str,
    *,
    allow_empty: bool = False,
    max_items: int = 128,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _token(value, f"{field}[{index}]", max_length=240)
        for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _unique_texts(
    values: tuple[str, ...] | list[str],
    field: str,
    *,
    allow_empty: bool = False,
    max_items: int = 256,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _text(value, f"{field}[{index}]", max_length=1000)
        for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _sha256(value: object, field: str) -> str:
    normalized = _text(value, field, max_length=64).casefold()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


class SystemStateSourceStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SystemStateTargetV1:
    target_namespace: str
    target_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _text(self.target_identity, "target_identity", max_length=500),
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "target_namespace": self.target_namespace,
            "target_identity": self.target_identity,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class SystemStateReadRequestV1:
    requested_namespaces: tuple[str, ...]
    targets: tuple[SystemStateTargetV1, ...]
    now_epoch: float
    max_facts: int = 500
    schema_version: str = SYSTEM_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_namespaces",
            _unique_tokens(
                self.requested_namespaces,
                "requested_namespaces",
            ),
        )
        if any(not isinstance(item, SystemStateTargetV1) for item in self.targets):
            raise TypeError("targets must contain SystemStateTargetV1 values")
        target_keys = tuple(
            (item.target_namespace, item.target_identity) for item in self.targets
        )
        if len(set(target_keys)) != len(target_keys):
            raise ValueError("targets must not contain duplicates")
        object.__setattr__(
            self,
            "now_epoch",
            _epoch(self.now_epoch, "now_epoch"),
        )
        object.__setattr__(self, "max_facts", _positive_int(self.max_facts, "max_facts"))
        if self.max_facts > 5000:
            raise ValueError("max_facts exceeds bounded SystemState limit")
        if self.schema_version != SYSTEM_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported SystemState request schema_version")

    def for_namespaces(
        self,
        namespaces: tuple[str, ...],
    ) -> SystemStateReadRequestV1:
        return SystemStateReadRequestV1(
            requested_namespaces=namespaces,
            targets=self.targets,
            now_epoch=self.now_epoch,
            max_facts=self.max_facts,
        )


@dataclass(frozen=True, slots=True)
class SystemStateSourceErrorV1:
    source_namespace: str
    source_adapter_key: str
    source_adapter_version: int
    reason_code: str
    summary: str
    schema_version: str = SYSTEM_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_namespace",
            _token(self.source_namespace, "source_namespace"),
        )
        object.__setattr__(
            self,
            "source_adapter_key",
            _token(self.source_adapter_key, "source_adapter_key"),
        )
        object.__setattr__(
            self,
            "source_adapter_version",
            _positive_int(self.source_adapter_version, "source_adapter_version"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _token(self.reason_code, "reason_code"),
        )
        object.__setattr__(
            self,
            "summary",
            _text(self.summary, "summary", max_length=500),
        )
        if self.schema_version != SYSTEM_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported SystemState source-error schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "source_namespace": self.source_namespace,
            "source_adapter_key": self.source_adapter_key,
            "source_adapter_version": self.source_adapter_version,
            "reason_code": self.reason_code,
            "summary": self.summary,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class SystemStateFactV1:
    fact_namespace: str
    source_identity: str
    source_version_or_digest: str
    target_namespace: str
    target_identity: str
    value_json: dict[str, JSONValue]
    observed_at_epoch: float
    evidence_references: tuple[str, ...]
    source_adapter_key: str
    source_adapter_version: int
    fresh_until_epoch: float | None = None
    schema_version: str = SYSTEM_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fact_namespace",
            _token(self.fact_namespace, "fact_namespace"),
        )
        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity", max_length=500),
        )
        object.__setattr__(
            self,
            "source_version_or_digest",
            _text(
                self.source_version_or_digest,
                "source_version_or_digest",
                max_length=500,
            ),
        )
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _text(self.target_identity, "target_identity", max_length=500),
        )
        object.__setattr__(
            self,
            "value_json",
            _json_object(self.value_json, "value_json"),
        )
        observed = _epoch(self.observed_at_epoch, "observed_at_epoch")
        fresh_until = _epoch(
            self.fresh_until_epoch,
            "fresh_until_epoch",
            optional=True,
        )
        if fresh_until is not None and fresh_until < observed:
            raise ValueError("fresh_until_epoch cannot precede observed_at_epoch")
        object.__setattr__(self, "observed_at_epoch", observed)
        object.__setattr__(self, "fresh_until_epoch", fresh_until)
        object.__setattr__(
            self,
            "evidence_references",
            _unique_texts(
                self.evidence_references,
                "evidence_references",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "source_adapter_key",
            _token(self.source_adapter_key, "source_adapter_key"),
        )
        object.__setattr__(
            self,
            "source_adapter_version",
            _positive_int(self.source_adapter_version, "source_adapter_version"),
        )
        if self.schema_version != SYSTEM_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported SystemState fact schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "fact_namespace": self.fact_namespace,
            "source_identity": self.source_identity,
            "source_version_or_digest": self.source_version_or_digest,
            "target_namespace": self.target_namespace,
            "target_identity": self.target_identity,
            "value_json": deepcopy(self.value_json),
            "observed_at_epoch": self.observed_at_epoch,
            "evidence_references": list(self.evidence_references),
            "source_adapter_key": self.source_adapter_key,
            "source_adapter_version": self.source_adapter_version,
            "fresh_until_epoch": self.fresh_until_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["evidence_references"] = tuple(data["evidence_references"])
        return cls(**data)

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_payload())

    def is_fresh(self, *, now_epoch: float) -> bool:
        now = _epoch(now_epoch, "now_epoch")
        return self.fresh_until_epoch is None or now <= self.fresh_until_epoch


@dataclass(frozen=True, slots=True)
class SystemStateSourceResultV1:
    source_adapter_key: str
    source_adapter_version: int
    status: SystemStateSourceStatus
    facts: tuple[SystemStateFactV1, ...]
    incomplete_namespaces: tuple[str, ...] = ()
    errors: tuple[SystemStateSourceErrorV1, ...] = ()
    schema_version: str = SYSTEM_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_adapter_key",
            _token(self.source_adapter_key, "source_adapter_key"),
        )
        object.__setattr__(
            self,
            "source_adapter_version",
            _positive_int(self.source_adapter_version, "source_adapter_version"),
        )
        if not isinstance(self.status, SystemStateSourceStatus):
            raise TypeError("status must be a SystemStateSourceStatus")
        if any(not isinstance(item, SystemStateFactV1) for item in self.facts):
            raise TypeError("facts must contain SystemStateFactV1 values")
        if len({item.digest for item in self.facts}) != len(self.facts):
            raise ValueError("source result facts must be unique")
        for fact in self.facts:
            if (
                fact.source_adapter_key != self.source_adapter_key
                or fact.source_adapter_version != self.source_adapter_version
            ):
                raise ValueError("fact adapter identity does not match source result")
        object.__setattr__(
            self,
            "incomplete_namespaces",
            _unique_tokens(
                self.incomplete_namespaces,
                "incomplete_namespaces",
                allow_empty=True,
            ),
        )
        if any(not isinstance(item, SystemStateSourceErrorV1) for item in self.errors):
            raise TypeError("errors must contain SystemStateSourceErrorV1 values")
        if self.status is SystemStateSourceStatus.COMPLETE and (
            self.incomplete_namespaces or self.errors
        ):
            raise ValueError("COMPLETE source result cannot contain gaps or errors")
        if self.status is SystemStateSourceStatus.ERROR and not self.errors:
            raise ValueError("ERROR source result requires an explicit source error")
        if self.schema_version != SYSTEM_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported SystemState source-result schema_version")


class SystemStateSource(Protocol):
    source_key: str
    source_version: int
    namespaces: tuple[str, ...]

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1: ...


class DuplicateSystemStateSourceError(RuntimeError):
    pass


class SystemStateSourceRegistry:
    """Exact source-namespace registry; canonical source ownership cannot overlap."""

    def __init__(self, sources: Iterable[SystemStateSource] = ()) -> None:
        self._sources: dict[str, SystemStateSource] = {}
        self._source_keys: dict[tuple[str, int], SystemStateSource] = {}
        for source in sources:
            self.register(source)

    def register(self, source: SystemStateSource) -> None:
        source_key = _token(getattr(source, "source_key", ""), "source_key")
        source_version = _positive_int(
            getattr(source, "source_version", None),
            "source_version",
        )
        namespaces = _unique_tokens(
            tuple(getattr(source, "namespaces", ())),
            "source namespaces",
        )
        if not callable(getattr(source, "read", None)):
            raise TypeError("SystemState source must provide read(request)")
        source_identity = (source_key, source_version)
        existing_source = self._source_keys.get(source_identity)
        if existing_source is not None and existing_source is not source:
            raise DuplicateSystemStateSourceError(
                f"SystemState source already registered: {source_key}.v{source_version}"
            )
        for namespace in namespaces:
            existing = self._sources.get(namespace)
            if existing is not None and existing is not source:
                raise DuplicateSystemStateSourceError(
                    f"SystemState namespace already owned: {namespace}"
                )
        self._source_keys[source_identity] = source
        for namespace in namespaces:
            self._sources[namespace] = source

    def source_for_namespace(self, namespace: str) -> SystemStateSource | None:
        return self._sources.get(_token(namespace, "namespace"))

    def namespaces(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))

    def sources(self) -> tuple[SystemStateSource, ...]:
        unique = {
            (source.source_key, source.source_version): source
            for source in self._sources.values()
        }
        return tuple(unique[key] for key in sorted(unique))


@dataclass(frozen=True, slots=True)
class SystemStateSnapshotV1:
    snapshot_id: str
    snapshot_digest: str
    evaluated_source_namespaces: tuple[str, ...]
    facts: tuple[SystemStateFactV1, ...]
    source_errors: tuple[SystemStateSourceErrorV1, ...]
    incomplete_namespaces: tuple[str, ...]
    started_at_epoch: float
    ended_at_epoch: float
    producer_version: str
    schema_version: str = SYSTEM_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_id",
            _text(self.snapshot_id, "snapshot_id", max_length=240),
        )
        object.__setattr__(
            self,
            "snapshot_digest",
            _sha256(self.snapshot_digest, "snapshot_digest"),
        )
        object.__setattr__(
            self,
            "evaluated_source_namespaces",
            _unique_tokens(
                self.evaluated_source_namespaces,
                "evaluated_source_namespaces",
            ),
        )
        if any(not isinstance(item, SystemStateFactV1) for item in self.facts):
            raise TypeError("facts must contain SystemStateFactV1 values")
        if len({item.digest for item in self.facts}) != len(self.facts):
            raise ValueError("snapshot facts must be unique")
        if any(
            not isinstance(item, SystemStateSourceErrorV1)
            for item in self.source_errors
        ):
            raise TypeError("source_errors must contain SystemStateSourceErrorV1 values")
        object.__setattr__(
            self,
            "incomplete_namespaces",
            _unique_tokens(
                self.incomplete_namespaces,
                "incomplete_namespaces",
                allow_empty=True,
            ),
        )
        started = _epoch(self.started_at_epoch, "started_at_epoch")
        ended = _epoch(self.ended_at_epoch, "ended_at_epoch")
        if ended < started:
            raise ValueError("ended_at_epoch cannot precede started_at_epoch")
        object.__setattr__(self, "started_at_epoch", started)
        object.__setattr__(self, "ended_at_epoch", ended)
        object.__setattr__(
            self,
            "producer_version",
            _text(self.producer_version, "producer_version", max_length=200),
        )
        if self.schema_version != SYSTEM_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported SystemState snapshot schema_version")

    @property
    def fact_digests(self) -> tuple[str, ...]:
        return tuple(item.digest for item in self.facts)

    @classmethod
    def create(
        cls,
        *,
        evaluated_source_namespaces: tuple[str, ...],
        facts: tuple[SystemStateFactV1, ...],
        source_errors: tuple[SystemStateSourceErrorV1, ...],
        incomplete_namespaces: tuple[str, ...],
        started_at_epoch: float,
        ended_at_epoch: float,
        producer_version: str = SYSTEM_STATE_PRODUCER_VERSION,
    ) -> SystemStateSnapshotV1:
        normalized_namespaces = tuple(sorted(evaluated_source_namespaces))
        normalized_facts = tuple(
            sorted(
                facts,
                key=lambda item: (
                    item.fact_namespace,
                    item.target_namespace,
                    item.target_identity,
                    item.digest,
                ),
            )
        )
        normalized_errors = tuple(
            sorted(
                source_errors,
                key=lambda item: (
                    item.source_namespace,
                    item.source_adapter_key,
                    item.source_adapter_version,
                    item.reason_code,
                    item.summary,
                ),
            )
        )
        normalized_incomplete = tuple(sorted(set(incomplete_namespaces)))
        payload = {
            "evaluated_source_namespaces": list(normalized_namespaces),
            "facts": [item.to_payload() for item in normalized_facts],
            "source_errors": [item.to_payload() for item in normalized_errors],
            "incomplete_namespaces": list(normalized_incomplete),
            "started_at_epoch": float(started_at_epoch),
            "ended_at_epoch": float(ended_at_epoch),
            "producer_version": producer_version,
            "schema_version": SYSTEM_STATE_SCHEMA_VERSION,
        }
        digest = canonical_digest(payload)
        return cls(
            snapshot_id=f"system_snapshot_{digest[:24]}",
            snapshot_digest=digest,
            evaluated_source_namespaces=normalized_namespaces,
            facts=normalized_facts,
            source_errors=normalized_errors,
            incomplete_namespaces=normalized_incomplete,
            started_at_epoch=started_at_epoch,
            ended_at_epoch=ended_at_epoch,
            producer_version=producer_version,
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_digest": self.snapshot_digest,
            "evaluated_source_namespaces": list(self.evaluated_source_namespaces),
            "facts": [item.to_payload() for item in self.facts],
            "source_errors": [item.to_payload() for item in self.source_errors],
            "incomplete_namespaces": list(self.incomplete_namespaces),
            "started_at_epoch": self.started_at_epoch,
            "ended_at_epoch": self.ended_at_epoch,
            "producer_version": self.producer_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        if payload.get("schema_version") != SYSTEM_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported SystemState snapshot schema_version")
        rebuilt = cls.create(
            evaluated_source_namespaces=tuple(payload["evaluated_source_namespaces"]),
            facts=tuple(
                SystemStateFactV1.from_payload(dict(item))
                for item in payload["facts"]
            ),
            source_errors=tuple(
                SystemStateSourceErrorV1.from_payload(dict(item))
                for item in payload["source_errors"]
            ),
            incomplete_namespaces=tuple(payload["incomplete_namespaces"]),
            started_at_epoch=float(payload["started_at_epoch"]),
            ended_at_epoch=float(payload["ended_at_epoch"]),
            producer_version=str(payload["producer_version"]),
        )
        if payload.get("snapshot_id") != rebuilt.snapshot_id:
            raise ValueError("SystemState snapshot identity mismatch")
        if payload.get("snapshot_digest") != rebuilt.snapshot_digest:
            raise ValueError("SystemState snapshot digest mismatch")
        return rebuilt


class SystemStateAggregator:
    """Build bounded immutable evidence snapshots from registered canonical readers."""

    def __init__(
        self,
        registry: SystemStateSourceRegistry,
        *,
        clock=time.time,
        producer_version: str = SYSTEM_STATE_PRODUCER_VERSION,
    ) -> None:
        if not isinstance(registry, SystemStateSourceRegistry):
            raise TypeError("registry must be a SystemStateSourceRegistry")
        self.registry = registry
        self.clock = clock
        self.producer_version = _text(
            producer_version,
            "producer_version",
            max_length=200,
        )

    def snapshot(
        self,
        *,
        requested_namespaces: tuple[str, ...],
        targets: tuple[SystemStateTargetV1, ...] = (),
        max_facts: int = 500,
    ) -> SystemStateSnapshotV1:
        started = float(self.clock())
        request = SystemStateReadRequestV1(
            requested_namespaces=requested_namespaces,
            targets=targets,
            now_epoch=started,
            max_facts=max_facts,
        )
        grouped: dict[tuple[str, int], tuple[SystemStateSource, set[str]]] = {}
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()
        facts: list[SystemStateFactV1] = []

        for namespace in request.requested_namespaces:
            source = self.registry.source_for_namespace(namespace)
            if source is None:
                incomplete.add(namespace)
                errors.append(
                    SystemStateSourceErrorV1(
                        source_namespace=namespace,
                        source_adapter_key="system_state.registry",
                        source_adapter_version=1,
                        reason_code="source_not_registered",
                        summary="No canonical SystemState source is registered.",
                    )
                )
                continue
            key = (source.source_key, source.source_version)
            if key not in grouped:
                grouped[key] = (source, set())
            grouped[key][1].add(namespace)

        for source, namespaces in (grouped[key] for key in sorted(grouped)):
            source_namespaces = tuple(sorted(namespaces))
            subrequest = request.for_namespaces(source_namespaces)
            try:
                result = source.read(subrequest)
            except Exception as exc:  # noqa: BLE001 - source failure becomes evidence
                for namespace in source_namespaces:
                    incomplete.add(namespace)
                    errors.append(
                        SystemStateSourceErrorV1(
                            source_namespace=namespace,
                            source_adapter_key=source.source_key,
                            source_adapter_version=source.source_version,
                            reason_code="source_read_failed",
                            summary=type(exc).__name__,
                        )
                    )
                continue

            if (
                result.source_adapter_key != source.source_key
                or result.source_adapter_version != source.source_version
            ):
                for namespace in source_namespaces:
                    incomplete.add(namespace)
                    errors.append(
                        SystemStateSourceErrorV1(
                            source_namespace=namespace,
                            source_adapter_key=source.source_key,
                            source_adapter_version=source.source_version,
                            reason_code="source_identity_mismatch",
                            summary="Source result adapter identity did not match registry.",
                        )
                    )
                continue

            out_of_scope = tuple(
                fact
                for fact in result.facts
                if fact.fact_namespace not in namespaces
            )
            if out_of_scope:
                for namespace in source_namespaces:
                    incomplete.add(namespace)
                    errors.append(
                        SystemStateSourceErrorV1(
                            source_namespace=namespace,
                            source_adapter_key=source.source_key,
                            source_adapter_version=source.source_version,
                            reason_code="source_fact_scope_violation",
                            summary="Source returned a fact outside requested namespaces.",
                        )
                    )
                continue

            facts.extend(result.facts)
            incomplete.update(result.incomplete_namespaces)
            errors.extend(result.errors)
            if result.status is not SystemStateSourceStatus.COMPLETE:
                incomplete.update(source_namespaces)

            for fact in result.facts:
                if not fact.is_fresh(now_epoch=started):
                    incomplete.add(fact.fact_namespace)
                    errors.append(
                        SystemStateSourceErrorV1(
                            source_namespace=fact.fact_namespace,
                            source_adapter_key=source.source_key,
                            source_adapter_version=source.source_version,
                            reason_code="stale_fact",
                            summary="Canonical source returned stale evidence.",
                        )
                    )

            if len(facts) > request.max_facts:
                raise ValueError("SystemState fact limit exceeded")

        ended = float(self.clock())
        return SystemStateSnapshotV1.create(
            evaluated_source_namespaces=request.requested_namespaces,
            facts=tuple(facts),
            source_errors=tuple(errors),
            incomplete_namespaces=tuple(incomplete),
            started_at_epoch=started,
            ended_at_epoch=ended,
            producer_version=self.producer_version,
        )
