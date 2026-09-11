"""Bounded Git operations for JARVIS Hands H5 using Dulwich, never raw shell."""

from __future__ import annotations

import os
import pathlib
import re
import time
from typing import Any, Protocol

from jarvis.authority.types import ActionAttributes, ActionScope
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.local_reads import default_project_root
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_MAX_PATHS = 30
_MAX_COMMIT_MESSAGE = 500


class DevelopmentGitError(ValueError):
    pass


def _parse_roots(raw: str | None) -> dict[str, pathlib.Path]:
    result: dict[str, pathlib.Path] = {}
    if not raw:
        return result
    for entry in raw.split(";"):
        if not entry.strip():
            continue
        if "=" not in entry:
            raise DevelopmentGitError(
                "JARVIS_DEV_REPOSITORIES entries must use alias=path"
            )
        alias, value = entry.split("=", 1)
        key = alias.strip().casefold()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", key):
            raise DevelopmentGitError("invalid development repository alias")
        result[key] = pathlib.Path(value.strip()).expanduser().resolve()
    return result


def _decode_oid(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    return str(value)


def _path_matches(requested: str, observed: str) -> bool:
    requested = pathlib.PurePosixPath(requested).as_posix().rstrip("/")
    observed = pathlib.PurePosixPath(observed).as_posix().rstrip("/")
    return observed == requested or observed.startswith(f"{requested}/")


class ApprovedRepositoryPolicy:
    def __init__(
        self,
        roots: dict[str, str | pathlib.Path] | None = None,
        *,
        jarvis_root: str | pathlib.Path | None = None,
        include_jarvis_read_target: bool = True,
    ) -> None:
        self.jarvis_root = pathlib.Path(jarvis_root or default_project_root()).resolve()
        configured = _parse_roots(os.getenv("JARVIS_DEV_REPOSITORIES"))
        for alias, path in (roots or {}).items():
            configured[str(alias).strip().casefold()] = (
                pathlib.Path(path).expanduser().resolve()
            )
        if include_jarvis_read_target:
            configured.setdefault("jarvis", self.jarvis_root)
        for alias, path in configured.items():
            if not path.is_dir() or not (path / ".git").exists():
                raise DevelopmentGitError(
                    f"development root is not a Git repository: {alias}"
                )
        self._roots = configured

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._roots))

    def resolve(self, alias: str) -> pathlib.Path:
        try:
            return self._roots[str(alias).strip().casefold()]
        except KeyError as exc:
            raise DevelopmentGitError(
                "unknown approved development repository"
            ) from exc

    def is_jarvis(self, path: pathlib.Path) -> bool:
        return path.resolve() == self.jarvis_root

    @staticmethod
    def relative_path(repo: pathlib.Path, value: object) -> str:
        raw = str(value or "").strip()
        pure = pathlib.PurePath(raw)
        if not raw or pure.is_absolute() or pathlib.PureWindowsPath(raw).is_absolute():
            raise DevelopmentGitError("Git path must be a non-empty relative path")
        if any(part in {"..", ".git"} for part in pure.parts):
            raise DevelopmentGitError("Git path traversal/internals are blocked")
        resolved = (repo / raw).resolve(strict=False)
        try:
            relative = resolved.relative_to(repo)
        except ValueError as exc:
            raise DevelopmentGitError("Git path escapes approved repository") from exc
        cursor = repo
        for part in relative.parts:
            cursor /= part
            if cursor.exists() and cursor.is_symlink():
                raise DevelopmentGitError(
                    "symlink paths are blocked from Git Hands mutations"
                )
        return relative.as_posix()


class GitBackend(Protocol):
    def status(self, repo: pathlib.Path) -> dict[str, Any]: ...

    def active_branch(self, repo: pathlib.Path) -> str: ...

    def head_oid(self, repo: pathlib.Path) -> str: ...

    def branch_oid(self, repo: pathlib.Path, branch: str) -> str | None: ...

    def create_branch(self, repo: pathlib.Path, branch: str) -> None: ...

    def stage(self, repo: pathlib.Path, paths: list[str]) -> None: ...

    def commit(self, repo: pathlib.Path, message: str) -> str: ...

    def push_current(self, repo: pathlib.Path) -> dict[str, Any]: ...

    def remote_branch_oid(self, repo: pathlib.Path, branch: str) -> str | None: ...


class DulwichGitBackend:
    @staticmethod
    def _porcelain():
        try:
            from dulwich import porcelain
        except ImportError as exc:
            raise DevelopmentGitError(
                "development Git Hands requires the jarvis[development-hands] extra"
            ) from exc
        return porcelain

    @staticmethod
    def _decode(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _repo(repo: pathlib.Path):
        try:
            from dulwich.repo import Repo
        except ImportError as exc:
            raise DevelopmentGitError(
                "development Git Hands requires the jarvis[development-hands] extra"
            ) from exc
        return Repo(str(repo))

    def status(self, repo: pathlib.Path) -> dict[str, Any]:
        status = self._porcelain().status(str(repo))
        staged = {
            self._decode(kind): [self._decode(path) for path in paths]
            for kind, paths in status.staged.items()
        }
        return {
            "staged": staged,
            "unstaged": [self._decode(path) for path in status.unstaged],
            "untracked": [self._decode(path) for path in status.untracked],
        }

    def active_branch(self, repo: pathlib.Path) -> str:
        return self._decode(self._porcelain().active_branch(str(repo)))

    def head_oid(self, repo: pathlib.Path) -> str:
        return _decode_oid(self._repo(repo).head())

    def branch_oid(self, repo: pathlib.Path, branch: str) -> str | None:
        ref = f"refs/heads/{branch}".encode()
        try:
            return _decode_oid(self._repo(repo).refs[ref])
        except KeyError:
            return None

    def create_branch(self, repo: pathlib.Path, branch: str) -> None:
        self._porcelain().branch_create(str(repo), branch, force=False)

    def stage(self, repo: pathlib.Path, paths: list[str]) -> None:
        self._porcelain().add(str(repo), paths=paths)

    def commit(self, repo: pathlib.Path, message: str) -> str:
        commit_id = self._porcelain().commit(str(repo), message=message.encode("utf-8"))
        return _decode_oid(commit_id)

    def _origin_url(self, repo: pathlib.Path) -> str:
        repository = self._repo(repo)
        try:
            remote = repository.get_config().get((b"remote", b"origin"), b"url")
        except KeyError as exc:
            raise DevelopmentGitError("repository has no origin remote") from exc
        return self._decode(remote)

    def push_current(self, repo: pathlib.Path) -> dict[str, Any]:
        branch = self.active_branch(repo)
        remote_url = self._origin_url(repo)
        ref = f"refs/heads/{branch}:refs/heads/{branch}"
        result = self._porcelain().push(
            str(repo), remote_location=remote_url, refspecs=ref
        )
        return {
            "branch": branch,
            "remote": "origin",
            "remote_url_omitted": True,
            "ref_status": {
                self._decode(key): value
                for key, value in (getattr(result, "ref_status", None) or {}).items()
            },
        }

    def remote_branch_oid(self, repo: pathlib.Path, branch: str) -> str | None:
        try:
            from dulwich.client import get_transport_and_path
        except ImportError as exc:
            raise DevelopmentGitError(
                "development Git Hands requires the jarvis[development-hands] extra"
            ) from exc
        client, remote_path = get_transport_and_path(self._origin_url(repo))
        refs_result = client.get_refs(remote_path)
        refs = getattr(refs_result, "refs", refs_result)
        value = refs.get(f"refs/heads/{branch}".encode())
        return None if value is None else _decode_oid(value)


class DevelopmentGitExecutor:
    capability_key = "development:git"
    operations = (
        "git_active_branch",
        "git_commit",
        "git_create_branch",
        "git_push_current",
        "git_stage_paths",
        "git_status",
    )

    def __init__(
        self,
        policy: ApprovedRepositoryPolicy | None = None,
        backend: GitBackend | None = None,
    ) -> None:
        self.policy = policy or ApprovedRepositoryPolicy()
        self._backend = backend or DulwichGitBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="git",
            source_id="development",
            kind=CapabilityKind.NATIVE_API,
            name="Governed Git project Hands",
            description=(
                "Bounded Git status/branch/stage/commit/push through Dulwich. "
                "JARVIS self-modification remains restricted by canonical authority."
            ),
            operations=list(self.operations),
            metadata={
                "backend": "Dulwich",
                "repo_aliases": list(self.policy.aliases),
                "shell": False,
            },
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        operation = request.operation
        if operation not in self.operations:
            raise DevelopmentGitError("unsupported development Git operation")
        alias = str(request.parameters.get("repo") or "").strip().casefold()
        repo = self.policy.resolve(alias)
        params: dict[str, Any] = {"repo": alias}
        payload: dict[str, Any] = {"repo_path": str(repo)}
        mutating = operation in {
            "git_commit",
            "git_create_branch",
            "git_push_current",
            "git_stage_paths",
        }
        external = operation == "git_push_current"

        if operation == "git_create_branch":
            branch = str(request.parameters.get("branch") or "").strip()
            if (
                not _BRANCH_RE.fullmatch(branch)
                or ".." in branch
                or branch.endswith(("/", ".lock"))
            ):
                raise DevelopmentGitError("Git branch name is invalid")
            params["branch"] = payload["branch"] = branch
        elif operation == "git_stage_paths":
            raw_paths = request.parameters.get("paths")
            if not isinstance(raw_paths, list) or not 1 <= len(raw_paths) <= _MAX_PATHS:
                raise DevelopmentGitError("Git stage requires 1-30 explicit paths")
            paths = [self.policy.relative_path(repo, item) for item in raw_paths]
            params["paths"] = paths
            payload["paths"] = paths
        elif operation == "git_commit":
            message = " ".join(str(request.parameters.get("message") or "").split())
            if not message or len(message) > _MAX_COMMIT_MESSAGE:
                raise DevelopmentGitError("Git commit message is empty or too long")
            params["message"] = payload["message"] = message

        attributes = ActionAttributes(
            private_read=not mutating,
            persistent_write=mutating,
            external_side_effect=external,
            self_modification=mutating and self.policy.is_jarvis(repo),
            scope=ActionScope.LIMITED
            if operation in {"git_stage_paths", "git_push_current"}
            else ActionScope.SINGLE,
        )
        return PreparedCapability(
            request=request,
            target={"domain": "development.git", "repo": alias},
            parameters=params,
            material_summary=f"{operation.replace('_', ' ')} in approved repo: {alias}",
            attributes=attributes,
            execution_payload=payload,
        )

    @staticmethod
    def _stage_verified(paths: list[str], status: dict[str, Any]) -> bool:
        residual = [
            str(path)
            for path in [
                *status.get("unstaged", []),
                *status.get("untracked", []),
            ]
        ]
        return all(
            not any(_path_matches(requested, observed) for observed in residual)
            for requested in paths
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        operation = prepared.request.operation
        repo = pathlib.Path(str(prepared.execution_payload["repo_path"]))
        try:
            verified = True
            if operation == "git_status":
                data = {"status": self._backend.status(repo)}
            elif operation == "git_active_branch":
                data = {"branch": self._backend.active_branch(repo)}
            elif operation == "git_create_branch":
                branch = str(prepared.execution_payload["branch"])
                expected_oid = self._backend.head_oid(repo)
                self._backend.create_branch(repo, branch)
                branch_oid = self._backend.branch_oid(repo, branch)
                verified = bool(branch_oid) and branch_oid == expected_oid
                data = {
                    "branch": branch,
                    "branch_oid": branch_oid,
                    "created": verified,
                }
            elif operation == "git_stage_paths":
                paths = list(prepared.execution_payload["paths"])
                self._backend.stage(repo, paths)
                status = self._backend.status(repo)
                verified = self._stage_verified(paths, status)
                data = {"paths": paths, "status": status}
            elif operation == "git_commit":
                commit_id = self._backend.commit(
                    repo, str(prepared.execution_payload["message"])
                )
                head_oid = self._backend.head_oid(repo)
                verified = bool(commit_id) and head_oid == commit_id
                data = {"commit": commit_id, "head": head_oid}
            else:
                data = self._backend.push_current(repo)
                branch = str(data["branch"])
                local_oid = self._backend.head_oid(repo)
                remote_oid = self._backend.remote_branch_oid(repo, branch)
                verified = bool(remote_oid) and remote_oid == local_oid
                data.update({"local_oid": local_oid, "remote_oid": remote_oid})
        except Exception as exc:  # noqa: BLE001 - executor boundary contains backend faults
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=operation,
                data={},
                reason=str(exc),
                elapsed_ms=(time.monotonic() - started) * 1000.0,
                provenance=("Dulwich pure-Python Git",),
            )

        data["verification_passed"] = verified
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            capability_key=self.capability_key,
            operation=operation,
            data=data,
            reason=None if verified else "Git post-action verification failed",
            elapsed_ms=(time.monotonic() - started) * 1000.0,
            provenance=("Dulwich pure-Python Git",),
        )
