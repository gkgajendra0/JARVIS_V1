from __future__ import annotations

from pathlib import Path

from jarvis.dev_control import RuntimeReleaseIdentity
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.promotion.deployment import DeploymentCoordinator
from jarvis.promotion.models import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttemptState,
    PromotionEvidenceV1,
)
from jarvis.promotion.release import DeploymentMetadataStore
from jarvis.promotion.store import PromotionStore
from jarvis.work.store import SQLiteWorkStore

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
CONFIG = "a" * 64
DIGEST = "b" * 64
DIFF = "c" * 64


class FakeStager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def stage(self, sha: str) -> Path:
        target = self.root / sha
        target.mkdir(parents=True, exist_ok=True)
        return target


class FakeRuntime:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def stop_active(self, *, timeout_seconds: float) -> None:
        self.events.append(("stop", timeout_seconds))

    def start_release(self, identity: RuntimeReleaseIdentity) -> None:
        self.events.append(("start", identity))

    def wait_ready(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None:
        self.events.append(("ready", (identity, timeout_seconds)))

    def stop_candidate(self, *, timeout_seconds: float) -> None:
        self.events.append(("stop_candidate", timeout_seconds))


def _fixture(tmp_path: Path):
    changes = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    change = changes.create(
        request="promote candidate",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner",
        source_turn_id="turn",
    )
    with changes.work._lock, changes.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=? WHERE change_id=?",
            (ChangeState.PROMOTED.value, change.change_id),
        )
    candidate = changes.add_artifact(
        change.change_id,
        kind="source_repair_candidate",
        payload={"candidate_id": "candidate-1"},
    )
    promotions = PromotionStore(changes)
    attempt = promotions.create_or_get(
        change_id=change.change_id,
        candidate_artifact_id=candidate.artifact_id,
        candidate_artifact_digest=candidate.digest,
        candidate_id="candidate-1",
        candidate_digest=DIGEST,
        base_sha=BASE,
        head_sha=HEAD,
    )
    attempt = promotions.transition(
        attempt.attempt_id,
        PromotionAttemptState.EVIDENCE_READY,
        expected_version=attempt.version,
    )
    attempt = promotions.transition(
        attempt.attempt_id,
        PromotionAttemptState.AUTHORIZED,
        expected_version=attempt.version,
    )
    attempt = promotions.transition(
        attempt.attempt_id,
        PromotionAttemptState.MERGED,
        expected_version=attempt.version,
        merge_sha=MERGE,
    )
    evidence = PromotionEvidenceV1.create(
        change_id=change.change_id,
        attempt_id=attempt.attempt_id,
        candidate_artifact_id=candidate.artifact_id,
        candidate_artifact_digest=candidate.digest,
        candidate_id="candidate-1",
        candidate_digest=DIGEST,
        candidate_base_sha=BASE,
        candidate_head_sha=HEAD,
        candidate_diff_digest=DIFF,
        changed_paths=["src/jarvis/voice/runtime.py"],
        protected_policy_id="repair.protected_surfaces",
        protected_policy_version=2,
        protected_verdict="clear",
        pr_number=1,
        pr_base_sha=BASE,
        pr_head_sha=HEAD,
        tested_merge_sha="4" * 40,
        ci_run_id="run-1",
        required_checks=(
            CheckEvidence("ruff", "success", 15368),
            CheckEvidence("pytest", "success", 15368),
            CheckEvidence("windows-hello-helper", "success", 15368),
            CheckEvidence("windows-dpapi", "success", 15368),
            CheckEvidence("promotion-policy", "success", 15368),
        ),
        windows_verified=True,
        compatibility=CompatibilityEvidence(
            schema=CompatibilityVerdict.SAFE,
            dbos=CompatibilityVerdict.SAFE,
            dependencies=CompatibilityVerdict.SAFE,
        ),
        config_digest=CONFIG,
        merge_method="squash",
        deployment_environment="owner-windows",
        lkg_release_sha=BASE,
        now_epoch=1.0,
    )
    return changes, promotions, attempt, evidence


def test_deployment_bootstrap_and_exact_release_switch(tmp_path: Path) -> None:
    changes, promotions, attempt, evidence = _fixture(tmp_path)
    metadata = DeploymentMetadataStore(tmp_path / "deployment")
    runtime = FakeRuntime()
    coordinator = DeploymentCoordinator(
        changes,
        promotions,
        stager=FakeStager(tmp_path / "releases"),
        metadata=metadata,
        runtime=runtime,
    )
    lkg = coordinator.bootstrap_lkg(
        release_sha=BASE,
        config_digest=CONFIG,
        verified=True,
        now_epoch=1.0,
    )
    assert metadata.active() == lkg
    assert metadata.lkg() == lkg

    result = coordinator.deploy(
        evidence=evidence,
        attempt=attempt,
        now_epoch=2.0,
    )

    assert result.release.release_sha == MERGE
    assert metadata.active() == result.release
    assert metadata.lkg() == lkg
    assert metadata.recovery().phase.value == "new_runtime_verified"
    assert promotions.require(attempt.attempt_id).state is PromotionAttemptState.OBSERVING
    assert changes.require(evidence.change_id).state is ChangeState.OBSERVING
    started = runtime.events[1][1]
    assert isinstance(started, RuntimeReleaseIdentity)
    assert started.release_sha == MERGE
    assert started.promotion_attempt_id == attempt.attempt_id


def test_release_identity_rejects_incomplete_or_wrong_digest(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_RELEASE_SHA", MERGE)
    monkeypatch.setenv("JARVIS_RELEASE_ROOT", "C:/jarvis/releases/test")
    monkeypatch.setenv("JARVIS_PROMOTION_ATTEMPT_ID", "promotion_123")
    monkeypatch.delenv("JARVIS_RELEASE_CONFIG_DIGEST", raising=False)

    try:
        RuntimeReleaseIdentity.from_environment()
    except RuntimeError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete release identity was accepted")
