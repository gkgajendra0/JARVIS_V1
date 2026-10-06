from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

from jarvis.conversation import ConversationSession
from jarvis.voice.agent import INSTRUCTIONS, build_instructions
from jarvis.voice.work_tools import (
    WorkAgentTools,
    WorkToolGroundingError,
    _explicit_capability_lifecycle_intent,
)
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


def test_phase9_voice_instructions_never_outsource_missing_automation_to_owner() -> (
    None
):
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


def test_gicc_apply_instructions_override_direct_phase9_entry() -> None:
    instructions = " ".join(build_instructions(gicc_apply=True).split())

    assert "GICC APPLY mode is active" in instructions
    assert "call pursue_owner_goal" in instructions
    assert (
        "Direct start_capability_acquisition is intentionally unavailable"
        in instructions
    )
    assert "Ordinary immediate local computer actions" in instructions
    assert "resolve_goal_information" in instructions
    assert "Never treat unrelated ambient speech as the answer" in instructions


def test_work_tools_can_hide_direct_capability_acquisition_in_apply() -> None:
    runtime = object.__new__(WorkRuntime)
    conversation = ConversationSession(session_id="gicc-apply-work-tools")
    conversation.start()

    legacy = WorkAgentTools(runtime, conversation).tools
    apply_tools = WorkAgentTools(
        runtime,
        conversation,
        allow_capability_acquisition=False,
    ).tools

    assert "start_capability_acquisition" in [tool.id for tool in legacy]
    assert "start_capability_acquisition" not in [tool.id for tool in apply_tools]
    assert "activate_acquired_capability" in [tool.id for tool in apply_tools]
    assert "disable_acquired_capability" in [tool.id for tool in apply_tools]


@pytest.mark.parametrize(
    ("text", "activate", "expected"),
    (
        ("Activate it.", True, True),
        ("Please enable the acquired capability.", True, True),
        ("Turn the capability on.", True, True),
        ("Turn on the capability.", True, True),
        ("Start using it now.", True, True),
        ("Do not activate it.", True, False),
        ("Don't enable the capability.", True, False),
        ("Never turn it on.", True, False),
        ("Yes, proceed.", True, False),
        ("What is its status?", True, False),
        ("Disable it.", False, True),
        ("Deactivate the capability.", False, True),
        ("Turn it off.", False, True),
        ("Turn off the capability.", False, True),
        ("Stop using it.", False, True),
        ("Do not disable it.", False, False),
        ("Don't turn it off.", False, False),
        ("Yes, proceed.", False, False),
    ),
)
def test_phase9_lifecycle_intent_is_explicit_and_deterministic(
    text: str,
    activate: bool,
    expected: bool,
) -> None:
    assert _explicit_capability_lifecycle_intent(text, activate=activate) is expected


class _LifecycleTargetStore:
    def __init__(self, change_ids: tuple[str, ...]) -> None:
        self.changes = tuple(SimpleNamespace(change_id=item) for item in change_ids)
        self.artifacts: dict[tuple[str, str], object] = {}
        for index, change_id in enumerate(change_ids):
            candidate = SimpleNamespace(
                artifact_id=f"candidate-{index}",
                digest=f"{index + 1}" * 64,
                payload={},
                created_at=index,
            )
            admission = SimpleNamespace(
                artifact_id=f"admission-{index}",
                digest=f"{index + 2}" * 64,
                payload={
                    "candidate_artifact_id": candidate.artifact_id,
                    "candidate_artifact_digest": candidate.digest,
                },
                created_at=index,
            )
            proposal = SimpleNamespace(
                artifact_id=f"proposal-{index}",
                digest=f"{index + 3}" * 64,
                payload={
                    "authority_required": True,
                    "admission_artifact_id": admission.artifact_id,
                    "admission_artifact_digest": admission.digest,
                },
                created_at=index,
            )
            self.artifacts[(change_id, "capability_candidate")] = candidate
            self.artifacts[(change_id, "capability_package_admission")] = admission
            self.artifacts[(change_id, "capability_lifecycle_proposal")] = proposal

    def list_by_states(self, *args, **kwargs):
        del args, kwargs
        return self.changes

    def latest_artifact(self, change_id: str, kind: str):
        return self.artifacts.get((change_id, kind))


def _lifecycle_target_tools(change_ids: tuple[str, ...]) -> WorkAgentTools:
    runtime = object.__new__(WorkRuntime)
    runtime.changes = SimpleNamespace(store=_LifecycleTargetStore(change_ids))
    conversation = ConversationSession(session_id="lifecycle-target-test")
    conversation.start()
    return WorkAgentTools(runtime, conversation)


def test_lifecycle_target_uses_unique_canonical_pending_change() -> None:
    change_id = "change_aaaaaaaaaaaaaaaa"
    tools = _lifecycle_target_tools((change_id,))

    assert (
        tools._resolve_lifecycle_change_id(
            requested_change_id="",
            owner_text="Activate it.",
            activate=True,
        )
        == change_id
    )


def test_lifecycle_target_rejects_model_id_conflicting_with_canonical_state() -> None:
    tools = _lifecycle_target_tools(("change_aaaaaaaaaaaaaaaa",))

    with pytest.raises(WorkToolGroundingError, match="conflicts with canonical"):
        tools._resolve_lifecycle_change_id(
            requested_change_id="change_bbbbbbbbbbbbbbbb",
            owner_text="Activate it.",
            activate=True,
        )


def test_lifecycle_target_requires_disambiguation_when_multiple_are_pending() -> None:
    first = "change_aaaaaaaaaaaaaaaa"
    second = "change_bbbbbbbbbbbbbbbb"
    tools = _lifecycle_target_tools((first, second))

    with pytest.raises(WorkToolGroundingError, match="ambiguous"):
        tools._resolve_lifecycle_change_id(
            requested_change_id="",
            owner_text="Activate it.",
            activate=True,
        )

    assert (
        tools._resolve_lifecycle_change_id(
            requested_change_id="",
            owner_text=f"Activate acquired capability {second}.",
            activate=True,
        )
        == second
    )


def test_work_runtime_rejects_phase9_lifecycle_without_capability_runtime() -> None:
    with pytest.raises(
        ValueError,
        match="requires governed capability runtime",
    ):
        from jarvis.work.runtime import build_work_runtime

        build_work_runtime(
            provider="test",
            research_service=object(),  # type: ignore[arg-type]
            capability_runtime=None,
            capability_lifecycle_service=object(),  # type: ignore[arg-type]
        )
