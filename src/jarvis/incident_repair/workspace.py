"""Read-only exact-revision diagnostic workspaces for Phase 6."""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.capabilities.local_reads import default_project_root
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.brain import BrainAction
from jarvis.work.development import _contains_secret, _is_sensitive, _safe_work_id
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import default_work_state_dir

_MAX_READ_CHARS = 40_000
_MAX_FILE_BYTES = 1_000_000
_MAX_SEARCH_RESULTS = 50
_MAX_HISTORY_RESULTS = 50
_MAX_BISECT_COMMITS = 512
_GIT_OBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class DiagnosticWorkspaceError(RuntimeError):
    """A diagnostic workspace request violated the read-only workspace contract."""


class DiagnosticRevisionResolver(Protocol):
    def revision_for(self, work_id: str) -> str: ...


@dataclass(frozen=True, slots=True)
class DiagnosticWorkspace:
    work_id: str
    revision: str
    path: pathlib.Path


class ChangeStoreDiagnosticRevisionResolver:
    """Resolve the immutable source revision from the owning EngineeringChange."""

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    def revision_for(self, work_id: str) -> str:
        stage = self._store.stage_for_work(str(work_id).strip())
        if stage is None:
            raise DiagnosticWorkspaceError(
                "diagnostic WorkItem is not linked to an EngineeringChange"
            )
        change = self._store.require(stage.change_id)
        process = self._store.process_contract(
            change.process_key,
            change.process_version,
        )
        if stage.stage_key != process.architecture_source_stage.stage_key:
            raise DiagnosticWorkspaceError(
                "diagnostic workspace is only valid for architecture-source work"
            )
        artifact = self._store.latest_artifact(
            change.change_id,
            "incident_repair_trigger",
        )
        if artifact is None:
            raise DiagnosticWorkspaceError(
                "incident repair trigger artifact is missing"
            )
        revision = str(artifact.payload.get("source_revision") or "").strip().lower()
        if _GIT_OBJECT.fullmatch(revision) is None:
            raise DiagnosticWorkspaceError(
                "incident repair trigger lacks an exact Git source revision"
            )
        return revision


class DiagnosticWorkspaceManager:
    """Create/reopen one detached, exact-revision worktree per DIAGNOSTICS WorkItem."""

    def __init__(
        self,
        revision_resolver: DiagnosticRevisionResolver,
        *,
        repository_root: str | pathlib.Path | None = None,
        workspace_root: str | pathlib.Path | None = None,
    ) -> None:
        self._revision_resolver = revision_resolver
        self.repository_root = pathlib.Path(
            repository_root or default_project_root()
        ).resolve()
        self.workspace_root = pathlib.Path(
            workspace_root or (default_work_state_dir() / "diagnostics")
        ).resolve()
        if not (self.repository_root / ".git").exists():
            raise DiagnosticWorkspaceError(
                "JARVIS source root is not a Git repository"
            )
        if self.workspace_root == self.repository_root:
            raise DiagnosticWorkspaceError(
                "diagnostic workspace root cannot be protected main"
            )
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._disabled_hooks_root = (
            self.workspace_root / ".disabled-git-hooks"
        ).resolve()
        self._disabled_hooks_root.mkdir(parents=True, exist_ok=True)

    def _run(
        self,
        cwd: pathlib.Path,
        *args: str,
        timeout: float = 60.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        git = shutil.which("git")
        if git is None:
            raise DiagnosticWorkspaceError("Git executable is unavailable")
        try:
            return subprocess.run(
                [
                    git,
                    "-c",
                    f"core.hooksPath={self._disabled_hooks_root}",
                    *args,
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=check,
                shell=False,
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise DiagnosticWorkspaceError(str(exc)) from exc

    def workspace_for(self, work_id: str) -> DiagnosticWorkspace:
        token = _safe_work_id(work_id)
        revision = self._revision_resolver.revision_for(work_id)
        path = (self.workspace_root / token).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise DiagnosticWorkspaceError(
                "diagnostic workspace path escaped approved root"
            ) from exc
        return DiagnosticWorkspace(
            work_id=str(work_id).strip(),
            revision=revision,
            path=path,
        )

    def _assert_revision_exists(self, revision: str) -> None:
        result = self._run(
            self.repository_root,
            "cat-file",
            "-e",
            f"{revision}^{{commit}}",
            check=False,
        )
        if result.returncode != 0:
            raise DiagnosticWorkspaceError(
                "diagnostic source revision is unavailable in local repository"
            )

    def assert_pristine(self, work_id: str) -> DiagnosticWorkspace:
        workspace = self.workspace_for(work_id)
        if not workspace.path.is_dir():
            raise DiagnosticWorkspaceError("diagnostic workspace is not prepared")
        head = self._run(workspace.path, "rev-parse", "HEAD").stdout.strip().lower()
        if head != workspace.revision:
            raise DiagnosticWorkspaceError(
                "diagnostic workspace revision changed after preparation"
            )
        status = self._run(
            workspace.path,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout
        if status.strip():
            raise DiagnosticWorkspaceError(
                "diagnostic workspace is not pristine; writes are forbidden"
            )
        return workspace

    def ensure(self, work_id: str) -> DiagnosticWorkspace:
        workspace = self.workspace_for(work_id)
        self._assert_revision_exists(workspace.revision)
        git_marker = workspace.path / ".git"
        if git_marker.exists() or git_marker.is_file():
            return self.assert_pristine(work_id)
        if workspace.path.exists():
            raise DiagnosticWorkspaceError(
                "diagnostic workspace path exists but is not a Git worktree"
            )
        self._run(
            self.repository_root,
            "worktree",
            "add",
            "--detach",
            str(workspace.path),
            workspace.revision,
            timeout=120.0,
        )
        return self.assert_pristine(work_id)

    def resolve(
        self,
        work_id: str,
        relative_path: str,
        *,
        require_file: bool = False,
    ) -> pathlib.Path:
        workspace = self.assert_pristine(work_id)
        raw = str(relative_path or "").strip()
        pure = pathlib.PurePath(raw)
        if not raw or pure.is_absolute() or pathlib.PureWindowsPath(raw).is_absolute():
            raise DiagnosticWorkspaceError("diagnostic path must be relative")
        if any(part in {"..", ".git"} for part in pure.parts):
            raise DiagnosticWorkspaceError(
                "diagnostic path traversal/internals are blocked"
            )
        if _is_sensitive(pure):
            raise DiagnosticWorkspaceError(
                "credential/secret-like diagnostic path is blocked"
            )
        target = (workspace.path / raw).resolve(strict=False)
        try:
            target.relative_to(workspace.path)
        except ValueError as exc:
            raise DiagnosticWorkspaceError(
                "diagnostic path escaped pinned worktree"
            ) from exc
        cursor = workspace.path
        for part in target.relative_to(workspace.path).parts:
            cursor /= part
            if cursor.exists() and cursor.is_symlink():
                raise DiagnosticWorkspaceError(
                    "symlink paths are blocked in diagnostics"
                )
        if require_file and not target.is_file():
            raise DiagnosticWorkspaceError(
                "diagnostic target is not a regular file"
            )
        return target

    def tracked_files(
        self,
        work_id: str,
        *,
        max_results: int = 100,
    ) -> tuple[str, ...]:
        workspace = self.assert_pristine(work_id)
        limit = max(1, min(int(max_results), 1000))
        result = self._run(workspace.path, "ls-files", "-z")
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
        return tuple(files)

    def read_file(self, work_id: str, relative_path: str) -> dict[str, Any]:
        target = self.resolve(work_id, relative_path, require_file=True)
        if target.stat().st_size > _MAX_FILE_BYTES:
            raise DiagnosticWorkspaceError(
                "diagnostic file exceeds bounded read size"
            )
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise DiagnosticWorkspaceError(
                "diagnostic file is not UTF-8 text"
            ) from exc
        if _contains_secret(text):
            raise DiagnosticWorkspaceError(
                "credential-like content is blocked from diagnostic model context"
            )
        workspace = self.workspace_for(work_id)
        encoded = text.encode("utf-8")
        return {
            "path": target.relative_to(workspace.path).as_posix(),
            "text": text[:_MAX_READ_CHARS],
            "truncated": len(text) > _MAX_READ_CHARS,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "revision": workspace.revision,
        }

    def search_source(
        self,
        work_id: str,
        query: str,
        *,
        max_results: int = 20,
    ) -> tuple[str, ...]:
        workspace = self.assert_pristine(work_id)
        needle = str(query or "").strip()
        if not needle:
            raise DiagnosticWorkspaceError("diagnostic search query is empty")
        limit = max(1, min(int(max_results), _MAX_SEARCH_RESULTS))
        rg = shutil.which("rg")
        matches: list[str] = []
        if rg is not None:
            completed = subprocess.run(
                [
                    rg,
                    "--line-number",
                    "--fixed-strings",
                    "--no-messages",
                    "--glob",
                    "!.git/**",
                    needle,
                    ".",
                ],
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
                raise DiagnosticWorkspaceError("ripgrep diagnostic search failed")
            for line in completed.stdout.splitlines():
                if _contains_secret(line):
                    continue
                path_text = line.split(":", 1)[0].removeprefix("./")
                if _is_sensitive(pathlib.PurePosixPath(path_text)):
                    continue
                matches.append(line[:1200])
                if len(matches) >= limit:
                    break
        else:
            for relative_text in self.tracked_files(work_id, max_results=1000):
                if len(matches) >= limit:
                    break
                target = workspace.path / relative_text
                if not target.is_file() or target.stat().st_size > _MAX_FILE_BYTES:
                    continue
                try:
                    lines = target.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeError):
                    continue
                for number, line in enumerate(lines, 1):
                    if needle in line and not _contains_secret(line):
                        matches.append(
                            f"{relative_text}:{number}:{line[:800]}"
                        )
                        if len(matches) >= limit:
                            break
        self.assert_pristine(work_id)
        return tuple(matches)

    def history(
        self,
        work_id: str,
        *,
        relative_path: str,
        max_results: int = 20,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> dict[str, Any]:
        workspace = self.assert_pristine(work_id)
        target = self.resolve(work_id, relative_path, require_file=True)
        relative = target.relative_to(workspace.path).as_posix()
        limit = max(1, min(int(max_results), _MAX_HISTORY_RESULTS))
        if line_start is not None or line_end is not None:
            start = int(line_start or line_end or 1)
            end = int(line_end or line_start or start)
            if start <= 0 or end < start or end - start > 200:
                raise DiagnosticWorkspaceError("invalid bounded blame line range")
            result = self._run(
                workspace.path,
                "blame",
                "--line-porcelain",
                "-L",
                f"{start},{end}",
                "--",
                relative,
            )
            output = result.stdout[-20_000:]
            if _contains_secret(output):
                raise DiagnosticWorkspaceError(
                    "credential-like content is blocked from history context"
                )
            self.assert_pristine(work_id)
            return {
                "mode": "blame",
                "path": relative,
                "line_start": start,
                "line_end": end,
                "output": output,
                "revision": workspace.revision,
            }

        result = self._run(
            workspace.path,
            "log",
            f"-n{limit}",
            "--format=%H%x09%ct%x09%s",
            "--",
            relative,
        )
        rows = tuple(
            line[:1200]
            for line in result.stdout.splitlines()
            if line.strip() and not _contains_secret(line)
        )
        self.assert_pristine(work_id)
        return {
            "mode": "log",
            "path": relative,
            "commits": rows,
            "revision": workspace.revision,
        }

    def bisect_candidates(
        self,
        work_id: str,
        *,
        good_revision: str,
        bad_revision: str,
        max_commits: int = 128,
    ) -> dict[str, Any]:
        workspace = self.assert_pristine(work_id)
        good = str(good_revision).strip().lower()
        bad = str(bad_revision).strip().lower()
        if _GIT_OBJECT.fullmatch(good) is None or _GIT_OBJECT.fullmatch(bad) is None:
            raise DiagnosticWorkspaceError(
                "bisect revisions must be exact Git object IDs"
            )
        for revision in (good, bad):
            result = self._run(
                workspace.path,
                "cat-file",
                "-e",
                f"{revision}^{{commit}}",
                check=False,
            )
            if result.returncode != 0:
                raise DiagnosticWorkspaceError(
                    "bisect revision is unavailable in local repository"
                )
        ancestor = self._run(
            workspace.path,
            "merge-base",
            "--is-ancestor",
            good,
            bad,
            check=False,
        )
        if ancestor.returncode != 0:
            raise DiagnosticWorkspaceError(
                "good revision is not an ancestor of bad revision"
            )
        bound = max(2, min(int(max_commits), _MAX_BISECT_COMMITS))
        result = self._run(
            workspace.path,
            "rev-list",
            "--ancestry-path",
            "--reverse",
            f"{good}..{bad}",
        )
        commits = [line.strip().lower() for line in result.stdout.splitlines() if line]
        truncated = len(commits) > bound
        visible = commits[:bound]
        midpoint = visible[len(visible) // 2] if visible else None
        self.assert_pristine(work_id)
        return {
            "good_revision": good,
            "bad_revision": bad,
            "candidate_count": len(commits),
            "candidates": visible,
            "midpoint": midpoint,
            "truncated": truncated,
            "workspace_revision": workspace.revision,
            "repository_state_mutated": False,
        }


class PrepareDiagnosticWorkspaceExecutor:
    descriptor = BrainAction(
        name="diag_prepare_workspace",
        description=(
            "Prepare or reopen the detached exact-revision read-only diagnostic "
            "worktree for this incident."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, manager: DiagnosticWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        workspace = await asyncio.to_thread(self._manager.ensure, work.work_id)
        return {
            "prepared": True,
            "revision": workspace.revision,
            "workspace_token": workspace.path.name,
            "detached": True,
            "read_only_actions": True,
            "production_tree_modified": False,
        }


class DiagnosticListFilesExecutor:
    descriptor = BrainAction(
        name="diag_list_files",
        description="List tracked non-sensitive files in the pinned diagnostic revision.",
        parameter_schema={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "minimum": 1, "maximum": 1000}
            },
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, manager: DiagnosticWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        limit = int(parameters.get("max_results", 100))
        files = await asyncio.to_thread(
            self._manager.tracked_files,
            work.work_id,
            max_results=limit,
        )
        workspace = self._manager.workspace_for(work.work_id)
        return {
            "files": list(files),
            "max_results": max(1, min(limit, 1000)),
            "revision": workspace.revision,
        }


class DiagnosticReadFileExecutor:
    descriptor = BrainAction(
        name="diag_read_file",
        description="Read one bounded non-sensitive file from the pinned diagnostic revision.",
        parameter_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1000}
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, manager: DiagnosticWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._manager.read_file,
            work.work_id,
            str(parameters.get("path") or ""),
        )


class DiagnosticSearchSourceExecutor:
    descriptor = BrainAction(
        name="diag_search_source",
        description=(
            "Run bounded fixed-string source search inside the pinned diagnostic revision."
        ),
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
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, manager: DiagnosticWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        query = str(parameters.get("query") or "")
        limit = int(parameters.get("max_results", 20))
        matches = await asyncio.to_thread(
            self._manager.search_source,
            work.work_id,
            query,
            max_results=limit,
        )
        workspace = self._manager.workspace_for(work.work_id)
        return {
            "query": query.strip(),
            "matches": list(matches),
            "max_results": max(1, min(limit, _MAX_SEARCH_RESULTS)),
            "revision": workspace.revision,
        }


class DiagnosticHistoryExecutor:
    descriptor = BrainAction(
        name="diag_history",
        description=(
            "Read bounded Git log or blame evidence without changing repository state."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "line_start": {"type": "integer", "minimum": 1},
                "line_end": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, manager: DiagnosticWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._manager.history,
            work.work_id,
            relative_path=str(parameters.get("path") or ""),
            max_results=int(parameters.get("max_results", 20)),
            line_start=parameters.get("line_start"),
            line_end=parameters.get("line_end"),
        )


class DiagnosticBisectExecutor:
    descriptor = BrainAction(
        name="diag_bisect",
        description=(
            "Compute a bounded read-only ancestry bisect candidate without invoking "
            "git bisect or mutating refs/worktree state."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "good_revision": {
                    "type": "string",
                    "minLength": 40,
                    "maxLength": 64,
                },
                "bad_revision": {
                    "type": "string",
                    "minLength": 40,
                    "maxLength": 64,
                },
                "max_commits": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 512,
                },
            },
            "required": ["good_revision", "bad_revision"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, manager: DiagnosticWorkspaceManager) -> None:
        self._manager = manager

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("git", "cpu")

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._manager.bisect_candidates,
            work.work_id,
            good_revision=str(parameters.get("good_revision") or ""),
            bad_revision=str(parameters.get("bad_revision") or ""),
            max_commits=int(parameters.get("max_commits", 128)),
        )


def build_diagnostic_workspace_executors(
    manager: DiagnosticWorkspaceManager,
) -> tuple[object, ...]:
    """Read-only DIAGNOSTICS actions. No write/edit/commit executor is registered."""

    return (
        PrepareDiagnosticWorkspaceExecutor(manager),
        DiagnosticListFilesExecutor(manager),
        DiagnosticReadFileExecutor(manager),
        DiagnosticSearchSourceExecutor(manager),
        DiagnosticHistoryExecutor(manager),
        DiagnosticBisectExecutor(manager),
    )
