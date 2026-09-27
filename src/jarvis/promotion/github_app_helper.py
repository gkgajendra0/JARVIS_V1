"""Trusted child-only GitHub App transport for Phase 7.

The private key is supplied only through SecretBroker child environment, removed
from the child environment immediately, and never emitted in RPC responses/logs.
All network/Git operations are fixed and typed; this module exposes no generic shell.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_API_ROOT = "https://api.github.com"
_API_VERSION = "2026-03-10"
_SECRET_ENV = "JARVIS_GITHUB_APP_PRIVATE_KEY"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_RESPONSE_BYTES = 2_000_000


class HelperError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not self.reason_code or not text:
            raise ValueError("helper errors require a reason code and message")
        super().__init__(text)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _github_jwt(private_key_pem: str, client_id: str, *, now: int | None = None) -> str:
    client = str(client_id).strip()
    if not client:
        raise HelperError("client_id_missing", "GitHub App client ID is missing")
    timestamp = int(time.time() if now is None else now)
    header = _b64url(_json_bytes({"alg": "RS256", "typ": "JWT"}))
    payload = _b64url(
        _json_bytes(
            {
                "iat": timestamp - 60,
                "exp": timestamp + 540,
                "iss": client,
            }
        )
    )
    material = f"{header}.{payload}".encode("ascii")
    try:
        key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
        signature = key.sign(
            material,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (TypeError, ValueError) as exc:
        raise HelperError(
            "private_key_invalid",
            "GitHub App private key is invalid",
        ) from exc
    return f"{header}.{payload}.{_b64url(signature)}"


def _require_sha(value: object, *, field: str) -> str:
    text = str(value or "").strip().casefold()
    if _GIT_SHA.fullmatch(text) is None:
        raise HelperError("invalid_git_sha", f"{field} is not an exact Git SHA")
    return text


def _require_branch(value: object) -> str:
    branch = str(value or "").strip()
    if (
        _BRANCH.fullmatch(branch) is None
        or ".." in branch
        or branch.endswith(("/", ".lock"))
    ):
        raise HelperError("invalid_branch", "candidate branch is invalid")
    return branch


def _request_json(
    method: str,
    path: str,
    *,
    authorization: str,
    body: object | None = None,
    query: dict[str, object] | None = None,
    accepted_statuses: tuple[int, ...] = (200,),
    timeout_seconds: float = 20.0,
) -> tuple[int, object | None]:
    url = _API_ROOT + path
    if query:
        url += "?" + urllib.parse.urlencode(
            {key: str(value) for key, value in query.items()}
        )
    data = None if body is None else _json_bytes(body)
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": authorization,
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "JARVIS-Phase7-Promotion",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if status in accepted_statuses:
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
        else:
            raise HelperError(
                f"github_http_{status}",
                f"GitHub API rejected {method} {path} with HTTP {status}",
            ) from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise HelperError(
            "github_unavailable",
            f"GitHub API request failed for {method} {path}",
        ) from exc
    if status not in accepted_statuses:
        raise HelperError(
            f"github_http_{status}",
            f"GitHub API returned unexpected HTTP {status}",
        )
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise HelperError("github_response_too_large", "GitHub response exceeded limit")
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HelperError(
            "github_response_invalid",
            "GitHub API returned invalid JSON",
        ) from exc


def _installation_token(
    *,
    private_key_pem: str,
    client_id: str,
    installation_id: int,
    repository_name: str,
    timeout_seconds: float,
) -> str:
    if type(installation_id) is not int or installation_id <= 0:
        raise HelperError(
            "installation_id_invalid",
            "GitHub App installation ID must be positive",
        )
    jwt = _github_jwt(private_key_pem, client_id)
    _, payload = _request_json(
        "POST",
        f"/app/installations/{installation_id}/access_tokens",
        authorization=f"Bearer {jwt}",
        body={
            "repositories": [repository_name],
            "permissions": {
                "actions": "read",
                "checks": "read",
                "contents": "write",
                "pull_requests": "write",
            },
        },
        accepted_statuses=(201,),
        timeout_seconds=timeout_seconds,
    )
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise HelperError(
            "installation_token_missing",
            "GitHub did not return an installation access token",
        )
    return token.strip()


class _Session:
    def __init__(
        self,
        *,
        repository_full_name: str,
        base_branch: str,
        workflow_file: str,
        token: str,
        timeout_seconds: float,
    ) -> None:
        repository = str(repository_full_name).strip()
        if _REPOSITORY.fullmatch(repository) is None:
            raise HelperError(
                "repository_invalid",
                "repository must use owner/name form",
            )
        owner, name = repository.split("/", 1)
        self.owner = owner
        self.name = name
        self.repository = repository
        self.base_branch = _require_branch(base_branch)
        workflow = pathlib.PurePosixPath(str(workflow_file).strip())
        if (
            not workflow.name
            or workflow.is_absolute()
            or ".." in workflow.parts
            or len(workflow.parts) != 1
        ):
            raise HelperError(
                "workflow_invalid",
                "workflow file must be one basename",
            )
        self.workflow_file = workflow.name
        self._authorization = f"Bearer {token}"
        self._timeout = float(timeout_seconds)

    @property
    def _repo_path(self) -> str:
        return f"/repos/{self.owner}/{self.name}"

    def _api(
        self,
        method: str,
        suffix: str,
        *,
        body: object | None = None,
        query: dict[str, object] | None = None,
        accepted_statuses: tuple[int, ...] = (200,),
    ) -> tuple[int, object | None]:
        return _request_json(
            method,
            self._repo_path + suffix,
            authorization=self._authorization,
            body=body,
            query=query,
            accepted_statuses=accepted_statuses,
            timeout_seconds=self._timeout,
        )

    def _ref_sha(self, branch: str) -> str | None:
        encoded = urllib.parse.quote(_require_branch(branch), safe="")
        status, payload = self._api(
            "GET",
            f"/git/ref/heads/{encoded}",
            accepted_statuses=(200, 404),
        )
        if status == 404:
            return None
        try:
            return _require_sha(payload["object"]["sha"], field="remote branch SHA")
        except (KeyError, TypeError) as exc:
            raise HelperError(
                "remote_ref_invalid",
                "GitHub branch ref payload is malformed",
            ) from exc

    def protected_main_sha(self) -> str:
        sha = self._ref_sha(self.base_branch)
        if sha is None:
            raise HelperError(
                "protected_main_missing",
                "protected base branch is missing",
            )
        return sha

    @staticmethod
    def _git(root: pathlib.Path, *args: str) -> str:
        git = shutil.which("git")
        if git is None:
            raise HelperError("git_unavailable", "Git executable is unavailable")
        try:
            completed = subprocess.run(
                [git, "-C", str(root), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60.0,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HelperError("git_failed", "fixed Git operation failed") from exc
        if completed.returncode != 0:
            raise HelperError("git_failed", "fixed Git operation returned failure")
        return completed.stdout.strip()

    def publish_candidate(
        self,
        *,
        workspace_root: str,
        branch: str,
        head_sha: str,
    ) -> dict[str, object]:
        workspace = pathlib.Path(workspace_root).expanduser().resolve()
        branch = _require_branch(branch)
        head_sha = _require_sha(head_sha, field="candidate head SHA")
        if not workspace.is_dir() or not (workspace / ".git").exists():
            raise HelperError(
                "candidate_workspace_invalid",
                "candidate workspace is not a Git worktree",
            )
        if (
            _require_sha(self._git(workspace, "rev-parse", "HEAD"), field="local HEAD")
            != head_sha
        ):
            raise HelperError(
                "candidate_workspace_mismatch",
                "candidate workspace HEAD differs from approved commit",
            )
        if self._git(workspace, "branch", "--show-current") != branch:
            raise HelperError(
                "candidate_branch_mismatch",
                "candidate workspace branch differs from approved branch",
            )
        if self._git(
            workspace,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ):
            raise HelperError(
                "candidate_workspace_dirty",
                "candidate workspace is not clean",
            )
        existing = self._ref_sha(branch)
        if existing is not None:
            if existing != head_sha:
                raise HelperError(
                    "remote_candidate_ref_conflict",
                    "remote candidate branch already points to another commit",
                )
            return {"branch": branch, "head_sha": head_sha, "published": False}

        basic = base64.b64encode(
            f"x-access-token:{self._authorization.removeprefix('Bearer ')}".encode(
                "utf-8"
            )
        ).decode("ascii")
        git = shutil.which("git")
        if git is None:
            raise HelperError("git_unavailable", "Git executable is unavailable")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        try:
            completed = subprocess.run(
                [
                    git,
                    "-C",
                    str(workspace),
                    "push",
                    "--porcelain",
                    f"https://github.com/{self.repository}.git",
                    f"{head_sha}:refs/heads/{branch}",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120.0,
                check=False,
                shell=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HelperError(
                "candidate_push_failed",
                "exact candidate publication failed",
            ) from exc
        finally:
            environment["GIT_CONFIG_VALUE_0"] = ""
            basic = ""
        if completed.returncode != 0:
            raise HelperError(
                "candidate_push_failed",
                "exact candidate publication was rejected",
            )
        observed = self._ref_sha(branch)
        if observed != head_sha:
            raise HelperError(
                "candidate_push_verification_failed",
                "remote candidate branch does not equal approved commit",
            )
        return {"branch": branch, "head_sha": head_sha, "published": True}

    @staticmethod
    def _pull_snapshot(payload: object) -> dict[str, object]:
        try:
            number = int(payload["number"])
            base_sha = _require_sha(payload["base"]["sha"], field="PR base SHA")
            head_sha = _require_sha(payload["head"]["sha"], field="PR head SHA")
            state = str(payload["state"])
            draft = bool(payload.get("draft", False))
            merged = bool(payload.get("merged", False))
            merge_sha = payload.get("merge_commit_sha") if merged else None
            if merge_sha is not None:
                merge_sha = _require_sha(merge_sha, field="PR merge SHA")
        except (KeyError, TypeError, ValueError) as exc:
            raise HelperError(
                "pull_request_invalid",
                "GitHub pull request payload is malformed",
            ) from exc
        return {
            "number": number,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "draft": draft,
            "state": state,
            "merged": merged,
            "merge_sha": merge_sha,
        }

    def read_pull_request(self, number: int) -> dict[str, object]:
        if type(number) is not int or number <= 0:
            raise HelperError("pr_number_invalid", "PR number must be positive")
        _, payload = self._api("GET", f"/pulls/{number}")
        return self._pull_snapshot(payload)

    def ensure_pull_request(
        self,
        *,
        branch: str,
        head_sha: str,
        base_sha: str,
        title: str,
        body: str,
    ) -> dict[str, object]:
        branch = _require_branch(branch)
        head_sha = _require_sha(head_sha, field="candidate head SHA")
        base_sha = _require_sha(base_sha, field="candidate base SHA")
        if self.protected_main_sha() != base_sha:
            raise HelperError(
                "stale_candidate_base",
                "protected main no longer equals candidate base",
            )
        if self._ref_sha(branch) != head_sha:
            raise HelperError(
                "remote_candidate_missing",
                "candidate branch is not published at the exact head SHA",
            )
        _, payload = self._api(
            "GET",
            "/pulls",
            query={
                "state": "open",
                "head": f"{self.owner}:{branch}",
                "base": self.base_branch,
                "per_page": 100,
            },
        )
        pulls = payload if isinstance(payload, list) else []
        if len(pulls) > 1:
            raise HelperError(
                "duplicate_candidate_pr",
                "multiple open pull requests exist for candidate branch",
            )
        if pulls:
            snapshot = self._pull_snapshot(pulls[0])
        else:
            _, created = self._api(
                "POST",
                "/pulls",
                body={
                    "title": str(title).strip(),
                    "head": branch,
                    "base": self.base_branch,
                    "body": str(body),
                    "draft": False,
                },
                accepted_statuses=(201,),
            )
            snapshot = self._pull_snapshot(created)
        if snapshot["base_sha"] != base_sha or snapshot["head_sha"] != head_sha:
            raise HelperError(
                "pull_request_identity_mismatch",
                "pull request does not bind the exact candidate/base",
            )
        return snapshot

    def read_workflow(self, number: int) -> dict[str, object]:
        if type(number) is not int or number <= 0:
            raise HelperError("pr_number_invalid", "PR number must be positive")
        workflow = urllib.parse.quote(self.workflow_file, safe="")
        _, payload = self._api(
            "GET",
            f"/actions/workflows/{workflow}/runs",
            query={"event": "pull_request", "per_page": 100},
        )
        raw_runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
        candidates: list[tuple[int, int, dict[str, Any], str]] = []
        for raw in raw_runs:
            if not isinstance(raw, dict):
                continue
            pull_requests = raw.get("pull_requests")
            if not isinstance(pull_requests, list):
                continue
            for pr in pull_requests:
                if not isinstance(pr, dict) or pr.get("number") != number:
                    continue
                head = pr.get("head")
                if not isinstance(head, dict):
                    raise HelperError(
                        "workflow_pr_identity_missing",
                        "workflow run lacks PR head identity",
                    )
                candidate_head = _require_sha(
                    head.get("sha"),
                    field="workflow PR head SHA",
                )
                candidates.append(
                    (
                        int(raw.get("run_number") or 0),
                        int(raw.get("run_attempt") or 0),
                        raw,
                        candidate_head,
                    )
                )
        if not candidates:
            raise HelperError(
                "workflow_missing",
                "no Code Quality workflow run is bound to this pull request",
            )
        _, _, selected, candidate_head = max(
            candidates,
            key=lambda item: (item[0], item[1]),
        )
        tested_merge_sha = _require_sha(
            selected.get("head_sha"),
            field="workflow tested merge SHA",
        )
        status = str(selected.get("status") or "").casefold()
        conclusion = str(selected.get("conclusion") or "").casefold()
        checks: list[dict[str, object]] = []
        if tested_merge_sha:
            _, check_payload = self._api(
                "GET",
                f"/commits/{tested_merge_sha}/check-runs",
                query={"filter": "latest", "per_page": 100},
            )
            raw_checks = (
                check_payload.get("check_runs", [])
                if isinstance(check_payload, dict)
                else []
            )
            for check in raw_checks:
                if not isinstance(check, dict):
                    continue
                name = str(check.get("name") or "").strip()
                check_conclusion = str(check.get("conclusion") or "").casefold()
                app = check.get("app")
                app_id = app.get("id") if isinstance(app, dict) else None
                if name and check_conclusion:
                    checks.append(
                        {
                            "context": name,
                            "conclusion": check_conclusion,
                            "app_id": app_id if isinstance(app_id, int) else None,
                        }
                    )
        return {
            "run_id": str(selected.get("id") or ""),
            "event": str(selected.get("event") or ""),
            "head_sha": candidate_head,
            "tested_merge_sha": tested_merge_sha,
            "status": status,
            "conclusion": conclusion,
            "checks": checks,
        }

    def squash_merge(self, number: int, *, expected_head_sha: str) -> str:
        expected = _require_sha(expected_head_sha, field="expected head SHA")
        _, payload = self._api(
            "PUT",
            f"/pulls/{number}/merge",
            body={"sha": expected, "merge_method": "squash"},
        )
        if not isinstance(payload, dict) or payload.get("merged") is not True:
            raise HelperError(
                "merge_rejected",
                "GitHub did not merge the exact approved pull request",
            )
        return _require_sha(payload.get("sha"), field="merge SHA")


def _reply(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _command(session: _Session, request: dict[str, object]) -> object:
    op = str(request.get("op") or "").strip()
    if op == "publish_candidate":
        return session.publish_candidate(
            workspace_root=str(request.get("workspace_root") or ""),
            branch=str(request.get("branch") or ""),
            head_sha=str(request.get("head_sha") or ""),
        )
    if op == "ensure_pull_request":
        return session.ensure_pull_request(
            branch=str(request.get("branch") or ""),
            head_sha=str(request.get("head_sha") or ""),
            base_sha=str(request.get("base_sha") or ""),
            title=str(request.get("title") or ""),
            body=str(request.get("body") or ""),
        )
    if op == "read_pull_request":
        return session.read_pull_request(int(request.get("number") or 0))
    if op == "read_workflow":
        return session.read_workflow(int(request.get("number") or 0))
    if op == "read_protected_main_sha":
        return {"sha": session.protected_main_sha()}
    if op == "squash_merge":
        return {
            "sha": session.squash_merge(
                int(request.get("number") or 0),
                expected_head_sha=str(request.get("expected_head_sha") or ""),
            )
        }
    if op == "shutdown":
        return {"shutdown": True}
    raise HelperError("operation_not_allowed", "unregistered GitHub helper operation")


def main() -> int:
    private_key = os.environ.pop(_SECRET_ENV, "")
    if not private_key:
        _reply(
            {
                "ok": False,
                "reason_code": "private_key_missing",
                "message": "GitHub App private key was not supplied",
            }
        )
        return 2
    try:
        first = sys.stdin.readline()
        if not first:
            raise HelperError("bootstrap_missing", "GitHub helper bootstrap is missing")
        bootstrap = json.loads(first)
        if not isinstance(bootstrap, dict) or bootstrap.get("op") != "bootstrap":
            raise HelperError("bootstrap_invalid", "GitHub helper bootstrap is invalid")
        repository = str(bootstrap.get("repository_full_name") or "").strip()
        if _REPOSITORY.fullmatch(repository) is None:
            raise HelperError(
                "repository_invalid", "repository must use owner/name form"
            )
        repository_name = repository.split("/", 1)[1]
        timeout_seconds = float(bootstrap.get("timeout_seconds") or 20.0)
        if not 1.0 <= timeout_seconds <= 60.0:
            raise HelperError(
                "timeout_invalid",
                "GitHub helper timeout must be within 1-60 seconds",
            )
        token = _installation_token(
            private_key_pem=private_key,
            client_id=str(bootstrap.get("client_id") or ""),
            installation_id=int(bootstrap.get("installation_id") or 0),
            repository_name=repository_name,
            timeout_seconds=timeout_seconds,
        )
        private_key = ""
        session = _Session(
            repository_full_name=repository,
            base_branch=str(bootstrap.get("base_branch") or "main"),
            workflow_file=str(bootstrap.get("workflow_file") or "code-quality.yml"),
            token=token,
            timeout_seconds=timeout_seconds,
        )
        _reply({"ok": True, "result": {"ready": True}})
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise HelperError(
                        "request_invalid",
                        "GitHub helper request must be an object",
                    )
                result = _command(session, request)
                _reply({"ok": True, "result": result})
                if request.get("op") == "shutdown":
                    return 0
            except HelperError as exc:
                _reply(
                    {
                        "ok": False,
                        "reason_code": exc.reason_code,
                        "message": str(exc),
                    }
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                _reply(
                    {
                        "ok": False,
                        "reason_code": "request_invalid",
                        "message": "GitHub helper request is invalid",
                    }
                )
        return 0
    except HelperError as exc:
        _reply(
            {
                "ok": False,
                "reason_code": exc.reason_code,
                "message": str(exc),
            }
        )
        return 2
    except (TypeError, ValueError, json.JSONDecodeError):
        _reply(
            {
                "ok": False,
                "reason_code": "bootstrap_invalid",
                "message": "GitHub helper bootstrap is invalid",
            }
        )
        return 2
    finally:
        private_key = ""


if __name__ == "__main__":
    raise SystemExit(main())
