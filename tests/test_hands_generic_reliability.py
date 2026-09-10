from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capabilities.windows_focus import PollingForegroundWindowBackend
from jarvis.capabilities.windows_native import WindowSnapshot
from jarvis.hands.contracts import PlannedAction
from jarvis.hands.orchestrator import GroundingContext, HandsOrchestrationError
from jarvis.hands.planner import HandsRouteGroup
from jarvis.provider_resilience import ProviderFailureKind, classify_provider_failure
from jarvis.voice.agent import INSTRUCTIONS
from jarvis.voice.hands_goal_tools import _compact_voice_result
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator
from jarvis.voice.hands_transaction import (
    LeaseAwareCapabilityRuntime,
    LeaseAwareHandsPlanner,
)


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in normalization-only tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in normalization-only tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in normalization-only tests")

    def close(self) -> None:
        pass


def _empty_runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def _voice_orchestrator() -> VoiceHandsOrchestrator:
    planner = SimpleNamespace(provider_name="test", model_name="test-model")
    return VoiceHandsOrchestrator(_empty_runtime(), planner)


@pytest.mark.parametrize(
    "transcript",
    (
        "जार्विस सिस्टम का वॉल्यूम थर्टी परसेंट पर सेट करो।",
        "جارویز، والیم کو تھرٹی پرسنٹ پر سیٹ کرو",
    ),
)
def test_voice_numeric_grounding_accepts_transliterated_reversible_volume(
    transcript: str,
) -> None:
    orchestrator = _voice_orchestrator()
    normalized = orchestrator._normalize_action(
        PlannedAction(
            operation="set_master_volume",
            parameters={"percent": 30.0},
            evidence="thirty percent",
        ),
        GroundingContext(transcript, ()),
    )

    assert normalized.operation == "set_master_volume"
    assert normalized.parameters == {"percent": 30.0}


def test_voice_semantic_grounding_does_not_relax_high_risk_install_evidence() -> None:
    orchestrator = _voice_orchestrator()

    with pytest.raises(HandsOrchestrationError, match="verbatim-grounded"):
        orchestrator._normalize_action(
            PlannedAction(
                operation="install_package",
                parameters={"package_id": "Microsoft.PowerToys"},
                evidence="invented package evidence",
            ),
            GroundingContext("Install PowerToys", ()),
        )


def test_voice_prompt_routes_desktop_screen_inspection_to_hands_not_camera() -> None:
    assert "desktop UI/screen inspection is Hands, not Pocket3 camera vision" in INSTRUCTIONS
    assert "MUST call `use_computer` before answering" in INSTRUCTIONS


class RouteRecordingPlanner:
    provider_name = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.candidates: tuple[str, ...] = ()

    async def route(self, *, goal, recent_user_turns, route_groups):
        del goal, recent_user_turns, route_groups
        return ("app_ui",)

    async def next_action(
        self,
        *,
        goal,
        recent_user_turns,
        candidate_operations,
        observations,
    ):
        del goal, recent_user_turns, observations
        self.candidates = tuple(item.operation for item in candidate_operations)
        return SimpleNamespace(goal_complete=False)


@pytest.mark.asyncio
async def test_voice_route_does_not_reinflate_unselected_related_operation_groups() -> None:
    planner = RouteRecordingPlanner()
    wrapped = LeaseAwareHandsPlanner(planner, lambda: True)
    groups = (
        HandsRouteGroup(
            key="app_ui",
            description="Desktop UI",
            operations=(SimpleNamespace(operation="execute_windows_plan"),),
        ),
        HandsRouteGroup(
            key="media",
            description="Media",
            operations=(SimpleNamespace(operation="play_media"),),
        ),
        HandsRouteGroup(
            key="windows",
            description="Windows",
            operations=(SimpleNamespace(operation="focus_window"),),
        ),
        HandsRouteGroup(
            key="visual_fallback",
            description="Visual",
            operations=(SimpleNamespace(operation="execute_visual_desktop_task"),),
        ),
    )
    selected = await wrapped.route(
        goal="Open my Punjabi playlist",
        recent_user_turns=(),
        route_groups=groups,
    )
    candidates = tuple(item for group in groups for item in group.operations)

    await wrapped.next_action(
        goal="Open my Punjabi playlist",
        recent_user_turns=(),
        candidate_operations=candidates,
        observations=(),
    )

    assert selected == ("app_ui", "visual_fallback")
    assert planner.candidates == ("execute_windows_plan",)


class ResultRuntime:
    def __init__(self, result: CapabilityResult) -> None:
        self.result = result

    def execute_operation(self, **kwargs):
        del kwargs
        return self.result


def test_mutating_ui_micro_plan_with_trailing_observation_becomes_verified() -> None:
    result = CapabilityResult(
        status=CapabilityStatus.SUCCEEDED,
        capability_key="windows:desktop.control",
        operation="execute_windows_plan",
        data={
            "steps": [
                {"action": "click", "payload": {"exit_code": 0}},
                {
                    "action": "inspect",
                    "payload": {"exit_code": 0, "tree": [{"name": "Playlists"}]},
                },
            ],
            "verification_passed": False,
        },
    )
    wrapped = LeaseAwareCapabilityRuntime(
        ResultRuntime(result),  # type: ignore[arg-type]
        lambda: True,
    )

    observed = wrapped.execute_operation(operation="execute_windows_plan")

    assert observed.data["verification_passed"] is True
    assert observed.data["verification_basis"] == "post_mutation_observation"


def test_voice_hands_result_compaction_keeps_final_evidence_not_full_trace() -> None:
    huge = "x" * 10_000
    full = {
        "ok": True,
        "status": "succeeded",
        "completed_steps": 5,
        "results": [
            {"operation": f"old-{index}", "data": {"blob": huge}}
            for index in range(4)
        ]
        + [
            {
                "ok": True,
                "status": "succeeded",
                "operation": "execute_windows_plan",
                "capability": "windows:desktop.control",
                "data": {"visible_text": huge},
            }
        ],
        "observations": [
            {"operation": f"old-{index}", "data": {"blob": huge}}
            for index in range(4)
        ]
        + [
            {
                "operation": "execute_windows_plan",
                "status": "succeeded",
                "ok": True,
                "verified": True,
                "data": {"visible_text": huge},
            }
        ],
    }

    compact = _compact_voice_result(full)
    encoded = json.dumps(compact)

    assert compact["completed_steps"] == 5
    assert compact["final_result"]["operation"] == "execute_windows_plan"
    assert compact["final_observation"]["verified"] is True
    assert "old-0" not in encoded
    assert len(encoded) < 10_000


def _snapshot(*, foreground: bool) -> WindowSnapshot:
    return WindowSnapshot(
        hwnd=42,
        title="Apple Music",
        process="AppleMusic.exe",
        rect=(0, 0, 1000, 700),
        visible=True,
        iconic=False,
        zoomed=False,
        foreground=foreground,
    )


class SequencedFocusBackend(PollingForegroundWindowBackend):
    def __init__(self, states: list[bool]) -> None:
        self._states = list(states)
        self._last = states[-1]
        super().__init__(
            verification_timeout_seconds=0.2,
            poll_seconds=0.01,
            sleeper=lambda _seconds: None,
            monotonic=self._clock,
        )
        self._ticks = 0
        self.focus_requests = 0

    def _clock(self) -> float:
        self._ticks += 1
        return self._ticks * 0.01

    def snapshot(self, app: str) -> WindowSnapshot:
        del app
        if self._states:
            self._last = self._states.pop(0)
        return _snapshot(foreground=self._last)

    def _modules(self):
        backend = self

        class Con:
            SW_RESTORE = 9

        class Gui:
            @staticmethod
            def ShowWindow(hwnd, command):
                del hwnd, command

            @staticmethod
            def SetForegroundWindow(hwnd):
                del hwnd
                backend.focus_requests += 1

        return object(), object(), Con, Gui, object()


def test_focus_verification_polls_eventual_foreground_state() -> None:
    backend = SequencedFocusBackend([False, False, True])

    state = backend.focus("Apple Music")

    assert state.foreground is True
    assert backend.focus_requests == 1


def test_focus_verification_does_not_claim_success_when_foreground_never_arrives() -> None:
    backend = SequencedFocusBackend([False])

    state = backend.focus("Apple Music")

    assert state.foreground is False
    assert backend.focus_requests == 1


def test_realtime_token_rate_code_without_http_status_is_classified() -> None:
    failure = classify_provider_failure(
        RuntimeError("response failed: [tokens] rate_limit_exceeded"),
        provider="openai",
    )

    assert failure.kind is ProviderFailureKind.RATE_LIMITED
    assert failure.status_code is None
