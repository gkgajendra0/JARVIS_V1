from __future__ import annotations

import json

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.hands_goal_tools import HandsGoalAgentTools, HandsGoalGroundingError


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in grounding-only tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in grounding-only tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in grounding-only tests")

    def close(self) -> None:
        pass


def runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def tools(text: str) -> HandsGoalAgentTools:
    conversation = ConversationSession(session_id="hands-goal-grounding")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    return HandsGoalAgentTools(runtime(), conversation)


def parse(tool: HandsGoalAgentTools, operation: str, parameters: dict) -> dict:
    plan = json.dumps([{"operation": operation, "parameters": parameters}])
    return tool._parse_plan(plan, tool._latest_user_turn().text)[0].parameters


def test_file_write_material_is_grounded_in_user_turn() -> None:
    grounded = parse(
        tools("Jarvis create file notes.txt in Documents with text hello world"),
        "create_text_file",
        {"root": "documents", "path": "notes.txt", "text": "hello world"},
    )

    assert grounded == {
        "root": "documents",
        "path": "notes.txt",
        "text": "hello world",
    }


def test_file_write_cannot_substitute_model_selected_text() -> None:
    with pytest.raises(
        HandsGoalGroundingError, match="text must be explicitly grounded"
    ):
        parse(
            tools("Jarvis create file notes.txt in Documents with text hello world"),
            "create_text_file",
            {"root": "documents", "path": "notes.txt", "text": "secret replacement"},
        )


def test_browser_allows_inferred_selector_but_not_invented_material_value() -> None:
    grounded = parse(
        tools("Jarvis open example.com and type Gajendra in the search box"),
        "execute_browser_plan",
        {
            "plan": [
                {"action": "navigate", "url": "https://example.com"},
                {
                    "action": "fill",
                    "selector_kind": "placeholder",
                    "selector": "Search",
                    "text": "Gajendra",
                },
            ]
        },
    )

    assert grounded["plan"][0]["url"] == "https://example.com"
    assert grounded["plan"][1]["selector"] == "Search"

    with pytest.raises(HandsGoalGroundingError, match="browser fill text"):
        parse(
            tools("Jarvis open example.com and type Gajendra in the search box"),
            "execute_browser_plan",
            {
                "plan": [
                    {"action": "navigate", "url": "https://example.com"},
                    {
                        "action": "fill",
                        "selector_kind": "placeholder",
                        "selector": "Search",
                        "text": "different value",
                    },
                ]
            },
        )


def test_software_install_requires_user_grounded_exact_package_id() -> None:
    with pytest.raises(HandsGoalGroundingError, match="exact WinGet package ID"):
        parse(
            tools("Jarvis install VLC"),
            "install_package",
            {"package_id": "VideoLAN.VLC"},
        )

    grounded = parse(
        tools("Jarvis install exact WinGet package VideoLAN.VLC"),
        "install_package",
        {"package_id": "VideoLAN.VLC"},
    )
    assert grounded == {"package_id": "VideoLAN.VLC"}


def test_brightness_percentage_must_match_latest_user_turn() -> None:
    grounded = parse(
        tools("Jarvis set brightness to 40 percent"),
        "set_display_brightness",
        {"percent": 40},
    )
    assert grounded == {"percent": 40}

    with pytest.raises(HandsGoalGroundingError, match="brightness percentage"):
        parse(
            tools("Jarvis set brightness to 40 percent"),
            "set_display_brightness",
            {"percent": 80},
        )


def test_bluetooth_device_name_cannot_be_substituted() -> None:
    with pytest.raises(HandsGoalGroundingError, match="Bluetooth device name"):
        parse(
            tools("Jarvis pair bluetooth device AirPods"),
            "pair_bluetooth_device",
            {"name": "BMW headset"},
        )


def test_git_commit_requires_grounded_repo_and_commit_message() -> None:
    grounded = parse(
        tools("Jarvis commit your repo with message wire browser hands"),
        "git_commit",
        {"repo": "jarvis", "message": "wire browser hands"},
    )
    assert grounded == {"repo": "jarvis", "message": "wire browser hands"}

    with pytest.raises(HandsGoalGroundingError, match="Git commit message"):
        parse(
            tools("Jarvis commit your repo with message wire browser hands"),
            "git_commit",
            {"repo": "jarvis", "message": "different message"},
        )


def test_declarative_power_statement_does_not_authorize_restart() -> None:
    with pytest.raises(HandsGoalGroundingError, match="not an explicit action request"):
        parse(
            tools("The computer restart feature is useful"),
            "restart_workstation",
            {},
        )
