from __future__ import annotations

import pytest

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition import (
    AcquisitionContextV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionResolver,
    CapabilitySourceRegistry,
    CustomBuildCapabilitySourceAdapter,
    McpCapabilitySourceAdapter,
    OpenApiCapabilitySourceAdapter,
    AsyncApiCapabilitySourceAdapter,
    SdkLibraryCapabilitySourceAdapter,
    OwnerConfiguredCapabilitySourceAdapter,
    OwnerCapabilityGoalV1,
    SourceEvidenceError,
    asyncapi_contract_evidence,
    mcp_server_evidence,
    openapi_contract_evidence,
    owner_configured_evidence,
    sdk_library_evidence,
)


def _goal(*operations: str) -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire a TV control capability",
        requested_capability="TV control",
        required_operations=operations or ("power", "volume"),
        source_session_id="session-9c",
        source_turn_id="turn-9c",
        now_epoch=1000.0,
    )


def _context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def test_mcp_tools_list_becomes_nonexecuting_wrap_candidate() -> None:
    evidence = mcp_server_evidence(
        server_identity="https://tv.example.test/mcp",
        server_version="2.0.0",
        tools=(
            {"name": "power", "inputSchema": {"type": "object"}},
            {
                "name": "volume",
                "inputSchema": {
                    "type": "object",
                    "properties": {"level": {"type": "integer"}},
                },
            },
        ),
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:mcp-tools-list",),
        network_scopes=("https://tv.example.test",),
    )
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((McpCapabilitySourceAdapter((evidence,)),))
    )

    result = resolver.resolve(_goal("power", "volume"), _context())

    assert result.selected_candidate is not None
    candidate = result.selected_candidate
    assert candidate.source_kind is AcquisitionSourceKind.MCP
    assert candidate.strategy is AcquisitionStrategy.WRAP
    assert candidate.supported_operations == ("power", "volume")
    assert len(candidate.source_digest or "") == 64


def test_mcp_evidence_digest_is_stable_under_tool_order() -> None:
    kwargs = {
        "server_identity": "mcp:tv",
        "server_version": "1",
        "trust_class": AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        "evidence_refs": ("registry:tv",),
    }
    first = mcp_server_evidence(
        tools=(
            {"name": "power", "inputSchema": {"type": "object"}},
            {"name": "volume", "inputSchema": {"type": "object"}},
        ),
        **kwargs,
    )
    second = mcp_server_evidence(
        tools=(
            {"name": "volume", "inputSchema": {"type": "object"}},
            {"name": "power", "inputSchema": {"type": "object"}},
        ),
        **kwargs,
    )

    assert first.source_digest == second.source_digest
    assert first.supported_operations == second.supported_operations


def test_openapi_contract_extracts_only_operation_ids() -> None:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "TV", "version": "1.0.0"},
        "paths": {
            "/power": {
                "post": {
                    "operationId": "power",
                    "x-command": "this-is-inert-document-metadata",
                }
            },
            "/volume": {"post": {"operationId": "volume"}},
        },
        "command": "also-inert-document-metadata",
    }
    evidence = openapi_contract_evidence(
        source_identity="https://tv.example.test/openapi.json",
        document=document,
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:openapi",),
        network_scopes=("https://tv.example.test",),
    )
    candidate = OpenApiCapabilitySourceAdapter((evidence,)).discover(
        _goal("power", "volume"),
        _context(),
    )[0]

    assert candidate.strategy is AcquisitionStrategy.GENERATE_CONTRACT_CLIENT
    assert candidate.supported_operations == ("power", "volume")
    assert not hasattr(candidate, "command")
    assert not hasattr(candidate, "argv")
    assert not hasattr(candidate, "executable_path")


def test_openapi_requires_v3_and_at_least_one_operation_id() -> None:
    with pytest.raises(SourceEvidenceError, match="OpenAPI 3"):
        openapi_contract_evidence(
            source_identity="api:old",
            document={"openapi": "2.0", "paths": {}},
            trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
            evidence_refs=("docs:old",),
        )

    with pytest.raises(SourceEvidenceError, match="semantic operations"):
        openapi_contract_evidence(
            source_identity="api:no-ids",
            document={
                "openapi": "3.1.0",
                "paths": {"/thing": {"get": {"summary": "No operation ID"}}},
            },
            trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
            evidence_refs=("docs:no-ids",),
        )


def test_asyncapi_v3_operations_become_contract_generation_candidate() -> None:
    evidence = asyncapi_contract_evidence(
        source_identity="wss://events.example.test",
        document={
            "asyncapi": "3.0.0",
            "info": {"title": "TV events", "version": "1"},
            "operations": {
                "watchPower": {"operationId": "power.changed"},
                "watchVolume": {"operationId": "volume.changed"},
            },
        },
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:asyncapi",),
        network_scopes=("wss://events.example.test",),
    )
    candidate = AsyncApiCapabilitySourceAdapter((evidence,)).discover(
        _goal("power.changed", "volume.changed"),
        _context(),
    )[0]

    assert candidate.source_kind is AcquisitionSourceKind.ASYNCAPI
    assert candidate.strategy is AcquisitionStrategy.GENERATE_CONTRACT_CLIENT


def test_sdk_library_evidence_stays_pinned_and_adapt_only() -> None:
    evidence = sdk_library_evidence(
        package_identity="vendor-tv-sdk",
        package_version="4.2.1",
        package_digest="a" * 64,
        trust_class=AcquisitionTrustClass.VERIFIED_SIGNED_EXTERNAL,
        supported_operations=("power", "volume"),
        evidence_refs=("vendor:release",),
        provenance_refs=("sigstore:bundle",),
        license_id="Apache-2.0",
        dependency_refs=("vendor-tv-sdk==4.2.1",),
    )
    candidate = SdkLibraryCapabilitySourceAdapter((evidence,)).discover(
        _goal("power"),
        _context(),
    )[0]

    assert candidate.strategy is AcquisitionStrategy.ADAPT_SDK
    assert candidate.source_version == "4.2.1"
    assert candidate.source_digest == "a" * 64
    assert candidate.provenance_refs == ("sigstore:bundle",)


def test_owner_configured_source_is_wrap_candidate_not_accepted_release() -> None:
    evidence = owner_configured_evidence(
        source_identity="home-assistant:living-room",
        source_version="2026.9",
        source_digest="b" * 64,
        supported_operations=("power", "volume"),
        evidence_refs=("owner-config:home-assistant",),
        verification_requirements=("home-assistant-entity-contract",),
        secret_scopes=("home_assistant.api",),
    )
    candidate = OwnerConfiguredCapabilitySourceAdapter((evidence,)).discover(
        _goal("power"),
        _context(),
    )[0]

    assert candidate.strategy is AcquisitionStrategy.WRAP
    assert candidate.trust_class is AcquisitionTrustClass.OWNER_CONFIGURED


def test_unverified_standard_source_is_blocked_and_custom_build_is_fallback() -> None:
    unverified = mcp_server_evidence(
        server_identity="mcp:unknown",
        tools=({"name": "power", "inputSchema": {"type": "object"}},),
        trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        evidence_refs=("registry:unknown",),
    )
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(
            (
                McpCapabilitySourceAdapter((unverified,)),
                CustomBuildCapabilitySourceAdapter(),
            )
        )
    )

    result = resolver.resolve(_goal("power"), _context())

    assert result.selected_candidate is not None
    assert result.selected_candidate.source_kind is AcquisitionSourceKind.CUSTOM_BUILD
    assert result.selected_candidate.strategy is AcquisitionStrategy.BUILD_CUSTOM
    mcp_candidate = next(
        item
        for item in result.candidates
        if item.source_kind is AcquisitionSourceKind.MCP
    )
    assert (
        "trust_not_allowed"
        in result.evaluation(mcp_candidate.candidate_id).reason_codes
    )


def test_verified_standard_source_beats_custom_build() -> None:
    evidence = openapi_contract_evidence(
        source_identity="api:tv",
        document={
            "openapi": "3.1.0",
            "paths": {"/power": {"post": {"operationId": "power"}}},
        },
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        evidence_refs=("vendor:openapi",),
    )
    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(
            (
                OpenApiCapabilitySourceAdapter((evidence,)),
                CustomBuildCapabilitySourceAdapter(),
            )
        )
    )

    result = resolver.resolve(_goal("power"), _context())

    assert result.selected_candidate is not None
    assert result.selected_candidate.source_kind is AcquisitionSourceKind.OPENAPI


def test_source_document_size_is_bounded() -> None:
    with pytest.raises(SourceEvidenceError, match="bytes"):
        openapi_contract_evidence(
            source_identity="api:oversized",
            document={
                "openapi": "3.1.0",
                "info": {"description": "x" * (1024 * 1024)},
                "paths": {"/power": {"post": {"operationId": "power"}}},
            },
            trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
            evidence_refs=("test:oversized",),
        )


def test_standard_evidence_rejects_invalid_digest_before_candidate_creation() -> None:
    with pytest.raises(SourceEvidenceError, match="SHA-256"):
        sdk_library_evidence(
            package_identity="broken-sdk",
            package_version="1.0",
            package_digest="not-a-digest",
            trust_class=AcquisitionTrustClass.VERIFIED_SIGNED_EXTERNAL,
            supported_operations=("power",),
            evidence_refs=("vendor:broken",),
            provenance_refs=("signature:broken",),
        )
