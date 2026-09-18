from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.work.development import (
    DevelopmentRunTestsExecutor,
    DevelopmentWorkspaceError,
    DevelopmentWorkspaceManager,
    DevelopmentWriteFileExecutor,
)
from jarvis.work.models import WorkItem, WorkType


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture()
def git_project(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("Git is required for development-worktree tests")
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "jarvis-tests@example.invalid")
    _git(root, "config", "user.name", "JARVIS Tests")
    (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_module.py").write_text(
        "from module import VALUE\n\ndef test_value():\n    assert VALUE == 1\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    return root


def _development_item() -> WorkItem:
    return WorkItem(
        work_id="work_dev_test",
        request="Change the module safely",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session-dev",
        source_turn_id="turn-dev",
    )


def test_workspace_is_separate_from_protected_checkout(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    workspace = manager.ensure("work_dev_test")

    assert workspace.path != git_project
    assert workspace.path.is_dir()
    assert workspace.branch.startswith("jarvis/work/")
    assert (workspace.path / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (git_project / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


@pytest.mark.asyncio
async def test_development_write_changes_only_isolated_worktree(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")
    executor = DevelopmentWriteFileExecutor(manager)

    result = await executor.execute(
        work=_development_item(),
        parameters={"path": "module.py", "text": "VALUE = 2\n"},
    )

    workspace = manager.workspace_for("work_dev_test")
    assert result["production_tree_modified"] is False
    assert (workspace.path / "module.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (git_project / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_development_paths_cannot_escape_worktree(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")

    with pytest.raises(DevelopmentWorkspaceError, match="traversal"):
        manager.resolve("work_dev_test", "../outside.py")


@pytest.mark.asyncio
async def test_development_test_runner_is_pytest_only_and_verified(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")
    executor = DevelopmentRunTestsExecutor(manager)

    result = await executor.execute(
        work=_development_item(),
        parameters={"targets": ["tests/test_module.py"], "timeout_seconds": 60},
    )

    assert result["passed"] is True
    assert result["timed_out"] is False
    assert result["command"][:4] == ["python", "-m", "pytest", "-q"]


@pytest.mark.asyncio
async def test_development_test_target_cannot_escape_worktree(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")
    executor = DevelopmentRunTestsExecutor(manager)

    with pytest.raises(DevelopmentWorkspaceError, match="remain inside worktree"):
        await executor.execute(
            work=_development_item(),
            parameters={"targets": ["../outside.py"]},
        )
