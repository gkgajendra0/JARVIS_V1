from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.work.development import (
    DevelopmentCommitExecutor,
    DevelopmentDiffExecutor,
    DevelopmentRunTestsExecutor,
    DevelopmentWorkspaceError,
    DevelopmentWorkspaceManager,
    DevelopmentWriteFileExecutor,
    DockerDevelopmentTestRunner,
)
from jarvis.work.engine import WorkOwnerInputRequired
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
async def test_development_test_executor_uses_only_configured_runner(
    git_project: Path,
    tmp_path: Path,
) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, tuple[str, ...], float]] = []

        async def run(
            self,
            workspace: Path,
            *,
            targets: tuple[str, ...],
            timeout_seconds: float,
        ) -> dict:
            self.calls.append((workspace, targets, timeout_seconds))
            return {"passed": True, "sandbox": "test-double"}

    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")
    runner = RecordingRunner()
    executor = DevelopmentRunTestsExecutor(manager, runner=runner)

    result = await executor.execute(
        work=_development_item(),
        parameters={"targets": ["tests/test_module.py"], "timeout_seconds": 60},
    )

    assert result["passed"] is True
    assert runner.calls == [
        (
            manager.workspace_for("work_dev_test").path,
            ("tests/test_module.py",),
            60.0,
        )
    ]


@pytest.mark.asyncio
async def test_development_tests_wait_for_owner_without_safe_sandbox(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")
    executor = DevelopmentRunTestsExecutor(manager)

    with pytest.raises(WorkOwnerInputRequired, match="sandbox is not configured"):
        await executor.execute(
            work=_development_item(),
            parameters={"targets": ["tests/test_module.py"]},
        )


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


@pytest.mark.asyncio
async def test_docker_runner_uses_locked_down_fixed_pytest_command(
    git_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "jarvis.work.development.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "1 passed", "")

    monkeypatch.setattr("jarvis.work.development.subprocess.run", fake_run)

    runner = DockerDevelopmentTestRunner("jarvis-tests:locked")
    result = await runner.run(
        git_project,
        targets=("tests/test_module.py",),
        timeout_seconds=45.0,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--cap-drop" in command and command[command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in command
    assert "no-new-privileges" in command
    assert "jarvis-tests:locked" in command
    image_index = command.index("jarvis-tests:locked")
    assert command[image_index + 1 : image_index + 5] == [
        "python",
        "-m",
        "pytest",
        "-q",
    ]
    assert result["passed"] is True
    assert result["network"] == "disabled"
    assert result["workspace"] == "read_only"


@pytest.mark.asyncio
async def test_development_diff_and_commit_stay_on_isolated_branch(
    git_project: Path,
    tmp_path: Path,
) -> None:
    manager = DevelopmentWorkspaceManager(
        repository_root=git_project,
        workspace_root=tmp_path / "worktrees",
    )
    manager.ensure("work_dev_test")
    write = DevelopmentWriteFileExecutor(manager)
    diff = DevelopmentDiffExecutor(manager)
    commit = DevelopmentCommitExecutor(manager)

    await write.execute(
        work=_development_item(),
        parameters={"path": "module.py", "text": "VALUE = 2\n"},
    )
    diff_result = await diff.execute(work=_development_item(), parameters={})
    commit_result = await commit.execute(
        work=_development_item(),
        parameters={"message": "Update isolated module"},
    )

    assert "VALUE = 2" in diff_result["diff"]
    assert commit_result["committed"] is True
    assert commit_result["clean"] is True
    assert commit_result["pushed"] is False
    assert commit_result["merged"] is False
    assert commit_result["production_tree_modified"] is False
    assert (git_project / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _git(git_project, "status", "--porcelain").stdout == ""
