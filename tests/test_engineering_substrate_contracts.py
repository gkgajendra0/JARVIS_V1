from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

import jarvis.engineering_substrate as substrate

SHA_A = "a" * 64
SHA_B = "b" * 64


def _requirement(**overrides: object) -> substrate.DependencyRequirement:
    values: dict[str, object] = {
        "requirement_id": "requirement-1",
        "ecosystem": substrate.DependencyEcosystem.PYTHON,
        "package_name": "Example-Package",
        "version_constraint": "==1.2.3",
        "purpose": "candidate verification",
        "registered_source_ids": ("PYPI.PUBLIC.V1",),
        "platform_constraints": ("win_amd64",),
        "change_id": "change-1",
        "work_id": "work-1",
    }
    values.update(overrides)
    return substrate.DependencyRequirement(**values)  # type: ignore[arg-type]


def test_contracts_normalize_and_remain_immutable() -> None:
    requirement = _requirement()

    assert requirement.package_name == "example-package"
    assert requirement.registered_source_ids == ("pypi.public.v1",)
    assert requirement.platform_constraints == ("win_amd64",)

    with pytest.raises(FrozenInstanceError):
        requirement.package_name = "changed"  # type: ignore[misc]


def test_phase5_v1_source_build_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="source builds are denied"):
        _requirement(source_build_policy="allow")


def test_canonical_digest_is_stable_after_normalization() -> None:
    left = _requirement(
        package_name=" Example-Package ",
        registered_source_ids=("PYPI.PUBLIC.V1",),
    )
    right = _requirement(
        package_name="example-package",
        registered_source_ids=("pypi.public.v1",),
    )

    assert substrate.canonical_digest(left) == substrate.canonical_digest(right)
    assert substrate.canonical_bytes(left) == substrate.canonical_bytes(right)


def test_schema_registry_is_exact_and_fail_closed() -> None:
    registry = substrate.default_contract_schema_registry()

    registration = registry.require("Dependency_Requirement", 1)
    assert registration.contract_name == "dependencyrequirement"

    with pytest.raises(substrate.UnknownSchemaVersionError):
        registry.require("dependency_requirement", 2)

    with pytest.raises(substrate.DuplicateSchemaRegistrationError):
        registry.register(registration)


def test_model_facing_secret_contracts_cannot_contain_plaintext_fields() -> None:
    names = {item.name for item in fields(substrate.SecretDescriptor)}
    names.update(item.name for item in fields(substrate.SecretLease))

    assert {
        "secret",
        "secret_value",
        "value",
        "plaintext",
        "password",
        "api_key",
        "token",
        "credential",
        "dpapi_blob",
    }.isdisjoint(names)


def test_dangerous_raw_execution_fields_are_structurally_absent() -> None:
    model_fields = set()
    for contract_type in (
        substrate.CapabilityManifest,
        substrate.SandboxProfile,
        substrate.DiscoveryScope,
        substrate.DependencyRequirement,
    ):
        model_fields.update(item.name for item in fields(contract_type))

    assert {
        "shell",
        "command",
        "argv",
        "docker_args",
        "docker_options",
        "port_range",
        "ports",
        "index_url",
        "extra_index_url",
    }.isdisjoint(model_fields)


def test_discovery_scope_requires_narrow_bounded_scope() -> None:
    with pytest.raises(ValueError, match="requires an allowed service or device"):
        substrate.DiscoveryScope(
            scope_id="scope-1",
            adapter_id="mdns_dns_sd.v1",
            protocol="mdns",
            allowed_service_types=(),
            allowed_device_types=(),
        )

    with pytest.raises(ValueError, match="unbounded wildcard"):
        substrate.DiscoveryScope(
            scope_id="scope-2",
            adapter_id="mdns_dns_sd.v1",
            protocol="mdns",
            allowed_service_types=("*",),
            allowed_device_types=(),
        )

    with pytest.raises(ValueError, match="timeout_seconds exceeds"):
        substrate.DiscoveryScope(
            scope_id="scope-3",
            adapter_id="mdns_dns_sd.v1",
            protocol="mdns",
            allowed_service_types=("_http._tcp.local.",),
            allowed_device_types=(),
            timeout_seconds=31,
        )


def test_secret_lease_is_scope_bound_and_time_bounded() -> None:
    lease = substrate.SecretLease(
        lease_id="lease-1",
        secret_id="secret-1",
        secret_version=2,
        consumer_id="dependency.uv.private-index",
        scopes=("read_index",),
        materialization_mode=substrate.SecretMaterializationMode.CHILD_ENV,
        issued_at_epoch=100,
        expires_at_epoch=110,
        use_budget=1,
        policy_digest=SHA_A,
        change_id="change-1",
    )
    assert lease.scopes == ("read_index",)
    assert lease.use_budget == 1

    with pytest.raises(ValueError, match="after issued"):
        substrate.SecretLease(
            lease_id="lease-bad",
            secret_id="secret-1",
            secret_version=2,
            consumer_id="consumer",
            scopes=("read",),
            materialization_mode=substrate.SecretMaterializationMode.CHILD_ENV,
            issued_at_epoch=100,
            expires_at_epoch=100,
            use_budget=1,
            policy_digest=SHA_A,
        )


def test_dependency_and_provenance_contracts_bind_content_digests() -> None:
    artifact = substrate.DependencyArtifact(
        artifact_id="artifact-1",
        package_name="Example",
        package_version="1.2.3",
        filename="example-1.2.3-py3-none-any.whl",
        distribution_kind=substrate.DistributionKind.WHEEL,
        size_bytes=1234,
        sha256=SHA_A,
        source_id="pypi.public.v1",
        platform_tags=("py3-none-any",),
    )
    provenance = substrate.ArtifactProvenance(
        provenance_id="provenance-1",
        artifact_id=artifact.artifact_id,
        source_id=artifact.source_id,
        resolver_id="uv",
        resolver_version="reviewed",
        resolver_digest=SHA_B,
        artifact_sha256=artifact.sha256,
        attestation_status=substrate.AttestationStatus.NOT_AVAILABLE,
        verification_status=substrate.VerificationStatus.PENDING,
    )

    assert artifact.sha256 == SHA_A
    assert provenance.artifact_sha256 == artifact.sha256


def test_hardware_acceptance_is_digest_bound_evidence_only() -> None:
    request = substrate.HardwareAcceptanceRequest(
        request_id="hardware-request-1",
        change_id="change-1",
        manifest_id="manifest-1",
        manifest_digest=SHA_A,
        device_identity="device:test",
        operation="observe_indicator",
        expected_observation="indicator becomes visible",
        required_automated_evidence_ids=("verification-1",),
        created_at_epoch=100,
        expires_at_epoch=200,
    )
    evidence = substrate.HardwareAcceptanceEvidence(
        evidence_id="hardware-evidence-1",
        request_id=request.request_id,
        request_digest=substrate.canonical_digest(request),
        verdict=substrate.HardwareAcceptanceVerdict.INCONCLUSIVE,
        observed_at_epoch=150,
        owner_observation_ref="trusted-local:observation-1",
        verifier_refs=("verification-1",),
    )

    assert evidence.request_digest == substrate.canonical_digest(request)
    assert evidence.verdict is substrate.HardwareAcceptanceVerdict.INCONCLUSIVE
