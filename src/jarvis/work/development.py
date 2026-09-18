"""Isolated staged development substrate for JARVIS background work.

This module deliberately does not expose arbitrary shell, package installation, push,
merge, or production-tree writes. The owner-authorized WorkItem may stage reversible
source changes only inside its own Git worktree. Promotion remains a separate governed
operation.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from jarvis.capabilities.local_reads import default_project_root
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import default_work_state_dir

_MAX_READ_CHARS = 40_000
_MAX_WRITE_BYTES = 1_000_000
_MAX_TEST_SECONDS = 300.0
_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9._/-]+")
_BLOCKED_NAMES = frozenset({
    ".env",
    "credentials",
    "credentials.json",
    "secrets",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
})
_BLOCKED_SUFFIXES = frozenset({".pem", ".p12", ".pfx", ".key", ".kdbx"})


class DevelopmentWorkspaceError(RuntimeError):
    pass


def _safe_work_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "-", value).strip("-")
    if not normalized:
        raise DevelopmentWorkspaceError("work id cannot form workspace name")
    return normalized[:80]


def _is_sensitive(path: pathlib.PurePath) -> bool:
    for part in path.parts:
        name = part.casefold()
        if name in _BLOCKED_NAMES or name.startswith((".env", "credentials", "secrets")):
            return True
        if pathlib.PurePath(name).suffix in _BLOCKED_SUFFIXES:
            return True
    return False


@dataclass(frozen=True, slots=True)
class DevelopmentWorkspace:
    work_id: str
    branch: str
    path: pathlib.Path


class DevelopmentWorkspaceManager:
    """Create one deterministic Git worktree per development WorkItem."""

    def __init__(
        self,
        *,
        repository_root: str | pathlib.Path | None = None,
        workspace_root: str | pathlib.Path | None = None,
    ) -> None:
        self.repository_root = pathlib.Path(
            repository_root or default_project_root()
        ).resolve()
        self.workspace_root = pathlib.Path(
            workspace_root or (default_work_state_dir() / "worktrees")
        ).resolve()
        if not (self.repository_root / ".git").exists():
            raise DevelopmentWorkspaceError("JARVIS source root is not a Git repository")
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _run(
        cwd: pathlib.Path,
        *args: str,
        timeout: float = 60.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        git = shutil.which("git")
        if git is None:
            raise DevelopmentWorkspaceError("Git executable is unavailable")
        try:
            return subprocess.run(
                [git, *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=check,
                shell=False,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise DevelopmentWorkspaceError(str(exc)) from exc

    def workspace_for(self, work_id: str) -> DevelopmentWorkspace:
        token = _safe_work_id(work_id)
        branch = f"jarvis/work/{token}"
        path = (self.workspace_root / token).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise DevelopmentWorkspaceError("workspace path escaped approved root") from exc
        return DevelopmentWorkspace(work_id=work_id, branch=branch, path=path)

    def ensure(self, work_id: str) -> DevelopmentWorkspace:
        workspace = self.workspace_for(work_id)
        if (workspace.path / ".git").exists() or (workspace.path / ".git").is_file():
            return workspace
        if workspace.path.exists():
            raise DevelopmentWorkspaceError("workspace path exists but is not a Git worktree")

        branch_check = self._run(
            self.repository_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{workspace.branch}",
            check=False,
        )
        args = ["worktree", "add"]
        if branch_check.returncode == 0:
            args.extend([str(workspace.path), workspace.branch])
        else:
            args.extend(["-b", workspace.branch, str(workspace.path), "HEAD"])
        self._run(self.repository_root, *args, timeout=120.0)
        if not workspace.path.is_dir():
            raise DevelopmentWorkspaceError("Git worktree creation was not verified")
        return workspace

    def resolve(self, work_id: str, relative_path: str, *, require_file: bool = False) -> pathlib.Path:
        workspace = self.workspace_for(work_id)
        if not workspace.path.is_dir():
            raise DevelopmentWorkspaceError("development workspace is not prepared")
        raw = str(relative_path or "").strip()
        pure = pathlib.PurePath(raw)
        if not raw or pure.is_absolute() or pathlib.PureWindowsPath(raw).is_absolute():
            raise DevelopmentWorkspaceError("development path must be relative")
        if any(part in {"..", ".git"} for part in pure.parts):
            raise DevelopmentWorkspaceError("development path traversal/internals are blocked")
        if _is_sensitive(pure):
            raise DevelopmentWorkspaceError("credential/secret-like development path is blocked")
        target = (workspace.path / raw).resolve(strict=False)
        try:
            target.relative_to(workspace.path)
        except ValueError as exc:
            raise DevelopmentWorkspaceError("development path escaped worktree") from exc
        cursor = workspace.path
        for part in target.relative_to(workspace.path).parts:
            cursor /= part
            if cursor.exists() and cursor.is_symlink():
                raise DevelopmentWorkspaceError("symlink paths are blocked")
        if require_file and not target.is_file():
            raise DevelopmentWorkspaceError("development target is not a regular file")
        return target

    def status(self, work_id: str) -> dict[str, Any]:
        workspace = self.workspace_for(work_id)
        if not workspace.path.is_dir():
            return {"prepared": False, "branch": workspace.branch}
        result = self._run(workspace.path, "status", "--porcelain=v1", "--branch")
        return {
            "prepared": True,
            "branch": workspace.branch,
            "status": result.stdout[:20_000],
        }


class PrepareDevelopmentWorkspaceExecutor:
    descriptor = BrainAction(
        name="dev_prepare_workspace",
        description=(
            "Prepare or reopen this WorkItem's isolated Git worktree. This does not "
            "modify protected main and should precede source inspection or edits."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        del parameters
        workspace = await asyncio.to_thread(self._manager.ensure, work.work_id)
        return {
            "prepared": True,
            "branch": workspace.branch,
            "workspace_token": workspace.path.name,
            "production_tree_modified": False,
        }


class DevelopmentReadFileExecutor:
    descriptor = BrainAction(
        name="dev_read_file",
        description="Read one non-sensitive UTF-8 source file from this WorkItem's worktree.",
        parameter_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._manager.resolve(work.work_id, str(parameters.get("path") or ""), require_file=True)
        if target.stat().st_size > _MAX_WRITE_BYTES:
            raise DevelopmentWorkspaceError("development file exceeds read limit")
        text = await asyncio.to_thread(target.read_text, encoding="utf-8")
        truncated = len(text) > _MAX_READ_CHARS
        return {
            "path": target.relative_to(self._manager.workspace_for(work.work_id).path).as_posix(),
            "text": text[:_MAX_READ_CHARS],
            "truncated": truncated,
        }


class DevelopmentListFilesExecutor:
    descriptor = BrainAction(
        name="dev_list_files",
        description="List tracked and untracked non-sensitive files in this WorkItem's worktree.",
        parameter_schema={
            "type": "object",
            "properties": {"max_results": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        workspace = self._manager.workspace_for(work.work_id)
        if not workspace.path.is_dir():
            raise DevelopmentWorkspaceError("development workspace is not prepared")
        limit = int(parameters.get("max_results", 80))
        limit = max(1, min(limit, 100))
        result = await asyncio.to_thread(
            self._manager._run,
            workspace.path,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        files: list[str] = []
        for raw in result.stdout.split("\x00"):
            if not raw:
                continue
            pure = pathlib.PurePosixPath(raw)
            if _is_sensitive(pure):
                continue
            files.append(pure.as_posix())
            if len(files) >= limit:
                break
        return {"files": files, "max_results": limit}


class DevelopmentSearchExecutor:
    descriptor = BrainAction(
        name="dev_search",
        description="Search text inside the isolated worktree without executing project code.",
        parameter_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 300},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        workspace = self._manager.workspace_for(work.work_id)
        if not workspace.path.is_dir():
            raise DevelopmentWorkspaceError("development workspace is not prepared")
        query = str(parameters.get("query") or "").strip()
        if not query:
            raise DevelopmentWorkspaceError("development search query is empty")
        limit = max(1, min(int(parameters.get("max_results", 20)), 50))
        rg = shutil.which("rg")
        matches: list[str] = []
        if rg is not None:
            completed = await asyncio.to_thread(
                subprocess.run,
                [rg, "--line-number", "--fixed-strings", "--no-messages", query, "."],
                cwd=workspace.path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30.0,
                check=False,
                shell=False,
            )
            if completed.returncode not in {0, 1}:
                raise DevelopmentWorkspaceError("ripgrep search failed")
            matches = completed.stdout.splitlines()[:limit]
        else:
            for path in workspace.path.rglob("*"):
                if len(matches) >= limit:
                    break
                if not path.is_file():
                    continue
                relative = path.relative_to(workspace.path)
                if _is_sensitive(relative) or ".git" in relative.parts:
                    continue
                try:
                    if path.stat().st_size > _MAX_WRITE_BYTES:
                        continue
                    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                        if query in line:
                            matches.append(f"{relative.as_posix()}:{number}:{line[:500]}")
                            if len(matches) >= limit:
                                break
                except (OSError, UnicodeError):
                    continue
        return {"query": query, "matches": matches, "max_results": limit}


class DevelopmentWriteFileExecutor:
    descriptor = BrainAction(
        name="dev_write_file",
        description=(
            "Create or replace one UTF-8 source file only inside this WorkItem's isolated "
            "worktree. This is staged development, never protected-main mutation."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                "text": {"type": "string", "maxLength": 200000},
            },
            "required": ["path", "text"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        text = str(parameters.get("text") or "")
        encoded = text.encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise DevelopmentWorkspaceError("development write exceeds size limit")
        target = self._manager.resolve(work.work_id, str(parameters.get("path") or ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.jarvis-{os.getpid()}.tmp")
        await asyncio.to_thread(temporary.write_text, text, encoding="utf-8", newline="")
        await asyncio.to_thread(os.replace, temporary, target)
        observed = await asyncio.to_thread(target.read_bytes)
        if observed != encoded:
            raise DevelopmentWorkspaceError("development write verification failed")
        return {
            "path": target.relative_to(self._manager.workspace_for(work.work_id).path).as_posix(),
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "production_tree_modified": False,
        }


class DevelopmentRunTestsExecutor:
    descriptor = BrainAction(
        name="dev_run_tests",
        description=(
            "Run bounded pytest inside this WorkItem's isolated worktree. Only pytest "
            "targets are accepted; arbitrary shell commands are not available."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                    "maxItems": 20,
                },
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 300},
            },
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        workspace = self._manager.workspace_for(work.work_id)
        if not workspace.path.is_dir():
            raise DevelopmentWorkspaceError("development workspace is not prepared")
        raw_targets = parameters.get("targets") or ["tests"]
        if not isinstance(raw_targets, list) or len(raw_targets) > 20:
            raise DevelopmentWorkspaceError("invalid pytest target list")
        targets: list[str] = []
        for value in raw_targets:
            text = str(value).strip()
            pure = pathlib.PurePath(text.split("::", 1)[0])
            if (
                not text
                or pure.is_absolute()
                or pathlib.PureWindowsPath(str(pure)).is_absolute()
                or ".." in pure.parts
            ):
                raise DevelopmentWorkspaceError("pytest target must remain inside worktree")
            targets.append(text)
        timeout = min(max(float(parameters.get("timeout_seconds", 120.0)), 1.0), _MAX_TEST_SECONDS)
        command = [sys.executable, "-m", "pytest", "-q", *targets]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=workspace.path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "timed_out": True,
                "timeout_seconds": timeout,
                "output": "pytest timed out",
            }
        combined = (completed.stdout + "\n" + completed.stderr).strip()
        return {
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "timed_out": False,
            "output": combined[-20_000:],
            "command": ["python", "-m", "pytest", "-q", *targets],
        }


class DevelopmentStatusExecutor:
    descriptor = BrainAction(
        name="dev_status",
        description="Read Git status for this WorkItem's isolated development worktree.",
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self, manager: DevelopmentWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(self, *, work: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        del parameters
        return await asyncio.to_thread(self._manager.status, work.work_id)


def build_development_executors(
    manager: DevelopmentWorkspaceManager,
) -> tuple[object, ...]:
    return (
        PrepareDevelopmentWorkspaceExecutor(manager),
        DevelopmentListFilesExecutor(manager),
        DevelopmentReadFileExecutor(manager),
        DevelopmentSearchExecutor(manager),
        DevelopmentWriteFileExecutor(manager),
        DevelopmentRunTestsExecutor(manager),
        DevelopmentStatusExecutor(manager),
    )
