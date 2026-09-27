"""Standardized read-only acquisition source normalization for Phase 9C."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.source import AcquisitionContextV1
from jarvis.engineering_substrate.canonical import canonical_digest

_MAX_SOURCE_DOCUMENT_BYTES = 1024 * 1024
_MAX_OPERATIONS = 256
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


class SourceEvidenceError(ValueError):
    """External source evidence is malformed, ambiguous or over policy bounds."""


def _text(value: object, *, field: str, max_length: int = 1000) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise SourceEvidenceError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise SourceEvidenceError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise SourceEvidenceError(f"{field} contains control characters")
    return normalized


def _operations(values: Sequence[object]) -> tuple[str, ...]:
    normalized = tuple(
        sorted(
            {
                _text(value, field="operation", max_length=120).casefold()
                for value in values
            }
        )
    )
    if not normalized:
        raise SourceEvidenceError("source evidence requires semantic operations")
    if len(normalized) > _MAX_OPERATIONS:
        raise SourceEvidenceError("source evidence exceeds operation limit")
    return normalized


def _refs(
    values: Sequence[object],
    *,
    field: str,
    required: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(
        sorted({_text(value, field=field, max_length=1000) for value in values})
    )
    if required and not normalized:
        raise SourceEvidenceError(f"{field} requires at least one value")
    return normalized


def _bounded_json_digest(payload: Mapping[str, object], *, field: str) -> str:
    if not isinstance(payload, Mapping):
        raise SourceEvidenceError(f"{field} must be a mapping")
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SourceEvidenceError(f"{field} must contain JSON-compatible values") from exc
    if not encoded or len(encoded) > _MAX_SOURCE_DOCUMENT_BYTES:
        raise SourceEvidenceError(
            f"{field} must be between 1 and {_MAX_SOURCE_DOCUMENT_BYTES} bytes"
        )
    return canonical_digest(dict(payload))


@dataclass(frozen=True, slots=True)
class StandardSourceEvidenceV1:
    """Normalized non-executing evidence from one reusable acquisition source."""

    source_kind: AcquisitionSourceKind
    source_identity: str
    source_version: str | None
    source_digest: str
    trust_class: AcquisitionTrustClass
    supported_operations: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    secret_scopes: tuple[str, ...]
    network_scopes: tuple[str, ...]
    device_scopes: tuple[str, ...]
    discovery_scopes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    license_id: str | None
    provenance_refs: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    external_acceptance_requirements: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.source_kind in {
            AcquisitionSourceKind.EXISTING_CAPABILITY,
            AcquisitionSourceKind.CUSTOM_BUILD,
        }:
            raise SourceEvidenceError(
                "standard source evidence must represent a reusable external/local source"
            )
        if self.trust_class is AcquisitionTrustClass.ACCEPTED_RELEASE:
            raise SourceEvidenceError(
                "standard external source evidence cannot claim accepted-release trust"
            )

    def to_candidate(
        self,
        *,
        strategy: AcquisitionStrategy,
    ) -> AcquisitionCandidateV1:
        return AcquisitionCandidateV1.create(
            source_kind=self.source_kind,
            source_identity=self.source_identity,
            source_version=self.source_version,
            source_digest=self.source_digest,
            trust_class=self.trust_class,
            supported_operations=self.supported_operations,
            dependency_refs=self.dependency_refs,
            secret_scopes=self.secret_scopes,
            network_scopes=self.network_scopes,
            device_scopes=self.device_scopes,
            discovery_scopes=self.discovery_scopes,
            evidence_refs=self.evidence_refs,
            license_id=self.license_id,
            provenance_refs=self.provenance_refs,
            strategy=strategy,
            verification_requirements=self.verification_requirements,
            external_acceptance_requirements=(
                self.external_acceptance_requirements
            ),
            reason_codes=self.reason_codes,
        )


def _evidence(
    *,
    source_kind: AcquisitionSourceKind,
    source_identity: str,
    source_version: str | None,
    source_digest: str,
    trust_class: AcquisitionTrustClass,
    supported_operations: Sequence[object],
    evidence_refs: Sequence[object],
    verification_requirements: Sequence[object],
    dependency_refs: Sequence[object] = (),
    secret_scopes: Sequence[object] = (),
    network_scopes: Sequence[object] = (),
    device_scopes: Sequence[object] = (),
    discovery_scopes: Sequence[object] = (),
    license_id: str | None = None,
    provenance_refs: Sequence[object] = (),
    external_acceptance_requirements: Sequence[object] = (),
    reason_codes: Sequence[object] = (),
) -> StandardSourceEvidenceV1:
    return StandardSourceEvidenceV1(
        source_kind=source_kind,
        source_identity=_text(source_identity, field="source_identity"),
        source_version=(
            None
            if source_version is None
            else _text(source_version, field="source_version", max_length=240)
        ),
        source_digest=_text(
            source_digest,
            field="source_digest",
            max_length=64,
        ).casefold(),
        trust_class=trust_class,
        supported_operations=_operations(supported_operations),
        dependency_refs=_refs(dependency_refs, field="dependency_ref"),
        secret_scopes=tuple(
            item.casefold() for item in _refs(secret_scopes, field="secret_scope")
        ),
        network_scopes=_refs(network_scopes, field="network_scope"),
        device_scopes=_refs(device_scopes, field="device_scope"),
        discovery_scopes=tuple(
            item.casefold()
            for item in _refs(discovery_scopes, field="discovery_scope")
        ),
        evidence_refs=_refs(evidence_refs, field="evidence_ref", required=True),
        license_id=(
            None if license_id is None else _text(license_id, field="license_id")
        ),
        provenance_refs=_refs(provenance_refs, field="provenance_ref"),
        verification_requirements=_refs(
            verification_requirements,
            field="verification_requirement",
            required=True,
        ),
        external_acceptance_requirements=_refs(
            external_acceptance_requirements,
            field="external_acceptance_requirement",
        ),
        reason_codes=tuple(
            item.casefold() for item in _refs(reason_codes, field="reason_code")
        ),
    )


def owner_configured_evidence(
    *,
    source_identity: str,
    source_digest: str,
    supported_operations: Sequence[object],
    evidence_refs: Sequence[object],
    verification_requirements: Sequence[object],
    source_version: str | None = None,
    dependency_refs: Sequence[object] = (),
    secret_scopes: Sequence[object] = (),
    network_scopes: Sequence[object] = (),
    device_scopes: Sequence[object] = (),
    discovery_scopes: Sequence[object] = (),
    provenance_refs: Sequence[object] = (),
    external_acceptance_requirements: Sequence[object] = (),
) -> StandardSourceEvidenceV1:
    return _evidence(
        source_kind=AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL,
        source_identity=source_identity,
        source_version=source_version,
        source_digest=source_digest,
        trust_class=AcquisitionTrustClass.OWNER_CONFIGURED,
        supported_operations=supported_operations,
        evidence_refs=evidence_refs,
        verification_requirements=verification_requirements,
        dependency_refs=dependency_refs,
        secret_scopes=secret_scopes,
        network_scopes=network_scopes,
        device_scopes=device_scopes,
        discovery_scopes=discovery_scopes,
        provenance_refs=provenance_refs,
        external_acceptance_requirements=external_acceptance_requirements,
        reason_codes=("owner_configured_source",),
    )


def mcp_server_evidence(
    *,
    server_identity: str,
    tools: Sequence[Mapping[str, object]],
    trust_class: AcquisitionTrustClass,
    evidence_refs: Sequence[object],
    server_version: str | None = None,
    dependency_refs: Sequence[object] = (),
    secret_scopes: Sequence[object] = (),
    network_scopes: Sequence[object] = (),
    provenance_refs: Sequence[object] = (),
) -> StandardSourceEvidenceV1:
    if not tools or len(tools) > _MAX_OPERATIONS:
        raise SourceEvidenceError("MCP evidence requires a bounded non-empty tool list")
    normalized_tools: list[dict[str, object]] = []
    tool_names: list[str] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            raise SourceEvidenceError("MCP tool evidence must be a mapping")
        name = _text(tool.get("name"), field="MCP tool name", max_length=120)
        schema = tool.get("inputSchema", {})
        if not isinstance(schema, Mapping):
            raise SourceEvidenceError("MCP tool inputSchema must be a mapping")
        normalized_tools.append(
            {
                "name": name,
                "input_schema_digest": _bounded_json_digest(
                    dict(schema),
                    field="MCP tool inputSchema",
                ),
            }
        )
        tool_names.append(name)
    normalized_tools.sort(key=lambda item: str(item["name"]).casefold())
    source_digest = canonical_digest(
        {
            "server_identity": _text(
                server_identity,
                field="server_identity",
            ),
            "server_version": server_version,
            "tools": normalized_tools,
        }
    )
    return _evidence(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity=server_identity,
        source_version=server_version,
        source_digest=source_digest,
        trust_class=trust_class,
        supported_operations=tool_names,
        evidence_refs=evidence_refs,
        verification_requirements=("mcp-tools-list-contract",),
        dependency_refs=dependency_refs,
        secret_scopes=secret_scopes,
        network_scopes=network_scopes,
        provenance_refs=provenance_refs,
        reason_codes=("mcp_standard_source",),
    )


def openapi_contract_evidence(
    *,
    source_identity: str,
    document: Mapping[str, object],
    trust_class: AcquisitionTrustClass,
    evidence_refs: Sequence[object],
    secret_scopes: Sequence[object] = (),
    network_scopes: Sequence[object] = (),
    provenance_refs: Sequence[object] = (),
) -> StandardSourceEvidenceV1:
    source_digest = _bounded_json_digest(document, field="OpenAPI document")
    version = _text(document.get("openapi"), field="OpenAPI version", max_length=40)
    if not version.startswith("3."):
        raise SourceEvidenceError("only OpenAPI 3.x contracts are supported")
    paths = document.get("paths")
    if not isinstance(paths, Mapping):
        raise SourceEvidenceError("OpenAPI document requires a paths mapping")
    operations: list[str] = []
    for path_item in paths.values():
        if not isinstance(path_item, Mapping):
            continue
        for method, operation in path_item.items():
            if str(method).casefold() not in _HTTP_METHODS:
                continue
            if not isinstance(operation, Mapping):
                continue
            operation_id = operation.get("operationId")
            if operation_id is not None and str(operation_id).strip():
                operations.append(str(operation_id))
    return _evidence(
        source_kind=AcquisitionSourceKind.OPENAPI,
        source_identity=source_identity,
        source_version=version,
        source_digest=source_digest,
        trust_class=trust_class,
        supported_operations=operations,
        evidence_refs=evidence_refs,
        verification_requirements=("openapi-contract-test",),
        secret_scopes=secret_scopes,
        network_scopes=network_scopes,
        provenance_refs=provenance_refs,
        reason_codes=("openapi_contract_source",),
    )


def asyncapi_contract_evidence(
    *,
    source_identity: str,
    document: Mapping[str, object],
    trust_class: AcquisitionTrustClass,
    evidence_refs: Sequence[object],
    secret_scopes: Sequence[object] = (),
    network_scopes: Sequence[object] = (),
    provenance_refs: Sequence[object] = (),
) -> StandardSourceEvidenceV1:
    source_digest = _bounded_json_digest(document, field="AsyncAPI document")
    version = _text(document.get("asyncapi"), field="AsyncAPI version", max_length=40)
    operations: list[str] = []
    top_level = document.get("operations")
    if isinstance(top_level, Mapping):
        for key, operation in top_level.items():
            if not isinstance(operation, Mapping):
                continue
            operation_id = operation.get("operationId") or key
            if str(operation_id).strip():
                operations.append(str(operation_id))
    else:
        channels = document.get("channels")
        if not isinstance(channels, Mapping):
            raise SourceEvidenceError(
                "AsyncAPI document requires operations or channels"
            )
        for channel in channels.values():
            if not isinstance(channel, Mapping):
                continue
            for action in ("publish", "subscribe"):
                operation = channel.get(action)
                if not isinstance(operation, Mapping):
                    continue
                operation_id = operation.get("operationId")
                if operation_id is not None and str(operation_id).strip():
                    operations.append(str(operation_id))
    return _evidence(
        source_kind=AcquisitionSourceKind.ASYNCAPI,
        source_identity=source_identity,
        source_version=version,
        source_digest=source_digest,
        trust_class=trust_class,
        supported_operations=operations,
        evidence_refs=evidence_refs,
        verification_requirements=("asyncapi-contract-test",),
        secret_scopes=secret_scopes,
        network_scopes=network_scopes,
        provenance_refs=provenance_refs,
        reason_codes=("asyncapi_contract_source",),
    )


def sdk_library_evidence(
    *,
    package_identity: str,
    package_version: str,
    package_digest: str,
    trust_class: AcquisitionTrustClass,
    supported_operations: Sequence[object],
    evidence_refs: Sequence[object],
    provenance_refs: Sequence[object],
    license_id: str | None = None,
    dependency_refs: Sequence[object] = (),
    secret_scopes: Sequence[object] = (),
    network_scopes: Sequence[object] = (),
    device_scopes: Sequence[object] = (),
) -> StandardSourceEvidenceV1:
    return _evidence(
        source_kind=AcquisitionSourceKind.SDK_LIBRARY,
        source_identity=package_identity,
        source_version=package_version,
        source_digest=package_digest,
        trust_class=trust_class,
        supported_operations=supported_operations,
        evidence_refs=evidence_refs,
        verification_requirements=("sdk-adapter-contract-test",),
        dependency_refs=dependency_refs,
        secret_scopes=secret_scopes,
        network_scopes=network_scopes,
        device_scopes=device_scopes,
        license_id=license_id,
        provenance_refs=provenance_refs,
        reason_codes=("sdk_library_source",),
    )


class _EvidenceSourceAdapter:
    source_kind: AcquisitionSourceKind
    strategy: AcquisitionStrategy

    def __init__(self, evidence: Sequence[StandardSourceEvidenceV1]) -> None:
        items = tuple(evidence)
        if any(item.source_kind is not self.source_kind for item in items):
            raise SourceEvidenceError(
                f"{self.source_kind.value} adapter received another source kind"
            )
        identities = tuple(
            (item.source_identity, item.source_version, item.source_digest)
            for item in items
        )
        if len(identities) != len(set(identities)):
            raise SourceEvidenceError("source adapter evidence identities must be unique")
        self._evidence = tuple(
            sorted(
                items,
                key=lambda item: (
                    item.source_identity,
                    item.source_version or "",
                    item.source_digest,
                ),
            )
        )

    def discover(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> tuple[AcquisitionCandidateV1, ...]:
        if not isinstance(goal, OwnerCapabilityGoalV1):
            raise TypeError("goal must be OwnerCapabilityGoalV1")
        if not isinstance(context, AcquisitionContextV1):
            raise TypeError("context must be AcquisitionContextV1")
        required = set(goal.required_operations)
        return tuple(
            item.to_candidate(strategy=self.strategy)
            for item in self._evidence
            if required.issubset(item.supported_operations)
        )


class OwnerConfiguredCapabilitySourceAdapter(_EvidenceSourceAdapter):
    source_kind = AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL
    strategy = AcquisitionStrategy.WRAP


class McpCapabilitySourceAdapter(_EvidenceSourceAdapter):
    source_kind = AcquisitionSourceKind.MCP
    strategy = AcquisitionStrategy.WRAP


class OpenApiCapabilitySourceAdapter(_EvidenceSourceAdapter):
    source_kind = AcquisitionSourceKind.OPENAPI
    strategy = AcquisitionStrategy.GENERATE_CONTRACT_CLIENT


class AsyncApiCapabilitySourceAdapter(_EvidenceSourceAdapter):
    source_kind = AcquisitionSourceKind.ASYNCAPI
    strategy = AcquisitionStrategy.GENERATE_CONTRACT_CLIENT


class SdkLibraryCapabilitySourceAdapter(_EvidenceSourceAdapter):
    source_kind = AcquisitionSourceKind.SDK_LIBRARY
    strategy = AcquisitionStrategy.ADAPT_SDK


class CustomBuildCapabilitySourceAdapter:
    """Deterministic last-resort source plan; it executes nothing."""

    source_kind = AcquisitionSourceKind.CUSTOM_BUILD

    def discover(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> tuple[AcquisitionCandidateV1, ...]:
        if not isinstance(goal, OwnerCapabilityGoalV1):
            raise TypeError("goal must be OwnerCapabilityGoalV1")
        if not isinstance(context, AcquisitionContextV1):
            raise TypeError("context must be AcquisitionContextV1")
        return (
            AcquisitionCandidateV1.create(
                source_kind=self.source_kind,
                source_identity=f"owner-goal:{goal.goal_id}",
                source_version="1",
                source_digest=goal.digest,
                trust_class=AcquisitionTrustClass.OWNER_CONFIGURED,
                supported_operations=goal.required_operations,
                strategy=AcquisitionStrategy.BUILD_CUSTOM,
                evidence_refs=(f"owner-goal-sha256:{goal.digest}",),
                verification_requirements=(
                    "phase5-sandbox-verification",
                    "phase6-candidate-verification",
                ),
                reason_codes=("custom_build_fallback",),
            ),
        )
