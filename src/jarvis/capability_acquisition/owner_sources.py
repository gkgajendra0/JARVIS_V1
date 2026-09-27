"""Read-only owner-approved reusable source evidence for Phase-9 acquisition."""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from jarvis.capability_acquisition.models import (
    AcquisitionSourceKind,
    AcquisitionTrustClass,
)
from jarvis.capability_acquisition.source import CapabilitySourceRegistry
from jarvis.capability_acquisition.standard_sources import (
    AsyncApiCapabilitySourceAdapter,
    McpCapabilitySourceAdapter,
    OpenApiCapabilitySourceAdapter,
    OwnerConfiguredCapabilitySourceAdapter,
    SdkLibraryCapabilitySourceAdapter,
    StandardSourceEvidenceV1,
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_SOURCES = 128
_ALLOWED_KINDS = frozenset(
    {
        AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL,
        AcquisitionSourceKind.MCP,
        AcquisitionSourceKind.OPENAPI,
        AcquisitionSourceKind.ASYNCAPI,
        AcquisitionSourceKind.SDK_LIBRARY,
    }
)


class OwnerSourceRegistryError(ValueError):
    """Owner-configured source registry content is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class OwnerSourceRegistry:
    evidence: tuple[StandardSourceEvidenceV1, ...]

    def adapters(self) -> tuple[object, ...]:
        grouped: dict[AcquisitionSourceKind, list[StandardSourceEvidenceV1]] = {
            kind: [] for kind in _ALLOWED_KINDS
        }
        for item in self.evidence:
            grouped[item.source_kind].append(item)
        return (
            OwnerConfiguredCapabilitySourceAdapter(
                grouped[AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL]
            ),
            McpCapabilitySourceAdapter(grouped[AcquisitionSourceKind.MCP]),
            OpenApiCapabilitySourceAdapter(grouped[AcquisitionSourceKind.OPENAPI]),
            AsyncApiCapabilitySourceAdapter(grouped[AcquisitionSourceKind.ASYNCAPI]),
            SdkLibraryCapabilitySourceAdapter(
                grouped[AcquisitionSourceKind.SDK_LIBRARY]
            ),
        )


def default_owner_source_registry_path() -> pathlib.Path:
    return (
        pathlib.Path.home()
        / ".jarvis"
        / "capability_acquisition"
        / "owner_sources.json"
    )


def _text(value: object, *, field: str, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise OwnerSourceRegistryError(f"{field} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise OwnerSourceRegistryError(f"{field} must not be empty")
    return normalized or None


def _strings(
    value: object,
    *,
    field: str,
    required: bool = False,
    max_items: int = 256,
) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list):
        raise OwnerSourceRegistryError(f"{field} must be an array")
    if required and not value:
        raise OwnerSourceRegistryError(f"{field} must not be empty")
    if len(value) > max_items:
        raise OwnerSourceRegistryError(f"{field} exceeds bounded item limit")
    output: list[str] = []
    for item in value:
        text = _text(item, field=field)
        assert text is not None
        output.append(text)
    if len(output) != len(set(output)):
        raise OwnerSourceRegistryError(f"{field} values must be unique")
    return tuple(output)


def _source(payload: object) -> StandardSourceEvidenceV1:
    if not isinstance(payload, dict):
        raise OwnerSourceRegistryError("source entry must be an object")
    allowed = {
        "source_kind",
        "source_identity",
        "source_version",
        "source_digest",
        "supported_operations",
        "dependency_refs",
        "secret_scopes",
        "network_scopes",
        "device_scopes",
        "discovery_scopes",
        "evidence_refs",
        "license_id",
        "provenance_refs",
        "verification_requirements",
        "external_acceptance_requirements",
    }
    unexpected = tuple(sorted(set(payload) - allowed))
    if unexpected:
        raise OwnerSourceRegistryError(
            "owner source contains unsupported fields: " + ", ".join(unexpected)
        )
    try:
        kind = AcquisitionSourceKind(str(payload.get("source_kind") or ""))
    except ValueError as exc:
        raise OwnerSourceRegistryError("unsupported owner source kind") from exc
    if kind not in _ALLOWED_KINDS:
        raise OwnerSourceRegistryError(
            "owner source kind cannot represent built-in/custom capability truth"
        )
    digest = _text(payload.get("source_digest"), field="source_digest")
    assert digest is not None
    digest = digest.casefold()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise OwnerSourceRegistryError("source_digest must be lowercase SHA-256")
    evidence_refs = _strings(
        payload.get("evidence_refs"),
        field="evidence_refs",
        required=True,
        max_items=50,
    )
    verification = _strings(
        payload.get("verification_requirements"),
        field="verification_requirements",
        required=True,
        max_items=30,
    )
    identity = _text(payload.get("source_identity"), field="source_identity")
    assert identity is not None
    return StandardSourceEvidenceV1(
        source_kind=kind,
        source_identity=identity,
        source_version=_text(
            payload.get("source_version"),
            field="source_version",
            required=False,
        ),
        source_digest=digest,
        trust_class=AcquisitionTrustClass.OWNER_CONFIGURED,
        supported_operations=_strings(
            payload.get("supported_operations"),
            field="supported_operations",
            required=True,
        ),
        dependency_refs=_strings(
            payload.get("dependency_refs"),
            field="dependency_refs",
            max_items=100,
        ),
        secret_scopes=tuple(
            item.casefold()
            for item in _strings(
                payload.get("secret_scopes"),
                field="secret_scopes",
                max_items=50,
            )
        ),
        network_scopes=_strings(
            payload.get("network_scopes"),
            field="network_scopes",
            max_items=50,
        ),
        device_scopes=_strings(
            payload.get("device_scopes"),
            field="device_scopes",
            max_items=50,
        ),
        discovery_scopes=tuple(
            item.casefold()
            for item in _strings(
                payload.get("discovery_scopes"),
                field="discovery_scopes",
                max_items=50,
            )
        ),
        evidence_refs=evidence_refs,
        license_id=_text(
            payload.get("license_id"),
            field="license_id",
            required=False,
        ),
        provenance_refs=_strings(
            payload.get("provenance_refs"),
            field="provenance_refs",
            max_items=50,
        ),
        verification_requirements=verification,
        external_acceptance_requirements=_strings(
            payload.get("external_acceptance_requirements"),
            field="external_acceptance_requirements",
            max_items=30,
        ),
        reason_codes=("owner_configured_source_registry",),
    )


def load_owner_source_registry(
    path: str | pathlib.Path | None = None,
) -> OwnerSourceRegistry:
    source = pathlib.Path(path or default_owner_source_registry_path()).expanduser()
    if not source.exists():
        return OwnerSourceRegistry(())
    if source.is_symlink() or not source.is_file():
        raise OwnerSourceRegistryError(
            "owner source registry must be a regular non-symlink file"
        )
    if source.stat().st_size <= 0 or source.stat().st_size > _MAX_FILE_BYTES:
        raise OwnerSourceRegistryError("owner source registry has invalid size")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OwnerSourceRegistryError(
            "owner source registry is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise OwnerSourceRegistryError("owner source registry root must be an object")
    if set(payload) != {"schema_version", "sources"}:
        raise OwnerSourceRegistryError(
            "owner source registry root fields do not match v1 contract"
        )
    if payload.get("schema_version") != 1:
        raise OwnerSourceRegistryError("unsupported owner source registry version")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) > _MAX_SOURCES:
        raise OwnerSourceRegistryError("owner source registry sources are invalid")
    evidence = tuple(_source(item) for item in sources)
    identities = tuple(
        (
            item.source_kind,
            item.source_identity,
            item.source_version,
            item.source_digest,
        )
        for item in evidence
    )
    if len(identities) != len(set(identities)):
        raise OwnerSourceRegistryError("owner source identities must be unique")
    return OwnerSourceRegistry(
        tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.source_kind.value,
                    item.source_identity,
                    item.source_version or "",
                    item.source_digest,
                ),
            )
        )
    )


def registered_source_adapters(
    path: str | pathlib.Path | None = None,
) -> tuple[object, ...]:
    return load_owner_source_registry(path).adapters()
