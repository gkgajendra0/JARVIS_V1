from __future__ import annotations

from dataclasses import fields

import pytest

from jarvis.authority import RiskClass
from jarvis.engineering_substrate import (
    CapabilityManifest,
    ManifestActivationError,
    ManifestAuthorityFloorError,
    ManifestDigestMismatchError,
    UnknownManifestReferenceError,
    canonical_digest,
    canonical_payload,
    default_sandbox_registry,
)
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    DependencyResolutionRegistration,
    DigestRegistration,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
    capability_manifest_json_schema,
    capability_manifest_schema_bytes,
    capability_manifest_schema_digest,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _sandbox_digest() -> str:
    definition = default_sandbox_registry(docker_executable="docker").require(
        "dependency.verify.v1",
        1,
    )
    return canonical_digest(definition.profile)


def _references() -> ManifestReferenceCatalog:
    return ManifestReferenceCatalog(
        dependency_resolutions=(
            DependencyResolutionRegistration(
                resolution_id="dep-resolution-1",
                digest=SHA_A,
                provenance_ids=("provenance-1",),
            ),
        ),
        provenance=(DigestRegistration("provenance-1", SHA_B),),
        sandbox_profiles=(
            DigestRegistration("dependency.verify.v1", _sandbox_digest()),
        ),
        discovery_scopes=(DigestRegistration("device-scope-1", SHA_D),),
        verification_contract_ids=("verify.device.v1",),
        hardware_acceptance_contract_ids=("hardware.observe.v1",),
        disable_rollback_contract_ids=("disable.device.v1",),
        health_probe_ids=("health.device.v1",),
        resource_requirement_ids=("resource.local-network.v1",),
        platform_constraint_ids=("windows-amd64",),
    )


def _registry() -> CapabilityManifestRegistry:
    return CapabilityManifestRegistry(
        executors=(
            TrustedExecutorRegistration(
                executor_id="device.executor.v1",
                adapter_ids=("device.adapter.v1",),
                operations=("set_indicator",),
                authority_attribute_floor=("external_side_effect",),
                allowed_secret_scopes=("device.control",),
                sandbox_profile_ids=("dependency.verify.v1",),
                physical_effect_operations=("set_indicator",),
            ),
        ),
        adapters=(
            TrustedAdapterRegistration(
                adapter_id="device.adapter.v1",
                operations=("set_indicator",),
                discovery_scope_ids=("device-scope-1",),
            ),
        ),
        references=_references(),
    )


def _manifest(**overrides: object) -> CapabilityManifest:
    values: dict[str, object] = {
        "manifest_id": "manifest-device-1",
        "manifest_version": 1,
        "capability_id": "device.indicator",
        "capability_version": "1.0.0",
        "purpose": "Set a harmless test indicator after governed verification.",
        "adapter_id": "device.adapter.v1",
        "executor_id": "device.executor.v1",
        "operations": ("set_indicator",),
        "dependency_resolution_ids": ("dep-resolution-1",),
        "secret_scope_requirements": ("device.control",),
        "authority_attributes": ("external_side_effect",),
        "sandbox_profile_ids": ("dependency.verify.v1",),
        "discovery_scope_ids": ("device-scope-1",),
        "platform_constraints": ("windows-amd64",),
        "resource_requirements": ("resource.local-network.v1",),
        "health_probe_ids": ("health.device.v1",),
        "verification_contract_ids": ("verify.device.v1",),
        "hardware_acceptance_contract_ids": ("hardware.observe.v1",),
        "provenance_ids": ("provenance-1",),
        "disable_rollback_contract_id": "disable.device.v1",
        "dependency_resolution_digests": (SHA_A,),
        "sandbox_profile_digests": (_sandbox_digest(),),
        "discovery_scope_digests": (SHA_D,),
        "provenance_digests": (SHA_B,),
    }
    values.update(overrides)
    return CapabilityManifest(**values)  # type: ignore[arg-type]


def test_trusted_execution_registrations_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="at least one adapter"):
        TrustedExecutorRegistration(
            executor_id="empty.executor.v1",
            adapter_ids=(),
            operations=("run",),
            authority_attribute_floor=(),
            allowed_secret_scopes=(),
            sandbox_profile_ids=(),
        )

    with pytest.raises(ValueError, match="at least one operation"):
        TrustedAdapterRegistration(
            adapter_id="empty.adapter.v1",
            operations=(),
        )


def test_representative_manifest_validates_and_is_digest_bound() -> None:
    manifest = _manifest()
    registered = _registry().register(manifest)

    assert registered.manifest == manifest
    assert registered.manifest_digest == canonical_digest(manifest)
    assert registered.authority_risk_floor is RiskClass.PERSISTENT_OR_EXTERNAL


def test_unknown_manifest_version_is_rejected() -> None:
    with pytest.raises(ManifestActivationError, match="unsupported manifest version"):
        _registry().validate_for_activation(_manifest(manifest_version=2))


def test_unknown_executor_cannot_activate() -> None:
    with pytest.raises(UnknownManifestReferenceError, match="unknown trusted executor"):
        _registry().validate_for_activation(_manifest(executor_id="model.chosen.exe"))


def test_manifest_cannot_reduce_authority_floor() -> None:
    with pytest.raises(ManifestAuthorityFloorError, match="lowers deterministic"):
        _registry().validate_for_activation(_manifest(authority_attributes=()))


def test_dependency_digest_drift_is_rejected() -> None:
    with pytest.raises(
        ManifestDigestMismatchError,
        match="dependency resolution digest mismatch",
    ):
        _registry().validate_for_activation(
            _manifest(dependency_resolution_digests=(SHA_C,))
        )


def test_sandbox_digest_drift_is_rejected() -> None:
    with pytest.raises(ManifestDigestMismatchError, match="sandbox profile digest"):
        _registry().validate_for_activation(_manifest(sandbox_profile_digests=(SHA_C,)))


def test_dependency_requires_its_registered_provenance() -> None:
    with pytest.raises(
        ManifestActivationError,
        match="missing required provenance",
    ):
        _registry().validate_for_activation(
            _manifest(provenance_ids=(), provenance_digests=())
        )


def test_physical_effect_requires_hardware_acceptance_contract() -> None:
    with pytest.raises(
        ManifestActivationError,
        match="requires hardware acceptance",
    ):
        _registry().validate_for_activation(
            _manifest(hardware_acceptance_contract_ids=())
        )


def test_manifest_reference_ids_and_digests_must_be_one_to_one() -> None:
    with pytest.raises(ValueError, match="must have equal length"):
        _manifest(dependency_resolution_digests=())


def test_raw_execution_and_plaintext_secret_fields_are_impossible() -> None:
    field_names = {item.name for item in fields(CapabilityManifest)}
    assert {
        "shell",
        "command",
        "argv",
        "executable",
        "docker_args",
        "secret",
        "secret_value",
        "password",
        "api_key",
        "token",
        "credential",
    }.isdisjoint(field_names)

    schema = capability_manifest_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert schema["additionalProperties"] is False
    for forbidden_name in ("command", "executable", "secret_value", "api_key"):
        assert forbidden_name not in properties
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            _manifest(**{forbidden_name: "must-never-be-accepted"})


def test_schema_is_valid_draft_2020_12_and_deterministic() -> None:
    schema_a = capability_manifest_json_schema()
    schema_b = capability_manifest_json_schema()

    assert schema_a["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema_a["type"] == "object"
    assert schema_a["additionalProperties"] is False
    assert schema_a == schema_b
    assert capability_manifest_schema_bytes() == capability_manifest_schema_bytes()
    assert capability_manifest_schema_digest() == canonical_digest(schema_a)
    assert capability_manifest_schema_digest() == canonical_digest(schema_b)


def test_schema_accepts_canonical_representative_manifest() -> None:
    payload = canonical_payload(_manifest())
    assert isinstance(payload, dict)

    schema = capability_manifest_json_schema()
    required = set(schema["required"])
    properties = set(schema["properties"])
    assert set(payload) == required
    assert set(payload).issubset(properties)
