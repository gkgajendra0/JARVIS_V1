from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionArchitectureError,
    _effective_owner_acceptance_contract_ids,
    _gicc_semantic_contract,
    ensure_gicc_external_acceptance_contract_current,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1


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
