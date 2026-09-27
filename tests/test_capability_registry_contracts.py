from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from jarvis.capability_registry import (
    CAPABILITY_PACKAGE_SCHEMA_URI_V1,
    CapabilityPackageContractError,
    CapabilityPackageKind,
    CapabilityPackageV1,
    StrictSemVer,
    capability_package_v1_json_schema,
    capability_package_v1_schema_digest,
    parse_capability_package_v1,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "package_id": "Example.Tools",
        "package_version": "1.2.3-alpha.1+build.7",
        "capability_id": "Example.Capability",
        "package_kind": "extension_source",
        "manifest_id": "Manifest.Example",
        "manifest_version": 1,
        "manifest_digest": "A" * 64,
        "runtime_api_id": "jarvis.capability_runtime",
        "runtime_api_version": 1,
        "artifacts": [
            {
                "role": "wheel",
                "sha256": "B" * 64,
                "size_bytes": 42,
                "media_type": "application/octet-stream",
                "provenance_refs": ["PROV.Z", "prov.a"],
            },
            {
                "role": "sbom",
                "sha256": "C" * 64,
                "size_bytes": 7,
                "media_type": "application/vnd.cyclonedx+json",
                "provenance_refs": [],
            },
        ],
        "attestation_refs": ["attestation:z", "attestation:a"],
        "sbom_refs": ["sbom:z", "sbom:a"],
    }


@pytest.mark.parametrize(
    "value",
    [
        "01.0.0",
        "1.01.0",
        "1.0.01",
        "1.0",
        "1.0.0-01",
        "1.0.0-",
        "1.0.0+",
        " 1.0.0",
        "1.0.0 ",
        "v1.0.0",
    ],
)
def test_strict_semver_rejects_invalid_values(value: str) -> None:
    with pytest.raises(CapabilityPackageContractError):
        StrictSemVer.parse(value)


def test_semver_precedence_matches_semver_2_spec_example() -> None:
    ordered = (
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    )

    parsed = tuple(StrictSemVer.parse(item) for item in ordered)
    for left, right in zip(parsed, parsed[1:], strict=True):
        assert left.compare_precedence(right) == -1
        assert right.compare_precedence(left) == 1


def test_semver_build_metadata_does_not_change_precedence() -> None:
    left = StrictSemVer.parse("1.0.0+build.1")
    right = StrictSemVer.parse("1.0.0+build.2")

    assert left.original != right.original
    assert left.compare_precedence(right) == 0


def test_package_contract_normalizes_identity_and_evidence_order() -> None:
    package = parse_capability_package_v1(_payload())

    assert package.package_id == "example.tools"
    assert package.capability_id == "example.capability"
    assert package.manifest_id == "manifest.example"
    assert package.manifest_digest == "a" * 64
    assert package.package_kind is CapabilityPackageKind.EXTENSION_SOURCE
    assert package.attestation_refs == ("attestation:a", "attestation:z")
    assert package.sbom_refs == ("sbom:a", "sbom:z")
    assert tuple(item.role for item in package.artifacts) == ("sbom", "wheel")
    assert package.artifacts[1].provenance_refs == ("prov.a", "prov.z")
    assert package.parsed_version.original == "1.2.3-alpha.1+build.7"


def test_package_digest_is_stable_under_nonsemantic_input_order() -> None:
    first_payload = _payload()
    second_payload = copy.deepcopy(first_payload)
    second_payload["artifacts"] = list(reversed(second_payload["artifacts"]))
    second_payload["attestation_refs"] = list(
        reversed(second_payload["attestation_refs"])
    )
    second_payload["sbom_refs"] = list(reversed(second_payload["sbom_refs"]))

    first = parse_capability_package_v1(first_payload)
    second = parse_capability_package_v1(second_payload)

    assert first.canonical_payload() == second.canonical_payload()
    assert first.digest == second.digest
    assert len(first.digest) == 64


@pytest.mark.parametrize(
    "field",
    [
        "module",
        "import_path",
        "command",
        "argv",
        "executable_path",
        "secret",
    ],
)
def test_package_contract_forbids_unrecognized_execution_or_secret_fields(
    field: str,
) -> None:
    payload = _payload()
    payload[field] = "forbidden"

    with pytest.raises(CapabilityPackageContractError):
        parse_capability_package_v1(payload)


def test_nested_artifact_contract_is_closed() -> None:
    payload = _payload()
    artifact = payload["artifacts"][0]
    artifact["command"] = "python evil.py"

    with pytest.raises(CapabilityPackageContractError):
        parse_capability_package_v1(payload)


def test_unknown_package_schema_version_fails_closed() -> None:
    payload = _payload()
    payload["schema_version"] = 2

    with pytest.raises(CapabilityPackageContractError):
        parse_capability_package_v1(payload)


def test_contract_uses_strict_integer_fields() -> None:
    payload = _payload()
    payload["manifest_version"] = "1"

    with pytest.raises(CapabilityPackageContractError):
        parse_capability_package_v1(payload)


def test_duplicate_artifact_identity_is_rejected() -> None:
    payload = _payload()
    payload["artifacts"].append(copy.deepcopy(payload["artifacts"][0]))

    with pytest.raises(CapabilityPackageContractError):
        parse_capability_package_v1(payload)


def test_models_are_frozen() -> None:
    package = parse_capability_package_v1(_payload())

    with pytest.raises(ValidationError):
        package.package_id = "changed"


def test_generated_json_schema_is_draft_2020_12_and_closed() -> None:
    schema = capability_package_v1_json_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == CAPABILITY_PACKAGE_SCHEMA_URI_V1
    assert schema["additionalProperties"] is False
    artifact_schema = schema["$defs"]["PackageArtifactDescriptorV1"]
    assert artifact_schema["additionalProperties"] is False
    assert len(capability_package_v1_schema_digest()) == 64


def test_direct_model_validation_rejects_unknown_fields() -> None:
    payload = _payload()
    payload["module"] = "jarvis.bad"

    with pytest.raises(ValidationError):
        CapabilityPackageV1.model_validate(payload)
