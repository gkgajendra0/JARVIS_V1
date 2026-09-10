from __future__ import annotations

from typing import Any

from jarvis.capabilities.development_git import (
    ApprovedRepositoryPolicy,
    DevelopmentGitExecutor,
)
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus


class FakeGitBackend:
    def __init__(self) -> None:
        self.head = "a" * 40
        self.branch_oids: dict[str, str] = {}
        self.remote_oids: dict[str, str] = {}
        self.status_payload: dict[str, Any] = {
            "staged": {},
            "unstaged": [],
            "untracked": [],
        }
        self.created_branch: str | None = None
        self.staged_paths: list[str] = []
        self.commit_oid = self.head
        self.push_branch = "feature"

    def status(self, repo):
        del repo
        return self.status_payload

    def active_branch(self, repo) -> str:
        del repo
        return self.push_branch

    def head_oid(self, repo) -> str:
        del repo
        return self.head

    def branch_oid(self, repo, branch: str) -> str | None:
        del repo
        return self.branch_oids.get(branch)

    def create_branch(self, repo, branch: str) -> None:
        del repo
        self.created_branch = branch

    def stage(self, repo, paths: list[str]) -> None:
        del repo
        self.staged_paths = list(paths)

    def commit(self, repo, message: str) -> str:
        del repo, message
        return self.commit_oid

    def push_current(self, repo) -> dict[str, Any]:
        del repo
        return {"branch": self.push_branch, "remote": "origin"}

    def remote_branch_oid(self, repo, branch: str) -> str | None:
        del repo
        return self.remote_oids.get(branch)


def _executor(tmp_path, backend: FakeGitBackend) -> DevelopmentGitExecutor:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    policy = ApprovedRepositoryPolicy(
        {"demo": repo},
        jarvis_root=tmp_path / "jarvis",
        include_jarvis_read_target=False,
    )
    return DevelopmentGitExecutor(policy=policy, backend=backend)


def _request(
    executor: DevelopmentGitExecutor,
    operation: str,
    parameters: dict[str, object] | None = None,
) -> CapabilityRequest:
    return CapabilityRequest(
        session_id="git-verification-test",
        capability_key=executor.capability_key,
        operation=operation,
        parameters={"repo": "demo", **(parameters or {})},
    )


def test_create_branch_fails_when_postcondition_does_not_exist(tmp_path) -> None:
    backend = FakeGitBackend()
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(
        _request(executor, "git_create_branch", {"branch": "feature/verified"})
    )

    result = executor.execute(prepared)

    assert backend.created_branch == "feature/verified"
    assert result.status is CapabilityStatus.FAILED
    assert result.data["verification_passed"] is False
    assert result.reason == "Git post-action verification failed"


def test_create_branch_passes_only_when_branch_points_to_original_head(tmp_path) -> None:
    backend = FakeGitBackend()
    backend.branch_oids["feature/verified"] = backend.head
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(
        _request(executor, "git_create_branch", {"branch": "feature/verified"})
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["branch_oid"] == backend.head
    assert result.data["verification_passed"] is True


def test_stage_fails_when_requested_path_remains_unstaged(tmp_path) -> None:
    backend = FakeGitBackend()
    backend.status_payload = {
        "staged": {},
        "unstaged": ["src/example.py"],
        "untracked": [],
    }
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(
        _request(executor, "git_stage_paths", {"paths": ["src/example.py"]})
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.FAILED
    assert result.data["verification_passed"] is False


def test_stage_accepts_requested_path_when_no_residual_change_remains(tmp_path) -> None:
    backend = FakeGitBackend()
    backend.status_payload = {
        "staged": {"add": ["src/example.py"]},
        "unstaged": [],
        "untracked": [],
    }
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(
        _request(executor, "git_stage_paths", {"paths": ["src/example.py"]})
    )

    result = executor.execute(prepared)

    assert backend.staged_paths == ["src/example.py"]
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["verification_passed"] is True


def test_commit_fails_when_returned_commit_is_not_repository_head(tmp_path) -> None:
    backend = FakeGitBackend()
    backend.commit_oid = "b" * 40
    backend.head = "c" * 40
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(
        _request(executor, "git_commit", {"message": "verified commit"})
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.FAILED
    assert result.data["commit"] == "b" * 40
    assert result.data["head"] == "c" * 40
    assert result.data["verification_passed"] is False


def test_push_fails_when_remote_branch_does_not_match_local_head(tmp_path) -> None:
    backend = FakeGitBackend()
    backend.remote_oids[backend.push_branch] = "d" * 40
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(_request(executor, "git_push_current"))

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.FAILED
    assert result.data["local_oid"] == backend.head
    assert result.data["remote_oid"] == "d" * 40
    assert result.data["verification_passed"] is False


def test_push_succeeds_only_when_remote_branch_matches_local_head(tmp_path) -> None:
    backend = FakeGitBackend()
    backend.remote_oids[backend.push_branch] = backend.head
    executor = _executor(tmp_path, backend)
    prepared = executor.prepare(_request(executor, "git_push_current"))

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["remote_oid"] == backend.head
    assert result.data["verification_passed"] is True
