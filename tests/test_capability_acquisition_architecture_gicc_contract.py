from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionArchitectureError,
    CapabilityAcquisitionArchitecturePlan,
    _effective_owner_acceptance_contract_ids,
    _gicc_semantic_contract,
    ensure_gicc_external_acceptance_contract_current,
    require_gicc_physical_target_identity,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1
from jarvis.capability_acquisition.workflow import AcquisitionFinalizeExecutor
from jarvis.engineering_substrate.sandbox import default_sandbox_registry


class FakeStore:
    def __init__(self, schema: str) -> None:
        self._artifact = SimpleNamespace(
            payload={
                "schema": schema,
                "reusable_capability_family": "media_player.control",
                "minimum_required_operations": ["play"],
                "target_entity_type": "media_player",
                "target_entity_id": "entity_tv",
                "monitor_event_contract_required": False,
                "monitor_event_contract": None,
            }
        )

    def latest_artifact(self, change_id: str, kind: str):
        assert change_id == "change-tv"
        assert kind == "gicc_capability_gap_link"
        return self._artifact


def _architecture_with_profiles(profiles: tuple[str, ...]):
    return CapabilityAcquisitionArchitecturePlan(
        goal_artifact_id="goal-artifact",
        goal_artifact_digest="a" * 64,
        goal_id="goal",
        goal_digest="b" * 64,
        plan_artifact_id="plan-artifact",
        plan_artifact_digest="c" * 64,
        plan_id="plan",
        plan_digest="d" * 64,
        selected_candidate_id="candidate",
        selected_candidate_digest="e" * 64,
        selected_evaluation_digest="f" * 64,
        source_revision="a" * 40,
        strategy="build_custom",
        requested_operations=("power",),
        allowed_paths=("src/jarvis/acquired_capabilities/demo",),
        allowed_components=(),
        dependency_refs=(),
        secret_scopes=(),
        sandbox_profile_ids=profiles,
        discovery_scopes=(),
        network_scopes=(),
        device_scopes=(),
        verification_contract_ids=("contract",),
        verification_targets=("tests/test_demo.py",),
        owner_acceptance_contract_ids=(),
        proposed_capability_id="demo",
        proposed_package_id="demo",
        proposed_package_version="1.0.0",
        rollback_strategy="disable",
    )


@pytest.mark.parametrize(
    "profile", ["local_device_control", "local_device_control.v1", "test.offline.v1.v1"]
)
def test_unregistered_sandbox_cannot_reach_approval_architecture(profile: str) -> None:
    with pytest.raises(CapabilityAcquisitionArchitectureError, match="sandbox profile"):
        _architecture_with_profiles((profile,))


def test_registered_sandbox_identity_is_preserved_without_version_suffix_rewrite() -> (
    None
):
    architecture = _architecture_with_profiles(("test.offline.v1",))
    profile_id = architecture.to_payload()["sandbox_profile_ids"][0]
    assert (
        default_sandbox_registry().require(profile_id, 1).profile.profile_id
        == profile_id
    )


def test_research_finalization_advertises_only_registered_sandbox_profiles() -> None:
    schema = AcquisitionFinalizeExecutor.descriptor.parameter_schema
    offered = schema["properties"]["sandbox_profile_ids"]["items"]["enum"]
    assert set(offered) == {
        definition.profile.profile_id for definition in default_sandbox_registry().all()
    }


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire reusable media player control.",
        requested_capability="media_player.control",
        required_operations=("play",),
        target_hints=("entity_type:media_player", "entity_id:entity_tv"),
        source_session_id="gicc:goal-tv",
        source_turn_id="gap:gap-tv",
        now_epoch=1.0,
    )


@pytest.mark.parametrize(
    "schema",
    ("gicc_phase9_gap_link.v1", "gicc_phase9_gap_link.v2"),
)
def test_gicc_semantic_contract_accepts_durable_supported_link_versions(
    schema: str,
) -> None:
    contract = _gicc_semantic_contract(
        FakeStore(schema),
        change_id="change-tv",
        goal=_goal(),
    )

    assert contract is not None
    assert contract.semantic_capability_family == "media_player.control"
    assert contract.required_operations == ("play",)
    assert contract.target_entity_type == "media_player"
    assert contract.target_entity_id == "entity_tv"


def test_gicc_semantic_contract_rejects_unknown_future_link_version() -> None:
    with pytest.raises(
        CapabilityAcquisitionArchitectureError,
        match="unsupported contract",
    ):
        _gicc_semantic_contract(
            FakeStore("gicc_phase9_gap_link.v3"),
            change_id="change-tv",
            goal=_goal(),
        )


def test_gicc_semantic_build_always_requires_real_external_acceptance() -> None:
    contract = _gicc_semantic_contract(
        FakeStore("gicc_phase9_gap_link.v2"),
        change_id="change-tv",
        goal=_goal(),
    )
    assert contract is not None

    contracts = _effective_owner_acceptance_contract_ids(
        (),
        semantic_contract=contract,
    )

    assert contracts == (PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,)


def test_non_gicc_architecture_preserves_declared_acceptance_contracts() -> None:
    contracts = _effective_owner_acceptance_contract_ids(
        ("owner.manual-check.v1",),
        semantic_contract=None,
    )

    assert contracts == ("owner.manual-check.v1",)


class _CurrentArchitectureStore:
    def __init__(self, *, gicc: bool, contracts: tuple[str, ...]) -> None:
        self._link = (
            SimpleNamespace(kind="gicc_capability_gap_link", payload={})
            if gicc
            else None
        )
        self._architecture = SimpleNamespace(
            kind="architecture",
            payload={"owner_acceptance_contract_ids": list(contracts)},
        )

    def latest_artifact(self, change_id: str, kind: str):
        assert change_id == "change-tv"
        if kind == "gicc_capability_gap_link":
            return self._link
        if kind == "architecture":
            return self._architecture
        raise AssertionError(kind)


def test_current_gicc_architecture_rejects_legacy_missing_external_acceptance() -> None:
    store = _CurrentArchitectureStore(gicc=True, contracts=())

    with pytest.raises(
        CapabilityAcquisitionArchitectureError,
        match="mandatory real-target external acceptance",
    ):
        ensure_gicc_external_acceptance_contract_current(
            store,
            "change-tv",
        )


def test_current_gicc_architecture_accepts_real_external_acceptance_contract() -> None:
    store = _CurrentArchitectureStore(
        gicc=True,
        contracts=(PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,),
    )

    architecture = ensure_gicc_external_acceptance_contract_current(
        store,
        "change-tv",
    )

    assert architecture is store._architecture


def test_non_gicc_current_architecture_does_not_invent_external_acceptance() -> None:
    store = _CurrentArchitectureStore(gicc=False, contracts=())

    architecture = ensure_gicc_external_acceptance_contract_current(
        store,
        "change-tv",
        architecture=store._architecture,
    )

    assert architecture is store._architecture


@pytest.mark.parametrize(
    "target",
    ["run all tests", "../tests/test_demo.py", "--pyargs", "tests/test_demo.py::"],
)
def test_invalid_executable_target_cannot_reach_approval_architecture(target):
    from dataclasses import replace

    with pytest.raises(
        CapabilityAcquisitionArchitectureError, match="executable verification"
    ):
        replace(
            _architecture_with_profiles(("test.offline.v1",)),
            verification_targets=(target,),
        )


class _TargetEvidenceStore:
    def __init__(self, target_id, *, context_id=None, provenance=None):
        self.target_id = target_id
        self.context_id = context_id
        self.provenance = provenance

    def latest_artifact(self, change_id, kind):
        assert change_id == "change-tv"
        if kind == "gicc_capability_gap_link":
            return SimpleNamespace(payload={
                "target_entity_type": "television",
                "target_entity_id": self.target_id,
            })
        if kind == "gicc_target_context" and self.context_id is not None:
            return SimpleNamespace(payload={
                "target_entity_type": "television",
                "target_entity_id": self.context_id,
                "canonical_name": "Verified owner TV",
                "provenance_refs": self.provenance,
            })
        return None


@pytest.mark.parametrize(
    ("target_id", "context_id", "provenance"),
    [
        (None, None, None),
        ("entity-tv", None, None),
        ("entity-tv", "entity-other", ("owner:device",)),
        ("entity-tv", "entity-tv", ()),
    ],
)
def test_gicc_physical_architecture_rejects_missing_or_invalid_identity(
    target_id, context_id, provenance
) -> None:
    with pytest.raises(
        CapabilityAcquisitionArchitectureError,
        match="identity is unresolved",
    ):
        require_gicc_physical_target_identity(
            _TargetEvidenceStore(
                target_id, context_id=context_id, provenance=provenance
            ),
            "change-tv",
        )


def test_gicc_physical_architecture_accepts_grounded_identity_only() -> None:
    require_gicc_physical_target_identity(
        _TargetEvidenceStore(
            "entity-tv",
            context_id="entity-tv",
            provenance=("owner_inventory:television",),
        ),
        "change-tv",
    )
