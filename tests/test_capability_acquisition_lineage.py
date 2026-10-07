from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
    EXTERNAL_ACCEPTANCE_RESULT_KIND,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.engineering_substrate.change_integration import MANIFEST_KIND
from jarvis.work.models import WorkState, WorkType


class FakeWorkStore:
    def __init__(self) -> None:
        self.items = {}
        self.steps = {}

    def get(self, work_id: str):
        return self.items.get(work_id)

    def list_steps(self, work_id: str):
        return tuple(self.steps.get(work_id, ()))


class FakeStore:
    def __init__(self) -> None:
        self.artifacts = {}
        self.work = FakeWorkStore()

    def latest_artifact(self, change_id: str, kind: str):
        assert change_id == "change-tv"
        return self.artifacts.get(kind)


def _artifact(
    artifact_id: str,
    digest_char: str,
    payload,
    *,
    created_at: str = "2026-10-03T10:00:00+00:00",
):
    return SimpleNamespace(
        artifact_id=artifact_id,
        digest=digest_char * 64,
        payload=payload,
        created_at=created_at,
    )


def _completed_step(kind: str, observation: dict[str, object]):
    return SimpleNamespace(
        kind=kind,
        state=SimpleNamespace(value="completed"),
        observation=observation,
    )


def _current_store(*, install_external_pass: bool = True) -> FakeStore:
    store = FakeStore()
    candidate = _artifact(
        "candidate",
        "c",
        {
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
            "development_work_id": "work-development",
        },
    )
    admission = _artifact(
        "admission",
        "a",
        {
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
        },
    )
    activation = _artifact(
        "activation",
        "b",
        {
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "admission_artifact_id": admission.artifact_id,
            "admission_artifact_digest": admission.digest,
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
            "effective_enabled": True,
            "authority_session_id": "owner-session",
            "source_turn_id": "activation-turn",
        },
    )
    architecture = _artifact(
        "architecture",
        "h",
        {
            "owner_acceptance_contract_ids": [
                PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
            ]
        },
    )
    goal_artifact = _artifact(
        "goal-artifact",
        "g",
        {"schema": "owner_capability_goal.v1"},
    )
    manifest = _artifact(
        "manifest",
        "m",
        {"schema": "substrate_manifest.v1"},
    )
    store.artifacts = {
        "gicc_capability_gap_link": _artifact(
            "link",
            "l",
            {
                "schema": "gicc_phase9_gap_link.v2",
                "motivating_goal_id": "goal-tv",
                "gap_id": "gap-tv",
                "engineering_change_id": "change-tv",
                "request_id": "request-tv",
                "request_digest": "r" * 64,
                "acquisition_work_id": "work-tv",
            },
        ),
        "capability_candidate": candidate,
        "capability_package_admission": admission,
        "capability_lifecycle_activation": activation,
        "architecture": architecture,
        "capability_goal": goal_artifact,
        MANIFEST_KIND: manifest,
    }
    if install_external_pass:
        _install_external_pass(store)
    return store


def _install_external_pass(store: FakeStore) -> None:
    candidate = store.artifacts["capability_candidate"]
    activation = store.artifacts["capability_lifecycle_activation"]
    architecture = store.artifacts["architecture"]
    goal_artifact = store.artifacts["capability_goal"]
    manifest = store.artifacts[MANIFEST_KIND]
    work_id = "work-external"

    binding = _artifact(
        "binding",
        "i",
        {
            "schema": "capability_external_acceptance_binding.v1",
            "work_id": work_id,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
            "architecture_artifact_id": architecture.artifact_id,
            "architecture_artifact_digest": architecture.digest,
            "manifest_artifact_id": manifest.artifact_id,
            "manifest_artifact_digest": manifest.digest,
            "goal_artifact_id": goal_artifact.artifact_id,
            "goal_artifact_digest": goal_artifact.digest,
            "acceptance_contract_id": PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
            "authority_session_id": activation.payload["authority_session_id"],
            "source_turn_id": activation.payload["source_turn_id"],
        },
    )
    store.artifacts[EXTERNAL_ACCEPTANCE_BINDING_KIND] = binding
    store.work.items[work_id] = SimpleNamespace(
        work_type=WorkType.EXTERNAL_ACCEPTANCE,
        source_session_id="phase9-external:change-tv",
        source_turn_id=activation.artifact_id,
        dependencies=(candidate.payload["development_work_id"],),
        state=WorkState.COMPLETED,
    )
    store.work.steps[work_id] = (
        _completed_step("external_acceptance_inspect", {"inspected": True}),
        _completed_step("external_acceptance_prepare", {"prepared": True}),
        _completed_step("external_acceptance_invoke", {"invoked": True}),
        _completed_step(
            "external_acceptance_record",
            {"acceptance_recorded": True, "verdict": "pass"},
        ),
    )
    store.artifacts[EXTERNAL_ACCEPTANCE_RESULT_KIND] = _artifact(
        "external",
        "e",
        {
            "schema": "capability_external_acceptance.v1",
            "work_id": work_id,
            "binding_artifact_id": binding.artifact_id,
            "binding_artifact_digest": binding.digest,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
            "verdict": "pass",
        },
    )


def test_lineage_verifier_returns_exact_current_chain() -> None:
    store = _current_store()

    result = verify_capability_acquisition_completion(
        store,
        change_id="change-tv",
        motivating_goal_id="goal-tv",
        gap_id="gap-tv",
        request_id="request-tv",
        request_digest="r" * 64,
    )

    assert result is not None
    assert result.change_id == "change-tv"
    assert result.acquisition_work_id == "work-tv"
    assert result.package_id == "tv.control.package"
    assert result.package_version == "1.0.0"
    assert result.package_digest == "p" * 64
    assert result.external_acceptance_required is True


def test_lineage_verifier_returns_none_until_activation_is_effective() -> None:
    store = _current_store()
    store.artifacts["capability_lifecycle_activation"].payload["effective_enabled"] = (
        False
    )

    assert (
        verify_capability_acquisition_completion(
            store,
            change_id="change-tv",
            motivating_goal_id="goal-tv",
            gap_id="gap-tv",
        )
        is None
    )


def test_lineage_verifier_rejects_stale_candidate_binding() -> None:
    store = _current_store()
    store.artifacts["capability_package_admission"].payload[
        "candidate_artifact_digest"
    ] = "0" * 64

    with pytest.raises(
        CapabilityAcquisitionLineageError,
        match="package admission is not bound",
    ):
        verify_capability_acquisition_completion(
            store,
            change_id="change-tv",
            motivating_goal_id="goal-tv",
            gap_id="gap-tv",
        )


def test_lineage_verifier_requires_external_pass_when_declared() -> None:
    store = _current_store(install_external_pass=False)

    assert (
        verify_capability_acquisition_completion(
            store,
            change_id="change-tv",
            motivating_goal_id="goal-tv",
            gap_id="gap-tv",
        )
        is None
    )

    _install_external_pass(store)

    result = verify_capability_acquisition_completion(
        store,
        change_id="change-tv",
        motivating_goal_id="goal-tv",
        gap_id="gap-tv",
    )
    assert result is not None
    assert result.external_acceptance_required is True
    assert result.external_acceptance_binding_artifact_id == "binding"
    assert result.external_acceptance_work_id == "work-external"
    assert result.external_acceptance_artifact_id == "external"


def test_lineage_verifier_returns_none_after_later_explicit_disable() -> None:
    store = _current_store()
    candidate = store.artifacts["capability_candidate"]
    store.artifacts["capability_lifecycle_disable"] = _artifact(
        "disable",
        "d",
        {
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "effective_enabled": False,
        },
        created_at="2026-10-03T10:01:00+00:00",
    )

    assert (
        verify_capability_acquisition_completion(
            store,
            change_id="change-tv",
            motivating_goal_id="goal-tv",
            gap_id="gap-tv",
        )
        is None
    )


def test_lineage_verifier_accepts_reactivation_after_older_disable() -> None:
    store = _current_store()
    candidate = store.artifacts["capability_candidate"]
    store.artifacts["capability_lifecycle_disable"] = _artifact(
        "disable",
        "d",
        {
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "effective_enabled": False,
        },
        created_at="2026-10-03T09:59:00+00:00",
    )

    result = verify_capability_acquisition_completion(
        store,
        change_id="change-tv",
        motivating_goal_id="goal-tv",
        gap_id="gap-tv",
    )

    assert result is not None
    assert result.activation_artifact_id == "activation"
