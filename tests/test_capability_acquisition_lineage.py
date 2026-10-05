from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)


class FakeStore:
    def __init__(self) -> None:
        self.artifacts = {}

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


def _current_store(*, external_required: bool = False) -> FakeStore:
    store = FakeStore()
    candidate = _artifact(
        "candidate",
        "c",
        {
            "package_id": "tv.control.package",
            "package_version": "1.0.0",
            "package_digest": "p" * 64,
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
        },
    )
    architecture = _artifact(
        "architecture",
        "h",
        {
            "owner_acceptance_contract_ids": (
                [PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT] if external_required else []
            )
        },
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
    }
    return store


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
    assert result.external_acceptance_required is False


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
    store = _current_store(external_required=True)

    assert (
        verify_capability_acquisition_completion(
            store,
            change_id="change-tv",
            motivating_goal_id="goal-tv",
            gap_id="gap-tv",
        )
        is None
    )

    candidate = store.artifacts["capability_candidate"]
    activation = store.artifacts["capability_lifecycle_activation"]
    store.artifacts["capability_external_acceptance"] = _artifact(
        "external",
        "e",
        {
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "activation_artifact_id": activation.artifact_id,
            "activation_artifact_digest": activation.digest,
            "verdict": "pass",
        },
    )

    result = verify_capability_acquisition_completion(
        store,
        change_id="change-tv",
        motivating_goal_id="goal-tv",
        gap_id="gap-tv",
    )
    assert result is not None
    assert result.external_acceptance_required is True
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
