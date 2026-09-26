"""Digest-bound CapabilityManifest validation without dynamic execution authority."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields

from jarvis.authority import ActionAttributes, ActionScope, RiskClass, RiskClassifier
from jarvis.engineering_substrate.canonical import canonical_bytes, canonical_digest
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.engineering_substrate.registry import (
    ContractSchemaRegistry,
    default_contract_schema_registry,
)


class CapabilityManifestError(RuntimeError):
    """Base error for manifest admission or activation validation."""


class DuplicateCapabilityManifestError(CapabilityManifestError):
    """The same immutable manifest identity/version is already registered."""


class UnknownManifestReferenceError(CapabilityManifestError):
    """A manifest references an unregistered trusted object."""


class ManifestDigestMismatchError(CapabilityManifestError):
    """A manifest-bound digest differs from the current registered object digest."""


class ManifestAuthorityFloorError(CapabilityManifestError):
    """A manifest attempts to declare less Authority risk than a trusted operation."""


class ManifestActivationError(CapabilityManifestError):
    """A manifest fails trusted executor/adapter activation checks."""


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _tokens(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_token(item, field=field) for item in values))


def _sha256(value: object, *, field: str) -> str:
    normalized = _token(value, field=field)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


@dataclass(frozen=True, order=True, slots=True)
class DigestRegistration:
    reference_id: str
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reference_id",
            _token(self.reference_id, field="reference_id"),
        )
        object.__setattr__(
            self,
            "digest",
            _sha256(self.digest, field="digest"),
        )


@dataclass(frozen=True, slots=True)
class DependencyResolutionRegistration:
    resolution_id: str
    digest: str
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolution_id",
            _token(self.resolution_id, field="resolution_id"),
        )
        object.__setattr__(self, "digest", _sha256(self.digest, field="digest"))
        object.__setattr__(
            self,
            "provenance_ids",
            _tokens(self.provenance_ids, field="provenance_id"),
        )


@dataclass(frozen=True, slots=True)
class TrustedExecutorRegistration:
    executor_id: str
    adapter_ids: tuple[str, ...]
    operations: tuple[str, ...]
    authority_attribute_floor: tuple[str, ...]
    allowed_secret_scopes: tuple[str, ...]
    sandbox_profile_ids: tuple[str, ...]
    physical_effect_operations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "executor_id",
            _token(self.executor_id, field="executor_id"),
        )
        object.__setattr__(
            self,
            "adapter_ids",
            _tokens(self.adapter_ids, field="adapter_id"),
        )
        object.__setattr__(
            self,
            "operations",
            _tokens(self.operations, field="operation"),
        )
        object.__setattr__(
            self,
            "authority_attribute_floor",
            _tokens(
                self.authority_attribute_floor,
                field="authority_attribute_floor",
            ),
        )
        object.__setattr__(
            self,
            "allowed_secret_scopes",
            _tokens(self.allowed_secret_scopes, field="allowed_secret_scope"),
        )
        object.__setattr__(
            self,
            "sandbox_profile_ids",
            _tokens(self.sandbox_profile_ids, field="sandbox_profile_id"),
        )
        physical = _tokens(
            self.physical_effect_operations,
            field="physical_effect_operation",
        )
        if not set(physical).issubset(set(self.operations)):
            raise ValueError("physical effect operations must be registered operations")
        object.__setattr__(self, "physical_effect_operations", physical)


@dataclass(frozen=True, slots=True)
class TrustedAdapterRegistration:
    adapter_id: str
    operations: tuple[str, ...]
    discovery_scope_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "adapter_id",
            _token(self.adapter_id, field="adapter_id"),
        )
        object.__setattr__(
            self,
            "operations",
            _tokens(self.operations, field="operation"),
        )
        object.__setattr__(
            self,
            "discovery_scope_ids",
            _tokens(self.discovery_scope_ids, field="discovery_scope_id"),
        )


@dataclass(frozen=True, slots=True)
class ManifestReferenceCatalog:
    dependency_resolutions: tuple[DependencyResolutionRegistration, ...] = ()
    provenance: tuple[DigestRegistration, ...] = ()
    sandbox_profiles: tuple[DigestRegistration, ...] = ()
    discovery_scopes: tuple[DigestRegistration, ...] = ()
    verification_contract_ids: tuple[str, ...] = ()
    hardware_acceptance_contract_ids: tuple[str, ...] = ()
    disable_rollback_contract_ids: tuple[str, ...] = ()
    health_probe_ids: tuple[str, ...] = ()
    resource_requirement_ids: tuple[str, ...] = ()
    platform_constraint_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "verification_contract_ids",
            "hardware_acceptance_contract_ids",
            "disable_rollback_contract_ids",
            "health_probe_ids",
            "resource_requirement_ids",
            "platform_constraint_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _tokens(getattr(self, field_name), field=field_name),
            )
        self.dependency_map()
        self.provenance_map()
        self.sandbox_map()
        self.discovery_map()

    def _digest_map(
        self,
        registrations: tuple[DigestRegistration, ...],
        *,
        kind: str,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for registration in registrations:
            if registration.reference_id in result:
                raise ValueError(
                    f"duplicate {kind} reference: {registration.reference_id}"
                )
            result[registration.reference_id] = registration.digest
        return result

    def dependency_map(self) -> dict[str, DependencyResolutionRegistration]:
        result: dict[str, DependencyResolutionRegistration] = {}
        for registration in self.dependency_resolutions:
            if registration.resolution_id in result:
                raise ValueError(
                    "duplicate dependency resolution reference: "
                    f"{registration.resolution_id}"
                )
            result[registration.resolution_id] = registration
        return result

    def provenance_map(self) -> dict[str, str]:
        return self._digest_map(self.provenance, kind="provenance")

    def sandbox_map(self) -> dict[str, str]:
        return self._digest_map(self.sandbox_profiles, kind="sandbox profile")

    def discovery_map(self) -> dict[str, str]:
        return self._digest_map(self.discovery_scopes, kind="discovery scope")


@dataclass(frozen=True, slots=True)
class RegisteredCapabilityManifest:
    manifest: CapabilityManifest
    manifest_digest: str
    authority_risk_floor: RiskClass


_AUTHORITY_BOOLEAN_FIELDS = frozenset(
    item.name for item in fields(ActionAttributes) if item.name != "scope"
)


def _authority_attributes(names: tuple[str, ...]) -> ActionAttributes:
    unknown = set(names) - _AUTHORITY_BOOLEAN_FIELDS
    if unknown:
        raise ManifestAuthorityFloorError(
            "unknown Authority attribute(s): " + ", ".join(sorted(unknown))
        )
    kwargs = {name: True for name in names}
    kwargs["scope"] = ActionScope.SINGLE
    return ActionAttributes(**kwargs)


def _required_risk(
    registrations: tuple[TrustedExecutorRegistration, ...],
) -> RiskClass:
    classifier = RiskClassifier()
    required: set[str] = set()
    for registration in registrations:
        required.update(registration.authority_attribute_floor)
    return classifier.classify(
        _authority_attributes(tuple(sorted(required)))
    ).risk_class


class CapabilityManifestRegistry:
    """Exact, declarative manifest admission. It never imports or executes capability code."""

    def __init__(
        self,
        *,
        executors: Iterable[TrustedExecutorRegistration] = (),
        adapters: Iterable[TrustedAdapterRegistration] = (),
        references: ManifestReferenceCatalog | None = None,
        schemas: ContractSchemaRegistry | None = None,
    ) -> None:
        self._executors: dict[str, TrustedExecutorRegistration] = {}
        self._adapters: dict[str, TrustedAdapterRegistration] = {}
        self._manifests: dict[tuple[str, int], RegisteredCapabilityManifest] = {}
        self._references = references or ManifestReferenceCatalog()
        self._schemas = schemas or default_contract_schema_registry()
        for executor in executors:
            if executor.executor_id in self._executors:
                raise ValueError(f"duplicate executor: {executor.executor_id}")
            self._executors[executor.executor_id] = executor
        for adapter in adapters:
            if adapter.adapter_id in self._adapters:
                raise ValueError(f"duplicate adapter: {adapter.adapter_id}")
            self._adapters[adapter.adapter_id] = adapter

    def _executor(self, executor_id: str) -> TrustedExecutorRegistration:
        try:
            return self._executors[executor_id]
        except KeyError as exc:
            raise UnknownManifestReferenceError(
                f"unknown trusted executor: {executor_id}"
            ) from exc

    def _adapter(self, adapter_id: str) -> TrustedAdapterRegistration:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise UnknownManifestReferenceError(
                f"unknown trusted adapter: {adapter_id}"
            ) from exc

    @staticmethod
    def _validate_digest_bindings(
        *,
        ids: tuple[str, ...],
        digests: tuple[str, ...],
        registered: dict[str, str],
        kind: str,
    ) -> None:
        for reference_id, expected_digest in zip(ids, digests, strict=True):
            try:
                current_digest = registered[reference_id]
            except KeyError as exc:
                raise UnknownManifestReferenceError(
                    f"unknown {kind}: {reference_id}"
                ) from exc
            if current_digest != expected_digest:
                raise ManifestDigestMismatchError(
                    f"{kind} digest mismatch for {reference_id}"
                )

    def _validate_dependencies(self, manifest: CapabilityManifest) -> None:
        dependencies = self._references.dependency_map()
        provenance = self._references.provenance_map()
        manifest_provenance = set(manifest.provenance_ids)

        for resolution_id, expected_digest in zip(
            manifest.dependency_resolution_ids,
            manifest.dependency_resolution_digests,
            strict=True,
        ):
            try:
                registered = dependencies[resolution_id]
            except KeyError as exc:
                raise UnknownManifestReferenceError(
                    f"unknown dependency resolution: {resolution_id}"
                ) from exc
            if registered.digest != expected_digest:
                raise ManifestDigestMismatchError(
                    f"dependency resolution digest mismatch for {resolution_id}"
                )
            missing_provenance = set(registered.provenance_ids) - manifest_provenance
            if missing_provenance:
                raise ManifestActivationError(
                    "dependency resolution is missing required provenance references: "
                    + ", ".join(sorted(missing_provenance))
                )

        self._validate_digest_bindings(
            ids=manifest.provenance_ids,
            digests=manifest.provenance_digests,
            registered=provenance,
            kind="provenance",
        )

    def _validate_authority(
        self,
        manifest: CapabilityManifest,
        executor: TrustedExecutorRegistration,
    ) -> RiskClass:
        manifest_attributes = set(manifest.authority_attributes)
        required = set(executor.authority_attribute_floor)
        if not required.issubset(manifest_attributes):
            missing = required - manifest_attributes
            raise ManifestAuthorityFloorError(
                "manifest lowers deterministic Authority floor; missing: "
                + ", ".join(sorted(missing))
            )

        classifier = RiskClassifier()
        manifest_risk = classifier.classify(
            _authority_attributes(tuple(sorted(manifest_attributes)))
        ).risk_class
        executor_risk = _required_risk((executor,))
        if manifest_risk < executor_risk:
            raise ManifestAuthorityFloorError(
                "manifest risk classification is below executor floor"
            )
        return manifest_risk

    def validate_for_activation(
        self,
        manifest: CapabilityManifest,
    ) -> RegisteredCapabilityManifest:
        self._schemas.require("capability_manifest", manifest.schema_version)
        if manifest.manifest_version != 1:
            raise ManifestActivationError(
                f"unsupported manifest version: {manifest.manifest_version}"
            )

        executor = self._executor(manifest.executor_id)
        adapter = self._adapter(manifest.adapter_id)

        if manifest.adapter_id not in executor.adapter_ids:
            raise ManifestActivationError(
                "executor is not registered for the manifest adapter"
            )

        operations = set(manifest.operations)
        if not operations.issubset(set(executor.operations)):
            raise ManifestActivationError(
                "manifest requests an operation not registered by executor"
            )
        if not operations.issubset(set(adapter.operations)):
            raise ManifestActivationError(
                "manifest requests an operation not registered by adapter"
            )

        if not set(manifest.secret_scope_requirements).issubset(
            set(executor.allowed_secret_scopes)
        ):
            raise ManifestActivationError(
                "manifest secret scope exceeds executor allowlist"
            )

        if not set(manifest.sandbox_profile_ids).issubset(
            set(executor.sandbox_profile_ids)
        ):
            raise ManifestActivationError(
                "manifest sandbox profile exceeds executor allowlist"
            )

        if not set(manifest.discovery_scope_ids).issubset(
            set(adapter.discovery_scope_ids)
        ):
            raise ManifestActivationError(
                "manifest discovery scope exceeds adapter allowlist"
            )

        self._validate_dependencies(manifest)
        self._validate_digest_bindings(
            ids=manifest.sandbox_profile_ids,
            digests=manifest.sandbox_profile_digests,
            registered=self._references.sandbox_map(),
            kind="sandbox profile",
        )
        self._validate_digest_bindings(
            ids=manifest.discovery_scope_ids,
            digests=manifest.discovery_scope_digests,
            registered=self._references.discovery_map(),
            kind="discovery scope",
        )

        verification = set(self._references.verification_contract_ids)
        if not manifest.verification_contract_ids:
            raise ManifestActivationError(
                "manifest requires at least one verification contract"
            )
        unknown_verification = set(manifest.verification_contract_ids) - verification
        if unknown_verification:
            raise UnknownManifestReferenceError(
                "unknown verification contract(s): "
                + ", ".join(sorted(unknown_verification))
            )

        rollback = set(self._references.disable_rollback_contract_ids)
        if manifest.disable_rollback_contract_id not in rollback:
            raise UnknownManifestReferenceError(
                "unknown disable/rollback contract: "
                f"{manifest.disable_rollback_contract_id}"
            )

        hardware = set(self._references.hardware_acceptance_contract_ids)
        unknown_hardware = set(manifest.hardware_acceptance_contract_ids) - hardware
        if unknown_hardware:
            raise UnknownManifestReferenceError(
                "unknown hardware acceptance contract(s): "
                + ", ".join(sorted(unknown_hardware))
            )
        if operations & set(executor.physical_effect_operations):
            if not manifest.hardware_acceptance_contract_ids:
                raise ManifestActivationError(
                    "physical-effect operation requires hardware acceptance contract"
                )

        for values, registered, kind in (
            (
                manifest.health_probe_ids,
                set(self._references.health_probe_ids),
                "health probe",
            ),
            (
                manifest.resource_requirements,
                set(self._references.resource_requirement_ids),
                "resource requirement",
            ),
            (
                manifest.platform_constraints,
                set(self._references.platform_constraint_ids),
                "platform constraint",
            ),
        ):
            unknown = set(values) - registered
            if unknown:
                raise UnknownManifestReferenceError(
                    f"unknown {kind}(s): " + ", ".join(sorted(unknown))
                )

        risk_floor = self._validate_authority(manifest, executor)
        return RegisteredCapabilityManifest(
            manifest=manifest,
            manifest_digest=canonical_digest(manifest),
            authority_risk_floor=risk_floor,
        )

    def register(
        self,
        manifest: CapabilityManifest,
    ) -> RegisteredCapabilityManifest:
        validated = self.validate_for_activation(manifest)
        key = (manifest.manifest_id, manifest.manifest_version)
        if key in self._manifests:
            raise DuplicateCapabilityManifestError(
                f"manifest already registered: {manifest.manifest_id}.v"
                f"{manifest.manifest_version}"
            )
        self._manifests[key] = validated
        return validated

    def require(
        self,
        manifest_id: str,
        manifest_version: int,
    ) -> RegisteredCapabilityManifest:
        key = (_token(manifest_id, field="manifest_id"), int(manifest_version))
        try:
            return self._manifests[key]
        except KeyError as exc:
            raise UnknownManifestReferenceError(
                f"unknown capability manifest: {key[0]}.v{key[1]}"
            ) from exc


def capability_manifest_json_schema() -> dict[str, object]:
    """Return deterministic JSON Schema Draft 2020-12 for manifest v1."""

    token_array = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "uniqueItems": True,
        "maxItems": 64,
    }
    digest_array = {
        "type": "array",
        "items": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "maxItems": 64,
    }
    properties: dict[str, object] = {
        "manifest_id": {"type": "string", "minLength": 1},
        "manifest_version": {"const": 1},
        "capability_id": {"type": "string", "minLength": 1},
        "capability_version": {"type": "string", "minLength": 1},
        "purpose": {"type": "string", "minLength": 1},
        "adapter_id": {"type": "string", "minLength": 1},
        "executor_id": {"type": "string", "minLength": 1},
        "operations": token_array,
        "dependency_resolution_ids": token_array,
        "secret_scope_requirements": token_array,
        "authority_attributes": token_array,
        "sandbox_profile_ids": token_array,
        "discovery_scope_ids": token_array,
        "platform_constraints": token_array,
        "resource_requirements": token_array,
        "health_probe_ids": token_array,
        "verification_contract_ids": token_array,
        "hardware_acceptance_contract_ids": token_array,
        "provenance_ids": token_array,
        "disable_rollback_contract_id": {"type": "string", "minLength": 1},
        "dependency_resolution_digests": digest_array,
        "sandbox_profile_digests": digest_array,
        "discovery_scope_digests": digest_array,
        "provenance_digests": digest_array,
        "schema_version": {"const": 1},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://jarvis.local/schema/capability-manifest-v1.json",
        "title": "JARVIS CapabilityManifest v1",
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def capability_manifest_schema_bytes() -> bytes:
    return canonical_bytes(capability_manifest_json_schema())


def capability_manifest_schema_digest() -> str:
    return canonical_digest(capability_manifest_json_schema())
