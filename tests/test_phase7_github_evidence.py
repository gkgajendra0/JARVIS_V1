from __future__ import annotations

import pytest

from jarvis.promotion import CheckEvidence
from jarvis.promotion.candidate import VerifiedPromotionCandidate
from jarvis.promotion.compatibility import assess_ordinary_compatibility
from jarvis.promotion.github import (
    GitHubPromotionError,
    GitHubPromotionPolicy,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
)

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
DIGEST = "a" * 64
DIFF = "b" * 64


def _candidate() -> VerifiedPromotionCandidate:
    return VerifiedPromotionCandidate(
        change_id="change_1",
        acceptance_artifact_id="artifact_acceptance",
        acceptance_artifact_digest=DIGEST,
        candidate_artifact_id="artifact_candidate",
        candidate_artifact_digest=DIGEST,
        candidate_id="candidate_1",
        candidate_digest=DIGEST,
        base_sha=BASE,
        head_sha=HEAD,
        diff_digest=DIFF,
        changed_paths=("src/jarvis/voice/runtime.py",),
        protected_policy_id="repair.protected_surfaces",
        protected_policy_version=2,
        protected_verdict="clear",
    )


def _workflow(*, head=HEAD, checks=None) -> GitHubWorkflowSnapshot:
    return GitHubWorkflowSnapshot(
        run_id="123",
        event="pull_request",
        head_sha=head,
        tested_merge_sha=MERGE,
        status="completed",
        conclusion="success",
        checks=tuple(
            checks
            or [
                CheckEvidence("ruff", "success", 15368),
                CheckEvidence("pytest", "success", 15368),
                CheckEvidence("windows-hello-helper", "success", 15368),
                CheckEvidence("windows-dpapi", "success", 15368),
                CheckEvidence("promotion-policy", "success", 15368),
            ]
        ),
    )


def test_github_policy_binds_exact_candidate_and_windows_ci() -> None:
    candidate = _candidate()
    result = GitHubPromotionPolicy().verify(
        candidate,
        current_main_sha=BASE,
        pr=GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open"),
        workflow=_workflow(),
    )

    assert result.pr_head_sha == HEAD
    assert result.tested_merge_sha == MERGE
    assert result.windows_verified is True
    assert tuple(item.context for item in result.required_checks)[-1] == "promotion-policy"


def test_github_policy_rejects_moved_head_or_wrong_check_app() -> None:
    candidate = _candidate()
    with pytest.raises(GitHubPromotionError) as moved:
        GitHubPromotionPolicy().verify(
            candidate,
            current_main_sha=BASE,
            pr=GitHubPullRequestSnapshot(12, BASE, "9" * 40, False, "open"),
            workflow=_workflow(),
        )
    assert moved.value.reason_code == "pr_head_moved"

    checks = list(_workflow().checks)
    checks[0] = CheckEvidence("ruff", "success", 999)
    with pytest.raises(GitHubPromotionError) as wrong_app:
        GitHubPromotionPolicy().verify(
            candidate,
            current_main_sha=BASE,
            pr=GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open"),
            workflow=_workflow(checks=checks),
        )
    assert wrong_app.value.reason_code == "ci_app_mismatch"


def test_github_policy_rejects_skipped_windows_validation() -> None:
    candidate = _candidate()
    checks = list(_workflow().checks)
    checks[3] = CheckEvidence("windows-dpapi", "skipped", 15368)

    with pytest.raises(GitHubPromotionError) as error:
        GitHubPromotionPolicy().verify(
            candidate,
            current_main_sha=BASE,
            pr=GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open"),
            workflow=_workflow(checks=checks),
        )

    assert error.value.reason_code == "required_ci_not_success"


def test_compatibility_classifier_marks_high_risk_surfaces() -> None:
    ordinary = assess_ordinary_compatibility(("src/jarvis/voice/runtime.py",))
    assert ordinary.evidence.ordinary_path_safe
    assert ordinary.reason_codes == ()

    risky = assess_ordinary_compatibility(
        (
            "src/jarvis/work/dbos_backend.py",
            "src/jarvis/memory/migrations/002_new.sql",
            "pyproject.toml",
        )
    )
    assert not risky.evidence.ordinary_path_safe
    assert set(risky.reason_codes) == {
        "dbos_workflow_or_persistence_change",
        "durable_schema_change",
        "runtime_dependency_change",
    }
