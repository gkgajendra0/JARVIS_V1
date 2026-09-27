"""Typed GitHub promotion evidence contracts; no generic shell authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .candidate import VerifiedPromotionCandidate
from .models import CheckEvidence

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubPromotionError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not code or not text:
            raise ValueError("GitHub promotion failure requires code and message")
        super().__init__(text)
        self.reason_code = code


@dataclass(frozen=True, slots=True)
class GitHubPullRequestSnapshot:
    number: int
    base_sha: str
    head_sha: str
    draft: bool
    state: str

    def __post_init__(self) -> None:
        if type(self.number) is not int or self.number <= 0:
            raise ValueError("PR number must be positive")
        _require_sha(self.base_sha, field="PR base SHA")
        _require_sha(self.head_sha, field="PR head SHA")
        if self.state not in {"open", "closed"}:
            raise ValueError("PR state must be open or closed")


@dataclass(frozen=True, slots=True)
class GitHubWorkflowSnapshot:
    run_id: str
    event: str
    head_sha: str
    tested_merge_sha: str
    status: str
    conclusion: str
    checks: tuple[CheckEvidence, ...]

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise ValueError("workflow run_id must not be empty")
        if self.event != "pull_request":
            raise ValueError("promotion CI must be a pull_request workflow")
        _require_sha(self.head_sha, field="workflow head SHA")
        _require_sha(self.tested_merge_sha, field="tested merge SHA")
        if self.status != "completed":
            raise ValueError("workflow must be completed")
        if self.conclusion != "success":
            raise ValueError("workflow conclusion must be success")
        if not self.checks:
            raise ValueError("workflow requires check evidence")


@dataclass(frozen=True, slots=True)
class VerifiedGitHubEvidence:
    pr_number: int
    pr_base_sha: str
    pr_head_sha: str
    tested_merge_sha: str
    ci_run_id: str
    required_checks: tuple[CheckEvidence, ...]
    windows_verified: bool


class GitHubPromotionClient(Protocol):
    """Narrow future GitHub App transport used by the Phase-7 adapter."""

    def ensure_pull_request(
        self,
        *,
        head_sha: str,
        base_sha: str,
        title: str,
        body: str,
    ) -> GitHubPullRequestSnapshot: ...

    def read_pull_request(self, number: int) -> GitHubPullRequestSnapshot: ...

    def read_workflow(self, number: int) -> GitHubWorkflowSnapshot: ...

    def squash_merge(self, number: int, *, expected_head_sha: str) -> str: ...


def _require_sha(value: object, *, field: str) -> str:
    text = str(value or "").strip().casefold()
    if _GIT_SHA.fullmatch(text) is None:
        raise ValueError(f"{field} must be an exact 40-character Git SHA")
    return text


class GitHubPromotionPolicy:
    """Verify exact PR/CI identity before promotion evidence can exist."""

    def __init__(
        self,
        *,
        required_contexts: tuple[str, ...] = (
            "ruff",
            "pytest",
            "windows-hello-helper",
            "windows-dpapi",
            "promotion-policy",
        ),
        expected_app_id: int | None = 15368,
    ) -> None:
        contexts = tuple(dict.fromkeys(str(item).strip() for item in required_contexts))
        if not contexts or any(not item for item in contexts):
            raise ValueError("required_contexts must be non-empty")
        if expected_app_id is not None and (
            type(expected_app_id) is not int or expected_app_id <= 0
        ):
            raise ValueError("expected_app_id must be positive")
        self.required_contexts = contexts
        self.expected_app_id = expected_app_id

    def verify(
        self,
        candidate: VerifiedPromotionCandidate,
        *,
        current_main_sha: str,
        pr: GitHubPullRequestSnapshot,
        workflow: GitHubWorkflowSnapshot,
    ) -> VerifiedGitHubEvidence:
        current_main = _require_sha(current_main_sha, field="current main SHA")
        if current_main != candidate.base_sha:
            raise GitHubPromotionError(
                "stale_candidate_base",
                "protected main changed after candidate verification",
            )
        if pr.state != "open" or pr.draft:
            raise GitHubPromotionError(
                "pr_not_merge_ready",
                "promotion PR must be open and non-draft before evidence creation",
            )
        if pr.base_sha != candidate.base_sha:
            raise GitHubPromotionError(
                "pr_base_mismatch",
                "PR base no longer equals the verified candidate base",
            )
        if pr.head_sha != candidate.head_sha:
            raise GitHubPromotionError(
                "pr_head_moved",
                "PR head no longer equals the verified candidate commit",
            )
        if workflow.head_sha != candidate.head_sha:
            raise GitHubPromotionError(
                "ci_head_mismatch",
                "CI did not run for the exact candidate head",
            )
        checks = {item.context: item for item in workflow.checks}
        missing = tuple(\n            context for context in self.required_contexts if context not in checks\n        )
        if missing:
            raise GitHubPromotionError(
                "required_ci_missing",
                "required CI checks are missing: " + ", ".join(missing),
            )
        selected: list[CheckEvidence] = []
        for context in self.required_contexts:
            check = checks[context]
            if check.conclusion != "success":
                raise GitHubPromotionError(
                    "required_ci_not_success",
                    f"required CI check {context} did not succeed",
                )
            if (
                self.expected_app_id is not None
                and check.app_id != self.expected_app_id
            ):
                raise GitHubPromotionError(
                    "ci_app_mismatch",
                    f"required CI check {context} came from an unexpected app",
                )
            selected.append(check)
        return VerifiedGitHubEvidence(
            pr_number=pr.number,
            pr_base_sha=pr.base_sha,
            pr_head_sha=pr.head_sha,
            tested_merge_sha=workflow.tested_merge_sha,
            ci_run_id=workflow.run_id,
            required_checks=tuple(selected),
            windows_verified=all(
                checks[name].conclusion == "success"
                for name in ("windows-hello-helper", "windows-dpapi")
            ),
        )


class GitHubPromotionAdapter:
    """Typed side-effect adapter; caller must supply a least-privilege GitHub App client."""

    def __init__(self, client: GitHubPromotionClient) -> None:
        self._client = client

    def ensure_pull_request(
        self,
        candidate: VerifiedPromotionCandidate,
        *,
        title: str,
        body: str,
    ) -> GitHubPullRequestSnapshot:
        return self._client.ensure_pull_request(
            head_sha=candidate.head_sha,
            base_sha=candidate.base_sha,
            title=title,
            body=body,
        )

    def read_pull_request(self, number: int) -> GitHubPullRequestSnapshot:
        return self._client.read_pull_request(number)

    def read_workflow(self, number: int) -> GitHubWorkflowSnapshot:
        return self._client.read_workflow(number)

    def squash_merge(self, number: int, *, expected_head_sha: str) -> str:
        merge_sha = self._client.squash_merge(
            number,
            expected_head_sha=_require_sha(
                expected_head_sha,
                field="expected head SHA",
            ),
        )
        return _require_sha(merge_sha, field="merge SHA")
