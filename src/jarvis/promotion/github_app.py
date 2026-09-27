"""SecretBroker-backed concrete GitHub App transport for governed Phase 7."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import threading
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

from jarvis.dev_control import RuntimeReleaseIdentity

from .github import (
    GitHubPromotionError,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
)
from .models import CheckEvidence

_CONSUMER_ID = "github.promotion.v1"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


@dataclass(frozen=True, slots=True)
class GitHubAppConfig:
    client_id: str
    installation_id: int
    repository_full_name: str
    base_branch: str = "main"
    workflow_file: str = "code-quality.yml"
    request_timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        client = str(self.client_id).strip()
        repository = str(self.repository_full_name).strip()
        branch = str(self.base_branch).strip()
        workflow = pathlib.PurePosixPath(str(self.workflow_file).strip())
        timeout = float(self.request_timeout_seconds)
        if not client:
            raise ValueError("GitHub App client_id must not be empty")
        if type(self.installation_id) is not int or self.installation_id <= 0:
            raise ValueError("GitHub App installation_id must be positive")
        if _REPOSITORY.fullmatch(repository) is None:
            raise ValueError("repository_full_name must use owner/name form")
        if (
            _BRANCH.fullmatch(branch) is None
            or ".." in branch
            or branch.endswith(("/", ".lock"))
        ):
            raise ValueError("base_branch is invalid")
        if (
            not workflow.name
            or workflow.is_absolute()
            or ".." in workflow.parts
            or len(workflow.parts) != 1
        ):
            raise ValueError("workflow_file must be one basename")
        if not 1.0 <= timeout <= 60.0:
            raise ValueError("request_timeout_seconds must be within 1-60 seconds")
        object.__setattr__(self, "client_id", client)
        object.__setattr__(self, "repository_full_name", repository)
        object.__setattr__(self, "base_branch", branch)
        object.__setattr__(self, "workflow_file", workflow.name)
        object.__setattr__(self, "request_timeout_seconds", timeout)


class SecretEnvironmentBroker(Protocol):
    def child_environment(
        self,
        lease_id: str,
        *,
        consumer_id: str,
        parent_environment: Mapping[str, str] | None = None,
    ) -> AbstractContextManager[dict[str, str]]: ...


class BrokeredGitHubAppClient:
    """One process-local GitHub App session with child-only credentials.

    The trusted helper path is derived only from the already verified active release.
    The private key is materialized once by SecretBroker into that child environment.
    """

    def __init__(
        self,
        *,
        broker: SecretEnvironmentBroker,
        lease_id: str,
        config: GitHubAppConfig,
        release_identity: RuntimeReleaseIdentity,
        process_factory=subprocess.Popen,
    ) -> None:
        if not isinstance(config, GitHubAppConfig):
            raise TypeError("config must be GitHubAppConfig")
        if not isinstance(release_identity, RuntimeReleaseIdentity):
            raise TypeError("release_identity must be RuntimeReleaseIdentity")
        self._broker = broker
        self._lease_id = str(lease_id).strip()
        if not self._lease_id:
            raise ValueError("lease_id must not be empty")
        self._config = config
        self._release_identity = release_identity
        self._process_factory = process_factory
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    def _helper_path(self) -> pathlib.Path:
        root = pathlib.Path(self._release_identity.release_root).resolve()
        helper = (
            root / "src" / "jarvis" / "promotion" / "github_app_helper.py"
        ).resolve()
        try:
            helper.relative_to(root)
        except ValueError as exc:
            raise GitHubPromotionError(
                "github_helper_escape",
                "GitHub helper path escaped the verified release root",
            ) from exc
        if not helper.is_file() or helper.is_symlink():
            raise GitHubPromotionError(
                "github_helper_missing",
                "GitHub App helper is unavailable in the verified release",
            )
        return helper

    def __enter__(self) -> Self:
        with self._lock:
            if self._process is not None:
                raise GitHubPromotionError(
                    "github_session_active",
                    "GitHub App session is already active",
                )
            helper = self._helper_path()
            root = pathlib.Path(self._release_identity.release_root).resolve()
            with self._broker.child_environment(
                self._lease_id,
                consumer_id=_CONSUMER_ID,
            ) as child_env:
                try:
                    process = self._process_factory(
                        [sys.executable, str(helper)],
                        cwd=root,
                        env=dict(child_env),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        encoding="utf-8",
                        errors="strict",
                        bufsize=1,
                    )
                except OSError as exc:
                    raise GitHubPromotionError(
                        "github_helper_launch_failed",
                        "GitHub App helper failed to launch",
                    ) from exc
            self._process = process
            try:
                result = self._rpc(
                    {
                        "op": "bootstrap",
                        "client_id": self._config.client_id,
                        "installation_id": self._config.installation_id,
                        "repository_full_name": self._config.repository_full_name,
                        "base_branch": self._config.base_branch,
                        "workflow_file": self._config.workflow_file,
                        "timeout_seconds": self._config.request_timeout_seconds,
                    }
                )
            except BaseException:
                self.close()
                raise
            if not isinstance(result, dict) or result.get("ready") is not True:
                self.close()
                raise GitHubPromotionError(
                    "github_helper_not_ready",
                    "GitHub App helper did not become ready",
                )
            return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.close()

    def _rpc(self, request: dict[str, object]) -> object:
        with self._lock:
            process = self._process
            if (
                process is None
                or process.stdin is None
                or process.stdout is None
                or process.poll() is not None
            ):
                raise GitHubPromotionError(
                    "github_helper_unavailable",
                    "GitHub App helper session is unavailable",
                )
            rendered = json.dumps(request, separators=(",", ":"), ensure_ascii=False)
            try:
                process.stdin.write(rendered + "\n")
                process.stdin.flush()
                raw = process.stdout.readline()
            except (OSError, UnicodeError) as exc:
                raise GitHubPromotionError(
                    "github_helper_io_failed",
                    "GitHub App helper communication failed",
                ) from exc
            if not raw:
                raise GitHubPromotionError(
                    "github_helper_exited",
                    "GitHub App helper exited unexpectedly",
                )
            try:
                response = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise GitHubPromotionError(
                    "github_helper_invalid_response",
                    "GitHub App helper returned invalid JSON",
                ) from exc
            if not isinstance(response, dict):
                raise GitHubPromotionError(
                    "github_helper_invalid_response",
                    "GitHub App helper returned invalid response",
                )
            if response.get("ok") is not True:
                raise GitHubPromotionError(
                    str(response.get("reason_code") or "github_helper_failed"),
                    str(response.get("message") or "GitHub App helper failed"),
                )
            return response.get("result")

    @staticmethod
    def _pr(payload: object) -> GitHubPullRequestSnapshot:
        if not isinstance(payload, dict):
            raise GitHubPromotionError(
                "pull_request_invalid",
                "GitHub helper returned invalid pull request evidence",
            )
        try:
            return GitHubPullRequestSnapshot(
                number=int(payload["number"]),
                base_sha=str(payload["base_sha"]),
                head_sha=str(payload["head_sha"]),
                draft=bool(payload["draft"]),
                state=str(payload["state"]),
                merged=bool(payload.get("merged", False)),
                merge_sha=(
                    None
                    if payload.get("merge_sha") is None
                    else str(payload["merge_sha"])
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubPromotionError(
                "pull_request_invalid",
                "GitHub helper returned malformed pull request evidence",
            ) from exc

    def publish_candidate(
        self,
        *,
        workspace_root: pathlib.Path,
        branch: str,
        head_sha: str,
    ) -> None:
        result = self._rpc(
            {
                "op": "publish_candidate",
                "workspace_root": str(pathlib.Path(workspace_root).resolve()),
                "branch": branch,
                "head_sha": head_sha,
            }
        )
        if (
            not isinstance(result, dict)
            or result.get("branch") != branch
            or result.get("head_sha") != head_sha
        ):
            raise GitHubPromotionError(
                "candidate_publication_invalid",
                "GitHub helper did not verify exact candidate publication",
            )

    def ensure_pull_request(
        self,
        *,
        branch: str,
        head_sha: str,
        base_sha: str,
        title: str,
        body: str,
    ) -> GitHubPullRequestSnapshot:
        return self._pr(
            self._rpc(
                {
                    "op": "ensure_pull_request",
                    "branch": branch,
                    "head_sha": head_sha,
                    "base_sha": base_sha,
                    "title": title,
                    "body": body,
                }
            )
        )

    def read_pull_request(self, number: int) -> GitHubPullRequestSnapshot:
        return self._pr(self._rpc({"op": "read_pull_request", "number": number}))

    def read_workflow(self, number: int) -> GitHubWorkflowSnapshot:
        payload = self._rpc({"op": "read_workflow", "number": number})
        if not isinstance(payload, dict):
            raise GitHubPromotionError(
                "workflow_invalid",
                "GitHub helper returned invalid workflow evidence",
            )
        raw_checks = payload.get("checks")
        if not isinstance(raw_checks, list):
            raise GitHubPromotionError(
                "workflow_invalid",
                "GitHub helper returned malformed workflow checks",
            )
        try:
            checks = tuple(
                CheckEvidence(
                    context=str(item["context"]),
                    conclusion=str(item["conclusion"]),
                    app_id=(
                        item.get("app_id")
                        if isinstance(item.get("app_id"), int)
                        else None
                    ),
                )
                for item in raw_checks
                if isinstance(item, dict)
            )
            return GitHubWorkflowSnapshot(
                run_id=str(payload["run_id"]),
                event=str(payload["event"]),
                head_sha=str(payload["head_sha"]),
                tested_merge_sha=str(payload["tested_merge_sha"]),
                status=str(payload["status"]),
                conclusion=str(payload["conclusion"]),
                checks=checks,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubPromotionError(
                "workflow_invalid",
                "GitHub helper returned malformed workflow evidence",
            ) from exc

    def read_protected_main_sha(self) -> str:
        payload = self._rpc({"op": "read_protected_main_sha"})
        if not isinstance(payload, dict) or not isinstance(payload.get("sha"), str):
            raise GitHubPromotionError(
                "protected_main_invalid",
                "GitHub helper returned invalid protected-main identity",
            )
        return str(payload["sha"])

    def squash_merge(self, number: int, *, expected_head_sha: str) -> str:
        payload = self._rpc(
            {
                "op": "squash_merge",
                "number": number,
                "expected_head_sha": expected_head_sha,
            }
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("sha"), str):
            raise GitHubPromotionError(
                "merge_response_invalid",
                "GitHub helper returned invalid merge identity",
            )
        return str(payload["sha"])

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            try:
                if (
                    process.poll() is None
                    and process.stdin is not None
                    and process.stdout is not None
                ):
                    process.stdin.write('{"op":"shutdown"}\n')
                    process.stdin.flush()
                    process.stdout.readline()
            except (OSError, UnicodeError):
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)
