from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.voice.agent import INSTRUCTIONS
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.runtime import WorkRuntime


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    if shutil.which("git") is None:
        pytest.skip("Git is required")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "jarvis-tests@example.invalid")
    _git(root, "config", "user.name", "JARVIS Tests")
    (root / "README.md").write_text("phase9 voice entrypoint\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root, _git(root, "rev-parse", "HEAD").casefold()


def test_development_workspace_reports_exact_trusted_source_revision(
    tmp_path: Path,
    git_repo: tuple[Path, str],
) -> None:
    root, expected = git_repo
    manager = DevelopmentWorkspaceManager(
        repository_root=root,
        workspace_root=tmp_path / "worktrees",
    )

    assert manager.current_revision() == expected
    assert len(manager.current_revision()) == 40


def test_work_runtime_source_revision_provider_is_fail_closed() -> None:
    runtime = object.__new__(WorkRuntime)
    runtime._source_revision_provider = lambda: "a" * 40
    assert runtime.current_source_revision() == "a" * 40

    runtime._source_revision_provider = lambda: "not-a-sha"
    with pytest.raises(RuntimeError, match="invalid"):
        runtime.current_source_revision()

    runtime._source_revision_provider = None
    with pytest.raises(RuntimeError, match="unavailable"):
        runtime.current_source_revision()


def test_work_runtime_refreshes_live_capability_catalog() -> None:
    runtime = object.__new__(WorkRuntime)
    calls: list[str] = []
    runtime._capability_catalog_refresher = lambda: calls.append("refresh")

    runtime.refresh_capability_catalog()

    assert calls == ["refresh"]

    runtime._capability_catalog_refresher = None
    runtime.refresh_capability_catalog()


def test_phase9_owner_voice_tools_are_exposed() -> None:
    assert hasattr(WorkAgentTools, "start_capability_acquisition")
    assert hasattr(WorkAgentTools, "activate_acquired_capability")
    assert hasattr(WorkAgentTools, "disable_acquired_capability")
    assert hasattr(WorkAgentTools, "prepare_change_promotion")
    assert hasattr(WorkAgentTools, "execute_change_promotion")


def test_phase9_voice_instructions_route_explicit_acquisition_to_governed_tool() -> None:
    assert "start_capability_acquisition" in INSTRUCTIONS
    assert "target_hints" in INSTRUCTIONS
    assert "superficially similar local operation" in INSTRUCTIONS
    assert "use_computer" in INSTRUCTIONS
