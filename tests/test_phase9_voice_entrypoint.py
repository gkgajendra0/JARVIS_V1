from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.voice.agent import INSTRUCTIONS, build_instructions
from jarvis.voice.work_tools import WorkAgentTools
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.runtime import WorkRuntime

NORMALIZED_INSTRUCTIONS = " ".join(INSTRUCTIONS.split())


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
    assert hasattr(WorkAgentTools, "retry_failed_background_work")
    assert hasattr(WorkAgentTools, "set_background_work_update_interval")
    assert hasattr(WorkAgentTools, "prepare_change_promotion")
    assert hasattr(WorkAgentTools, "execute_change_promotion")


def test_phase9_voice_instructions_route_explicit_acquisition_to_governed_tool() -> (
    None
):
    assert "start_capability_acquisition" in NORMALIZED_INSTRUCTIONS
    assert "target_hints" in NORMALIZED_INSTRUCTIONS
    assert "superficially similar local operation" in NORMALIZED_INSTRUCTIONS
    assert "use_computer" in NORMALIZED_INSTRUCTIONS


def test_phase9_voice_instructions_support_outcome_driven_acquisition() -> None:
    assert "outcome-driven acquisition" in NORMALIZED_INSTRUCTIONS
    assert "concrete external-device/service outcome" in NORMALIZED_INSTRUCTIONS
    assert "does not authorize the eventual external effect" in NORMALIZED_INSTRUCTIONS
    assert "immediately preceding accepted conversation" in NORMALIZED_INSTRUCTIONS
    assert "ask one concise clarification" in NORMALIZED_INSTRUCTIONS


def test_phase9_voice_instructions_never_outsource_missing_automation_to_owner() -> None:
    assert "Owner input is not an execution fallback" in NORMALIZED_INSTRUCTIONS
    assert "open, click, search, inspect, run, test" in NORMALIZED_INSTRUCTIONS
    assert "treat that as a capability gap" in NORMALIZED_INSTRUCTIONS
    assert "physical-world observation" in NORMALIZED_INSTRUCTIONS
    assert "genuinely cannot obtain independently" in NORMALIZED_INSTRUCTIONS


def test_background_research_is_not_a_capability_acquisition_substitute() -> None:
    assert "Do not use `start_background_work`" in NORMALIZED_INSTRUCTIONS
    assert '`work_type="research"` as a substitute' in NORMALIZED_INSTRUCTIONS
    assert "use governed capability acquisition" in NORMALIZED_INSTRUCTIONS


def test_voice_instructions_research_current_media_availability_before_claiming_service() -> (
    None
):
    assert "watch, play, or listen to a named piece of media" in NORMALIZED_INSTRUCTIONS
    assert "current service/catalog availability" in NORMALIZED_INSTRUCTIONS
    assert (
        "Use `search_web` before claiming which service currently carries"
        in NORMALIZED_INSTRUCTIONS
    )
    assert (
        "subscription context, not current catalog availability"
        in NORMALIZED_INSTRUCTIONS
    )
    assert "After service discovery" in NORMALIZED_INSTRUCTIONS
    assert "call `start_capability_acquisition`" in NORMALIZED_INSTRUCTIONS
    assert "inspect a Play button" in NORMALIZED_INSTRUCTIONS
    assert "substitute for the missing automation" in NORMALIZED_INSTRUCTIONS


def test_default_media_target_grounds_short_media_request_without_granting_authority() -> (
    None
):
    instructions = " ".join(
        build_instructions(default_media_target="Hisense TV").split()
    )

    assert "configured target for routing" in instructions
    assert "capability-acquisition target_hints" in instructions
    assert '"Hisense TV"' in instructions
    assert "does not prove a streaming subscription" in instructions
    assert "Authority gates still apply" in instructions


def test_default_media_target_instruction_is_absent_when_unconfigured() -> None:
    assert build_instructions(default_media_target=None) == INSTRUCTIONS


def test_voice_instructions_preserve_referential_retry_context() -> None:
    assert "retry_failed_background_work" in NORMALIZED_INSTRUCTIONS
    assert "referential retry utterance" in NORMALIZED_INSTRUCTIONS
    assert "set_background_work_update_interval" in NORMALIZED_INSTRUCTIONS
