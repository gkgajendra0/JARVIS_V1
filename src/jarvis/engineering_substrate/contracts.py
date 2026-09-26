"""Immutable, provider-neutral contracts for the Phase-5 engineering substrate."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION_V1 = 1
MAX_ITEMS = 64
MAX_DISCOVERY_HINTS = 16
MAX_DISCOVERY_TIMEOUT_SECONDS = 30.0
MAX_DISCOVERY_RESULTS = 64


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _token(value: object, *, field: str) -> str:
    return _required_text(value, field=field).casefold()


def _tokens(
    values: tuple[str, ...],
    *,
    field: str,
    required: bool = False,
    limit: int = MAX_ITEMS,
) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(_token(item, field=field) for item in values))
    if required and not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > limit:
        raise ValueError(f"{field} exceeds maximum of {limit}")
    return normalized


def _texts(
    values: tuple[str, ...],
    *,
    field: str,
    required: bool = False,
    limit: int = MAX_ITEMS,
) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(_required_text(item, field=field) for item in values)
    )
    if required and not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > limit:
        raise ValueError(f"{field} exceeds maximum of {limit}")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _positive_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return normalized


def _epoch(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _sha256(value: object, *, field: str) -> str:
    normalized = _token(value, field=field)
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def _digests(
    values: tuple[str, ...],
    *,
    field: str,
    limit: int = MAX_ITEMS,
) -> tuple[str, ...]:
    normalized = tuple(_sha256(item, field=field) for item in values)
    if len(normalized) > limit:
        raise ValueError(f"{field} exceeds maximum of {limit}")
    return normalized


def _schema_version(value: object) -> int:
    version = _positive_int(value, field="schema_version")
    if version != SCHEMA_VERSION_V1:
        raise ValueError(f"unsupported schema_version: {version}")
    return version


def _reject_wildcards(values: tuple[str, ...], *, field: str) -> None:
    for value in values:
        if value in {"*", "0.0.0.0/0", "::/0"}:
            raise ValueError(f"{field} cannot contain an unbounded wildcard")


class DependencyEcosystem(StrEnum):
    PYTHON = "python"


class SourceBuildPolicy(StrEnum):
    DENY = "deny"


class DistributionKind(StrEnum):
    WHEEL = "wheel"
    SDIST = "sdist"


class AttestationStatus(StrEnum):
    NOT_AVAILABLE = "not_available"
    VERIFIED = "verified"
    REJECTED = "rejected"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class SecretLifecycleState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class SecretMaterializationMode(StrEnum):
    CHILD_ENV = "child_env"


class SandboxNetworkMode(StrEnum):
    NONE = "none"
    REGISTERED_SOURCES = "registered_sources"


class SandboxFilesystemMode(StrEnum):
    READ_ONLY_ROOT = "read_only_root"


class HardwareAcceptanceVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class DependencyRequirement:
    requirement_id: str
    ecosystem: DependencyEcosystem
    package_name: str
    version_constraint: str
    purpose: str
    registered_source_ids: tuple[str, ...]
    platform_constraints: tuple[str, ...] = ()
    change_id: str | None = None
    work_id: str | None = None
    source_build_policy: SourceBuildPolicy = SourceBuildPolicy.DENY
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requirement_id",
            _required_text(self.requirement_id, field="requirement_id"),
        )
        if not isinstance(self.ecosystem, DependencyEcosystem):
            raise TypeError("ecosystem must be a DependencyEcosystem")
        object.__setattr__(
            self,
            "package_name",
            _token(self.package_name, field="package_name"),
        )
        object.__setattr__(
            self,
            "version_constraint",
            _required_text(self.version_constraint, field="version_constraint"),
        )
        object.__setattr__(
            self,
            "purpose",
            _required_text(self.purpose, field="purpose"),
        )
        object.__setattr__(
            self,
            "registered_source_ids",
            _tokens(
                self.registered_source_ids,
                field="registered_source_id",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "platform_constraints",
            _tokens(self.platform_constraints, field="platform_constraint"),
        )
        object.__setattr__(self, "change_id", _optional_text(self.change_id))
        object.__setattr__(self, "work_id", _optional_text(self.work_id))
        if self.source_build_policy is not SourceBuildPolicy.DENY:
            raise ValueError("source builds are denied by the Phase-5 v1 contract")
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class DependencyResolution:
    resolution_id: str
    requirement_id: str
    resolver_id: str
    resolver_version: str
    resolver_digest: str
    resolved_packages: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    dependency_graph_digest: str
    lock_format: str
    lock_version: str
    lock_digest: str
    platform_constraints: tuple[str, ...] = ()
    change_id: str | None = None
    work_id: str | None = None
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        for field_name in (
            "resolution_id",
            "requirement_id",
            "resolver_version",
            "lock_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "resolver_id",
            _token(self.resolver_id, field="resolver_id"),
        )
        object.__setattr__(
            self,
            "resolver_digest",
            _sha256(self.resolver_digest, field="resolver_digest"),
        )
        object.__setattr__(
            self,
            "resolved_packages",
            _texts(
                self.resolved_packages,
                field="resolved_package",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "artifact_ids",
            _texts(self.artifact_ids, field="artifact_id", required=True),
        )
        object.__setattr__(
            self,
            "dependency_graph_digest",
            _sha256(
                self.dependency_graph_digest,
                field="dependency_graph_digest",
            ),
        )
        lock_format = _token(self.lock_format, field="lock_format")
        if lock_format != "pylock.toml":
            raise ValueError("lock_format must be 'pylock.toml' for Python v1")
        object.__setattr__(self, "lock_format", lock_format)
        object.__setattr__(
            self,
            "lock_digest",
            _sha256(self.lock_digest, field="lock_digest"),
        )
        object.__setattr__(
            self,
            "platform_constraints",
            _tokens(self.platform_constraints, field="platform_constraint"),
        )
        object.__setattr__(self, "change_id", _optional_text(self.change_id))
        object.__setattr__(self, "work_id", _optional_text(self.work_id))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class DependencyArtifact:
    artifact_id: str
    package_name: str
    package_version: str
    filename: str
    distribution_kind: DistributionKind
    size_bytes: int
    sha256: str
    source_id: str
    platform_tags: tuple[str, ...] = ()
    provenance_id: str | None = None
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_id",
            _required_text(self.artifact_id, field="artifact_id"),
        )
        object.__setattr__(
            self,
            "package_name",
            _token(self.package_name, field="package_name"),
        )
        object.__setattr__(
            self,
            "package_version",
            _required_text(self.package_version, field="package_version"),
        )
        object.__setattr__(
            self,
            "filename",
            _required_text(self.filename, field="filename"),
        )
        if not isinstance(self.distribution_kind, DistributionKind):
            raise TypeError("distribution_kind must be a DistributionKind")
        object.__setattr__(
            self,
            "size_bytes",
            _non_negative_int(self.size_bytes, field="size_bytes"),
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, field="sha256"))
        object.__setattr__(
            self,
            "source_id",
            _token(self.source_id, field="source_id"),
        )
        object.__setattr__(
            self,
            "platform_tags",
            _tokens(self.platform_tags, field="platform_tag"),
        )
        object.__setattr__(self, "provenance_id", _optional_text(self.provenance_id))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    provenance_id: str
    artifact_id: str
    source_id: str
    resolver_id: str
    resolver_version: str
    resolver_digest: str
    artifact_sha256: str
    attestation_status: AttestationStatus
    verification_status: VerificationStatus
    attestation_refs: tuple[str, ...] = ()
    publisher_identity: str | None = None
    slsa_refs: tuple[str, ...] = ()
    sbom_refs: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        for field_name in ("provenance_id", "artifact_id", "resolver_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "source_id",
            _token(self.source_id, field="source_id"),
        )
        object.__setattr__(
            self,
            "resolver_id",
            _token(self.resolver_id, field="resolver_id"),
        )
        object.__setattr__(
            self,
            "resolver_digest",
            _sha256(self.resolver_digest, field="resolver_digest"),
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _sha256(self.artifact_sha256, field="artifact_sha256"),
        )
        if not isinstance(self.attestation_status, AttestationStatus):
            raise TypeError("attestation_status must be an AttestationStatus")
        if not isinstance(self.verification_status, VerificationStatus):
            raise TypeError("verification_status must be a VerificationStatus")
        object.__setattr__(
            self,
            "attestation_refs",
            _texts(self.attestation_refs, field="attestation_ref"),
        )
        object.__setattr__(
            self,
            "publisher_identity",
            _optional_text(self.publisher_identity),
        )
        object.__setattr__(
            self,
            "slsa_refs",
            _texts(self.slsa_refs, field="slsa_ref"),
        )
        object.__setattr__(
            self,
            "sbom_refs",
            _texts(self.sbom_refs, field="sbom_ref"),
        )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class SecretDescriptor:
    secret_id: str
    kind: str
    service: str
    allowed_consumers: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    lifecycle_state: SecretLifecycleState
    version: int
    created_at_epoch: float
    updated_at_epoch: float
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "secret_id",
            _required_text(self.secret_id, field="secret_id"),
        )
        object.__setattr__(self, "kind", _token(self.kind, field="kind"))
        object.__setattr__(self, "service", _token(self.service, field="service"))
        object.__setattr__(
            self,
            "allowed_consumers",
            _tokens(
                self.allowed_consumers,
                field="allowed_consumer",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "allowed_scopes",
            _tokens(
                self.allowed_scopes,
                field="allowed_scope",
                required=True,
            ),
        )
        if not isinstance(self.lifecycle_state, SecretLifecycleState):
            raise TypeError("lifecycle_state must be a SecretLifecycleState")
        object.__setattr__(
            self,
            "version",
            _positive_int(self.version, field="version"),
        )
        created = _epoch(self.created_at_epoch, field="created_at_epoch")
        updated = _epoch(self.updated_at_epoch, field="updated_at_epoch")
        if updated < created:
            raise ValueError("updated_at_epoch cannot precede created_at_epoch")
        object.__setattr__(self, "created_at_epoch", created)
        object.__setattr__(self, "updated_at_epoch", updated)
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class SecretLease:
    lease_id: str
    secret_id: str
    secret_version: int
    consumer_id: str
    scopes: tuple[str, ...]
    materialization_mode: SecretMaterializationMode
    issued_at_epoch: float
    expires_at_epoch: float
    use_budget: int
    policy_digest: str
    change_id: str | None = None
    work_id: str | None = None
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "lease_id",
            _required_text(self.lease_id, field="lease_id"),
        )
        object.__setattr__(
            self,
            "secret_id",
            _required_text(self.secret_id, field="secret_id"),
        )
        object.__setattr__(
            self,
            "secret_version",
            _positive_int(self.secret_version, field="secret_version"),
        )
        object.__setattr__(
            self,
            "consumer_id",
            _token(self.consumer_id, field="consumer_id"),
        )
        object.__setattr__(
            self,
            "scopes",
            _tokens(self.scopes, field="scope", required=True),
        )
        if not isinstance(self.materialization_mode, SecretMaterializationMode):
            raise TypeError("materialization_mode must be a SecretMaterializationMode")
        issued = _epoch(self.issued_at_epoch, field="issued_at_epoch")
        expires = _epoch(self.expires_at_epoch, field="expires_at_epoch")
        if expires <= issued:
            raise ValueError("expires_at_epoch must be after issued_at_epoch")
        object.__setattr__(self, "issued_at_epoch", issued)
        object.__setattr__(self, "expires_at_epoch", expires)
        object.__setattr__(
            self,
            "use_budget",
            _positive_int(self.use_budget, field="use_budget"),
        )
        object.__setattr__(
            self,
            "policy_digest",
            _sha256(self.policy_digest, field="policy_digest"),
        )
        object.__setattr__(self, "change_id", _optional_text(self.change_id))
        object.__setattr__(self, "work_id", _optional_text(self.work_id))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    manifest_id: str
    manifest_version: int
    capability_id: str
    capability_version: str
    purpose: str
    adapter_id: str
    executor_id: str
    operations: tuple[str, ...]
    dependency_resolution_ids: tuple[str, ...]
    secret_scope_requirements: tuple[str, ...]
    authority_attributes: tuple[str, ...]
    sandbox_profile_ids: tuple[str, ...]
    discovery_scope_ids: tuple[str, ...]
    platform_constraints: tuple[str, ...]
    resource_requirements: tuple[str, ...]
    health_probe_ids: tuple[str, ...]
    verification_contract_ids: tuple[str, ...]
    hardware_acceptance_contract_ids: tuple[str, ...]
    provenance_ids: tuple[str, ...]
    disable_rollback_contract_id: str
    dependency_resolution_digests: tuple[str, ...] = ()
    sandbox_profile_digests: tuple[str, ...] = ()
    discovery_scope_digests: tuple[str, ...] = ()
    provenance_digests: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manifest_id",
            _required_text(self.manifest_id, field="manifest_id"),
        )
        object.__setattr__(
            self,
            "manifest_version",
            _positive_int(self.manifest_version, field="manifest_version"),
        )
        object.__setattr__(
            self,
            "capability_id",
            _token(self.capability_id, field="capability_id"),
        )
        object.__setattr__(
            self,
            "capability_version",
            _required_text(self.capability_version, field="capability_version"),
        )
        object.__setattr__(
            self,
            "purpose",
            _required_text(self.purpose, field="purpose"),
        )
        object.__setattr__(
            self,
            "adapter_id",
            _token(self.adapter_id, field="adapter_id"),
        )
        object.__setattr__(
            self,
            "executor_id",
            _token(self.executor_id, field="executor_id"),
        )
        object.__setattr__(
            self,
            "operations",
            _tokens(self.operations, field="operation", required=True),
        )
        for field_name in (
            "dependency_resolution_ids",
            "secret_scope_requirements",
            "authority_attributes",
            "sandbox_profile_ids",
            "discovery_scope_ids",
            "platform_constraints",
            "resource_requirements",
            "health_probe_ids",
            "verification_contract_ids",
            "hardware_acceptance_contract_ids",
            "provenance_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _tokens(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "disable_rollback_contract_id",
            _token(
                self.disable_rollback_contract_id,
                field="disable_rollback_contract_id",
            ),
        )
        for field_name in (
            "dependency_resolution_digests",
            "sandbox_profile_digests",
            "discovery_scope_digests",
            "provenance_digests",
        ):
            object.__setattr__(
                self,
                field_name,
                _digests(getattr(self, field_name), field=field_name),
            )
        bindings = (
            (
                "dependency_resolution_ids",
                "dependency_resolution_digests",
            ),
            ("sandbox_profile_ids", "sandbox_profile_digests"),
            ("discovery_scope_ids", "discovery_scope_digests"),
            ("provenance_ids", "provenance_digests"),
        )
        for ids_field, digests_field in bindings:
            if len(getattr(self, ids_field)) != len(getattr(self, digests_field)):
                raise ValueError(
                    f"{ids_field} and {digests_field} must have equal length"
                )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class DiscoveryScope:
    scope_id: str
    adapter_id: str
    protocol: str
    allowed_service_types: tuple[str, ...]
    allowed_device_types: tuple[str, ...]
    local_interface: str | None = None
    local_domain: str | None = None
    target_hints: tuple[str, ...] = ()
    timeout_seconds: float = 5.0
    max_results: int = 16
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, field="scope_id"),
        )
        object.__setattr__(
            self,
            "adapter_id",
            _token(self.adapter_id, field="adapter_id"),
        )
        object.__setattr__(self, "protocol", _token(self.protocol, field="protocol"))
        services = _tokens(
            self.allowed_service_types,
            field="allowed_service_type",
        )
        devices = _tokens(
            self.allowed_device_types,
            field="allowed_device_type",
        )
        if not services and not devices:
            raise ValueError(
                "discovery scope requires an allowed service or device type"
            )
        _reject_wildcards(services, field="allowed_service_types")
        _reject_wildcards(devices, field="allowed_device_types")
        object.__setattr__(self, "allowed_service_types", services)
        object.__setattr__(self, "allowed_device_types", devices)
        interface = _optional_text(self.local_interface)
        domain = _optional_text(self.local_domain)
        if interface in {"*", "0.0.0.0/0", "::/0"} or domain == "*":
            raise ValueError("discovery scope cannot use an unbounded interface/domain")
        object.__setattr__(self, "local_interface", interface)
        object.__setattr__(self, "local_domain", domain)
        hints = _texts(
            self.target_hints,
            field="target_hint",
            limit=MAX_DISCOVERY_HINTS,
        )
        _reject_wildcards(
            tuple(item.casefold() for item in hints),
            field="target_hints",
        )
        object.__setattr__(self, "target_hints", hints)
        timeout = _positive_float(self.timeout_seconds, field="timeout_seconds")
        if timeout > MAX_DISCOVERY_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds exceeds Phase-5 discovery bound")
        object.__setattr__(self, "timeout_seconds", timeout)
        results = _positive_int(self.max_results, field="max_results")
        if results > MAX_DISCOVERY_RESULTS:
            raise ValueError("max_results exceeds Phase-5 discovery bound")
        object.__setattr__(self, "max_results", results)
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class DiscoveryObservation:
    observation_id: str
    scope_id: str
    scope_digest: str
    adapter_id: str
    adapter_version: str
    stable_identity: str
    endpoints: tuple[str, ...]
    observed_at_epoch: float
    expires_at_epoch: float
    evidence_digest: str
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "scope_id",
            "adapter_version",
            "stable_identity",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "scope_digest",
            _sha256(self.scope_digest, field="scope_digest"),
        )
        object.__setattr__(
            self,
            "adapter_id",
            _token(self.adapter_id, field="adapter_id"),
        )
        object.__setattr__(
            self,
            "endpoints",
            _texts(self.endpoints, field="endpoint", required=True),
        )
        observed = _epoch(self.observed_at_epoch, field="observed_at_epoch")
        expires = _epoch(self.expires_at_epoch, field="expires_at_epoch")
        if expires <= observed:
            raise ValueError("expires_at_epoch must be after observed_at_epoch")
        object.__setattr__(self, "observed_at_epoch", observed)
        object.__setattr__(self, "expires_at_epoch", expires)
        object.__setattr__(
            self,
            "evidence_digest",
            _sha256(self.evidence_digest, field="evidence_digest"),
        )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    profile_id: str
    profile_version: int
    entrypoint_id: str
    network_mode: SandboxNetworkMode
    filesystem_mode: SandboxFilesystemMode
    mount_policy_ids: tuple[str, ...]
    dropped_capabilities: tuple[str, ...]
    no_new_privileges: bool
    cpu_limit: float
    memory_limit_mb: int
    pid_limit: int
    timeout_seconds: float
    environment_allowlist: tuple[str, ...]
    allowed_secret_scopes: tuple[str, ...]
    output_policy_ids: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            _token(self.profile_id, field="profile_id"),
        )
        object.__setattr__(
            self,
            "profile_version",
            _positive_int(self.profile_version, field="profile_version"),
        )
        object.__setattr__(
            self,
            "entrypoint_id",
            _token(self.entrypoint_id, field="entrypoint_id"),
        )
        if not isinstance(self.network_mode, SandboxNetworkMode):
            raise TypeError("network_mode must be a SandboxNetworkMode")
        if not isinstance(self.filesystem_mode, SandboxFilesystemMode):
            raise TypeError("filesystem_mode must be a SandboxFilesystemMode")
        object.__setattr__(
            self,
            "mount_policy_ids",
            _tokens(self.mount_policy_ids, field="mount_policy_id"),
        )
        object.__setattr__(
            self,
            "dropped_capabilities",
            _tokens(
                self.dropped_capabilities,
                field="dropped_capability",
                required=True,
            ),
        )
        if not isinstance(self.no_new_privileges, bool):
            raise TypeError("no_new_privileges must be a bool")
        if not self.no_new_privileges:
            raise ValueError("Phase-5 v1 sandbox profiles require no_new_privileges")
        object.__setattr__(
            self,
            "cpu_limit",
            _positive_float(self.cpu_limit, field="cpu_limit"),
        )
        object.__setattr__(
            self,
            "memory_limit_mb",
            _positive_int(self.memory_limit_mb, field="memory_limit_mb"),
        )
        object.__setattr__(
            self,
            "pid_limit",
            _positive_int(self.pid_limit, field="pid_limit"),
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            _positive_float(self.timeout_seconds, field="timeout_seconds"),
        )
        object.__setattr__(
            self,
            "environment_allowlist",
            _tokens(self.environment_allowlist, field="environment_variable"),
        )
        object.__setattr__(
            self,
            "allowed_secret_scopes",
            _tokens(self.allowed_secret_scopes, field="allowed_secret_scope"),
        )
        object.__setattr__(
            self,
            "output_policy_ids",
            _tokens(self.output_policy_ids, field="output_policy_id"),
        )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class HardwareAcceptanceRequest:
    request_id: str
    change_id: str
    manifest_id: str
    manifest_digest: str
    device_identity: str
    operation: str
    expected_observation: str
    required_automated_evidence_ids: tuple[str, ...]
    created_at_epoch: float
    expires_at_epoch: float
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "change_id",
            "manifest_id",
            "device_identity",
            "expected_observation",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "manifest_digest",
            _sha256(self.manifest_digest, field="manifest_digest"),
        )
        object.__setattr__(
            self,
            "operation",
            _token(self.operation, field="operation"),
        )
        object.__setattr__(
            self,
            "required_automated_evidence_ids",
            _texts(
                self.required_automated_evidence_ids,
                field="required_automated_evidence_id",
            ),
        )
        created = _epoch(self.created_at_epoch, field="created_at_epoch")
        expires = _epoch(self.expires_at_epoch, field="expires_at_epoch")
        if expires <= created:
            raise ValueError("expires_at_epoch must be after created_at_epoch")
        object.__setattr__(self, "created_at_epoch", created)
        object.__setattr__(self, "expires_at_epoch", expires)
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))


@dataclass(frozen=True, slots=True)
class HardwareAcceptanceEvidence:
    evidence_id: str
    request_id: str
    request_digest: str
    verdict: HardwareAcceptanceVerdict
    observed_at_epoch: float
    owner_observation_ref: str | None = None
    telemetry_refs: tuple[str, ...] = ()
    verifier_refs: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION_V1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _required_text(self.evidence_id, field="evidence_id"),
        )
        object.__setattr__(
            self,
            "request_id",
            _required_text(self.request_id, field="request_id"),
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256(self.request_digest, field="request_digest"),
        )
        if not isinstance(self.verdict, HardwareAcceptanceVerdict):
            raise TypeError("verdict must be a HardwareAcceptanceVerdict")
        object.__setattr__(
            self,
            "observed_at_epoch",
            _epoch(self.observed_at_epoch, field="observed_at_epoch"),
        )
        object.__setattr__(
            self,
            "owner_observation_ref",
            _optional_text(self.owner_observation_ref),
        )
        object.__setattr__(
            self,
            "telemetry_refs",
            _texts(self.telemetry_refs, field="telemetry_ref"),
        )
        object.__setattr__(
            self,
            "verifier_refs",
            _texts(self.verifier_refs, field="verifier_ref"),
        )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
