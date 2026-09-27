from __future__ import annotations

import pathlib
import subprocess

import pytest

from jarvis.incident_repair.code_index import (
    DiagnosticCodeIndex,
    build_diagnostic_code_intelligence_executors,
)
from jarvis.incident_repair.workspace import (
    DiagnosticWorkspaceError,
    DiagnosticWorkspaceManager,
    build_diagnostic_workspace_executors,
)
from jarvis.work.engine import WorkActionRegistry
from jarvis.work.models import WorkType


class StaticRevisionResolver:
    def __init__(self, revision: str) -> None:
        self.revision = revision

    def revision_for(self, work_id: str) -> str:
        assert work_id
        return self.revision


class EmptyStructuralAnalyzer:
    version = "test-ast"

    def symbols(self, workspace, files, *, max_symbols):
        del workspace, files, max_symbols
        return ()

    def search(self, workspace, files, *, pattern, max_results):
        del workspace, files, pattern, max_results
        return ()


class EmptyImportGraphAnalyzer:
    version = "test-grimp"

    def edges(self, workspace, *, max_edges):
        del workspace, max_edges
        return ()


def _git(repo: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        shell=False,
    )
    return completed.stdout.strip()


def _repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "JARVIS Test")
    _git(repo, "config", "user.email", "jarvis-test@example.invalid")

    source = repo / "src" / "jarvis"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "demo.py").write_text(
        "def first_version():\n    return 'one'\n",
        encoding="utf-8",
    )
    (repo / ".env").write_text("API_KEY=not-for-model\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "first")
    first = _git(repo, "rev-parse", "HEAD").lower()

    (source / "demo.py").write_text(
        "def second_version():\n    return 'two'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "src/jarvis/demo.py")
    _git(repo, "commit", "-m", "second")
    second = _git(repo, "rev-parse", "HEAD").lower()
    return repo, first, second


def test_diagnostic_workspace_is_detached_exact_revision_and_restart_stable(
    tmp_path,
) -> None:
    repo, first, _ = _repo(tmp_path)
    root = tmp_path / "diagnostics"
    manager = DiagnosticWorkspaceManager(
        StaticRevisionResolver(first),
        repository_root=repo,
        workspace_root=root,
    )

    first_open = manager.ensure("work:diagnostic:1")
    second_open = manager.ensure("work:diagnostic:1")

    assert first_open == second_open
    assert first_open.revision == first
    assert _git(first_open.path, "rev-parse", "HEAD").lower() == first
    assert _git(first_open.path, "branch", "--show-current") == ""
    assert manager.read_file("work:diagnostic:1", "src/jarvis/demo.py")[
        "text"
    ].startswith("def first_version")
    assert "second_version" not in manager.read_file(
        "work:diagnostic:1",
        "src/jarvis/demo.py",
    )["text"]
    assert _git(repo, "status", "--porcelain") == ""


def test_diagnostic_workspace_blocks_sensitive_paths_traversal_and_symlinks(
    tmp_path,
) -> None:
    repo, first, _ = _repo(tmp_path)
    manager = DiagnosticWorkspaceManager(
        StaticRevisionResolver(first),
        repository_root=repo,
        workspace_root=tmp_path / "diagnostics",
    )
    workspace = manager.ensure("work-1")

    with pytest.raises(DiagnosticWorkspaceError, match="credential/secret"):
        manager.resolve("work-1", ".env", require_file=True)
    with pytest.raises(DiagnosticWorkspaceError, match="traversal"):
        manager.resolve("work-1", "../outside.txt")

    link = workspace.path / "src" / "jarvis" / "link.py"
    try:
        link.symlink_to(workspace.path / "src" / "jarvis" / "demo.py")
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(DiagnosticWorkspaceError, match="not pristine|symlink"):
        manager.resolve("work-1", "src/jarvis/link.py", require_file=True)


def test_history_and_typed_bisect_do_not_mutate_repository_state(tmp_path) -> None:
    repo, first, second = _repo(tmp_path)
    manager = DiagnosticWorkspaceManager(
        StaticRevisionResolver(first),
        repository_root=repo,
        workspace_root=tmp_path / "diagnostics",
    )
    workspace = manager.ensure("work-1")
    before = _git(workspace.path, "rev-parse", "HEAD")
    before_status = _git(workspace.path, "status", "--porcelain")

    history = manager.history(
        "work-1",
        relative_path="src/jarvis/demo.py",
        max_results=10,
    )
    bisect = manager.bisect_candidates(
        "work-1",
        good_revision=first,
        bad_revision=second,
    )

    assert history["mode"] == "log"
    assert history["revision"] == first
    assert bisect["repository_state_mutated"] is False
    assert bisect["good_revision"] == first
    assert bisect["bad_revision"] == second
    assert bisect["midpoint"] == second
    assert _git(workspace.path, "rev-parse", "HEAD") == before
    assert _git(workspace.path, "status", "--porcelain") == before_status


def test_diagnostics_registry_exposes_no_write_or_commit_action(tmp_path) -> None:
    repo, first, _ = _repo(tmp_path)
    manager = DiagnosticWorkspaceManager(
        StaticRevisionResolver(first),
        repository_root=repo,
        workspace_root=tmp_path / "diagnostics",
    )
    index = DiagnosticCodeIndex(
        manager,
        structural=EmptyStructuralAnalyzer(),
        import_graph=EmptyImportGraphAnalyzer(),
    )
    registry = WorkActionRegistry(
        (
            *build_diagnostic_workspace_executors(manager),
            *build_diagnostic_code_intelligence_executors(index),
        )
    )

    names = {
        action.name for action in registry.actions_for(WorkType.DIAGNOSTICS)
    }

    assert "diag_prepare_workspace" in names
    assert "diag_read_file" in names
    assert "diag_history" in names
    assert "diag_bisect" in names
    assert "diag_structural_search" in names
    assert "diag_repo_map" in names
    assert not any("write" in name or "commit" in name or "edit" in name for name in names)
