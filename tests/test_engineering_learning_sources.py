from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityEvaluator,
    CapabilityCompatibilityReportV1,
    CompatibilityVerdict,
)
from jarvis.capability_registry.contracts import parse_capability_package_v1
from jarvis.capability_registry.models import (
    CapabilityLifecycleEventKind,
    DesiredActivationState,
)
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_learning.sources import CapabilityCompatibilityOutcomeSource


def test_bounded_compatibility_scans_reach_later_packages_and_retry_failed_evaluation(
    tmp_path, monkeypatch
):
    registry = CapabilityRegistryStore(tmp_path / "registry.sqlite")
    for ordinal in range(3):
        identity = f"test.package{ordinal}"
        package = parse_capability_package_v1(
            {
                "schema_version": 1,
                "package_id": identity,
                "package_version": "1.0.0",
                "capability_id": identity,
                "package_kind": "extension_source",
                "manifest_id": f"manifest.{identity}",
                "manifest_version": 1,
                "manifest_digest": "b" * 64,
                "runtime_api_id": "jarvis.capability_runtime",
                "runtime_api_version": 1,
                "artifacts": [],
                "attestation_refs": [],
                "sbom_refs": [],
            }
        )
        registry.admit_package(
            package, admitted_release_sha="c" * 40, evidence_digest="e" * 64
        )
        registry.transition_registry(
            identity,
            expected_generation=1,
            desired_state=DesiredActivationState.DISABLED,
            selected_package_id=identity,
            selected_package_version="1.0.0",
            event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
            reason_code="test_selection",
            evidence_ref=package.digest,
        )
    evaluator = object.__new__(CapabilityCompatibilityEvaluator)
    fail = True

    def evaluate(admitted):
        if fail and admitted.package.package_id == "test.package0":
            raise ValueError("synthetic missing artifact")
        return CapabilityCompatibilityReportV1(
            package_id=admitted.package.package_id,
            package_version="1.0.0",
            package_digest=admitted.package_digest,
            current_release_sha="c" * 40,
            runtime_release_sha="c" * 40,
            platform_tags=("windows-amd64",),
            verdict=CompatibilityVerdict.READY,
            reason_codes=("ready",),
            manifest_digest=None,
            provider_descriptor_digest=None,
            artifact_digests=(),
        )

    monkeypatch.setattr(evaluator, "evaluate", evaluate)
    source = CapabilityCompatibilityOutcomeSource(registry, evaluator)
    first = source.scan(limit=2, observed_at_epoch=100)
    second = source.scan(limit=2, observed_at_epoch=101)
    fail = False
    retry = source.scan(limit=2, observed_at_epoch=102)
    assert len(first.errors) == 1
    assert [o.package_id for o in second.outcomes] == ["test.package2"]
    assert [o.package_id for o in retry.outcomes] == ["test.package0", "test.package1"]
