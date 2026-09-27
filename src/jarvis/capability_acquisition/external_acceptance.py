"""Strict owner-machine evidence for one real Phase-9 acquired capability."""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

from jarvis.engineering_substrate.canonical import canonical_digest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "api_key",
        "apikey",
        "credential",
        "credentials",
        "pin",
    }
)
_MAX_EVIDENCE_BYTES = 256 * 1024


class Phase9ExternalAcceptanceError(RuntimeError):
    pass


def _text(value: object, *, field: str, max_length: int = 1000) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise Phase9ExternalAcceptanceError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise Phase9ExternalAcceptanceError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise Phase9ExternalAcceptanceError(f"{field} contains control characters")
    return normalized


def _reject_sensitive_keys(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().casefold()
            if normalized in _FORBIDDEN_KEYS:
                raise Phase9ExternalAcceptanceError(
                    f"external acceptance evidence must not contain secret field {path}.{key}"
                )
            _reject_sensitive_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class ExternalCapabilityOperationEvidenceV1:
    operation: str
    verified: bool
    external_effect_observed: bool
    observation: str
    evidence_refs: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "verified": self.verified,
            "external_effect_observed": self.external_effect_observed,
            "observation": self.observation,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class Phase9ExternalAcceptanceEvidenceV1:
    capability_id: str
    package_id: str
    package_version: str
    package_digest: str
    target_kind: str
    target_identity: str
    operations: tuple[ExternalCapabilityOperationEvidenceV1, ...]
    effective_enabled_verified: bool
    disable_rollback_verified: bool
    owner_confirmed: bool
    recorded_at: str
    source: str

    def payload(self) -> dict[str, object]:
        return {
            "schema": "phase9_external_acceptance.v1",
            "capability_id": self.capability_id,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "package_digest": self.package_digest,
            "target_kind": self.target_kind,
            "target_identity": self.target_identity,
            "operations": [item.payload() for item in self.operations],
            "effective_enabled_verified": self.effective_enabled_verified,
            "disable_rollback_verified": self.disable_rollback_verified,
            "owner_confirmed": self.owner_confirmed,
            "recorded_at": self.recorded_at,
            "source": self.source,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.payload())


def validate_external_acceptance(
    payload: object,
) -> Phase9ExternalAcceptanceEvidenceV1:
    if not isinstance(payload, dict):
        raise Phase9ExternalAcceptanceError(
            "external acceptance evidence must be a JSON object"
        )
    _reject_sensitive_keys(payload)
    allowed = {
        "schema",
        "capability_id",
        "package_id",
        "package_version",
        "package_digest",
        "target_kind",
        "target_identity",
        "operations",
        "effective_enabled_verified",
        "disable_rollback_verified",
        "owner_confirmed",
        "recorded_at",
        "source",
        "evidence_digest",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise Phase9ExternalAcceptanceError(
            "external acceptance evidence contains unknown fields: "
            + ", ".join(sorted(unknown))
        )
    if payload.get("schema") != "phase9_external_acceptance.v1":
        raise Phase9ExternalAcceptanceError("unsupported external acceptance schema")
    package_digest = _text(payload.get("package_digest"), field="package_digest").casefold()
    if _SHA256.fullmatch(package_digest) is None:
        raise Phase9ExternalAcceptanceError(
            "package_digest must be a lowercase SHA-256 digest"
        )
    target_kind = _text(payload.get("target_kind"), field="target_kind").casefold()
    if target_kind not in {"device", "service", "external_system"}:
        raise Phase9ExternalAcceptanceError(
            "target_kind must be device, service, or external_system"
        )
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise Phase9ExternalAcceptanceError(
            "external acceptance requires at least one operation"
        )
    operations: list[ExternalCapabilityOperationEvidenceV1] = []
    names: set[str] = set()
    external_effects = 0
    for raw in raw_operations:
        if not isinstance(raw, dict):
            raise Phase9ExternalAcceptanceError(
                "operation evidence must be a JSON object"
            )
        if set(raw) - {
            "operation",
            "verified",
            "external_effect_observed",
            "observation",
            "evidence_refs",
        }:
            raise Phase9ExternalAcceptanceError(
                "operation evidence contains unknown fields"
            )
        operation = _text(raw.get("operation"), field="operation", max_length=120).casefold()
        if operation in names:
            raise Phase9ExternalAcceptanceError(
                f"duplicate external acceptance operation: {operation}"
            )
        names.add(operation)
        if raw.get("verified") is not True:
            raise Phase9ExternalAcceptanceError(
                f"operation {operation} was not independently verified"
            )
        effect = raw.get("external_effect_observed") is True
        if effect:
            external_effects += 1
        refs_raw = raw.get("evidence_refs")
        if not isinstance(refs_raw, list) or not refs_raw:
            raise Phase9ExternalAcceptanceError(
                f"operation {operation} requires evidence_refs"
            )
        refs = tuple(
            dict.fromkeys(
                _text(item, field="evidence_ref", max_length=1000)
                for item in refs_raw
            )
        )
        operations.append(
            ExternalCapabilityOperationEvidenceV1(
                operation=operation,
                verified=True,
                external_effect_observed=effect,
                observation=_text(
                    raw.get("observation"),
                    field="observation",
                    max_length=4000,
                ),
                evidence_refs=refs,
            )
        )
    if external_effects < 1:
        raise Phase9ExternalAcceptanceError(
            "real acceptance requires at least one observed external effect"
        )
    for field in (
        "effective_enabled_verified",
        "disable_rollback_verified",
        "owner_confirmed",
    ):
        if payload.get(field) is not True:
            raise Phase9ExternalAcceptanceError(f"{field} must be true")

    evidence = Phase9ExternalAcceptanceEvidenceV1(
        capability_id=_text(
            payload.get("capability_id"),
            field="capability_id",
            max_length=180,
        ).casefold(),
        package_id=_text(
            payload.get("package_id"),
            field="package_id",
            max_length=180,
        ).casefold(),
        package_version=_text(
            payload.get("package_version"),
            field="package_version",
            max_length=80,
        ),
        package_digest=package_digest,
        target_kind=target_kind,
        target_identity=_text(
            payload.get("target_identity"),
            field="target_identity",
            max_length=500,
        ),
        operations=tuple(operations),
        effective_enabled_verified=True,
        disable_rollback_verified=True,
        owner_confirmed=True,
        recorded_at=_text(
            payload.get("recorded_at"),
            field="recorded_at",
            max_length=100,
        ),
        source=_text(payload.get("source"), field="source", max_length=200),
    )
    expected = payload.get("evidence_digest")
    if expected is not None and str(expected).strip().casefold() != evidence.digest:
        raise Phase9ExternalAcceptanceError(
            "external acceptance evidence_digest mismatch"
        )
    return evidence


def load_external_acceptance(
    path: pathlib.Path | str,
) -> Phase9ExternalAcceptanceEvidenceV1:
    candidate = pathlib.Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise Phase9ExternalAcceptanceError(
            "external acceptance evidence file is unavailable or unsafe"
        )
    size = candidate.stat().st_size
    if size <= 0 or size > _MAX_EVIDENCE_BYTES:
        raise Phase9ExternalAcceptanceError(
            "external acceptance evidence file size is invalid"
        )
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase9ExternalAcceptanceError(
            "external acceptance evidence file is unreadable"
        ) from exc
    return validate_external_acceptance(payload)
