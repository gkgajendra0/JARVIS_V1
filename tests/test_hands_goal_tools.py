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


def test_live_voice_aliases_and_transcription_fillers_are_canonicalized() -> None:
    tool = tools("Javis open calculator and set my master volume to 90 percent")
    plan = json.dumps(
        [
            {"operation": "open_app", "parameters": {"app": "calculator"}},
            {"operation": "set_volume", "parameters": {"percent": 90}},
        ]
    )
    steps = tool._parse_plan(plan, tool._latest_user_turn().text)
    assert [step.operation for step in steps] == [
        "open_app",
        "set_master_volume",
    ]
    assert steps[1].parameters == {"percent": 90.0}


def test_voice_file_alias_accepts_spoken_dot_without_weakening_content_grounding() -> (
    None
):
    tool = tools(
        "So create a text file in Downloads named voice test dot txt with text hello world"
    )
    plan = json.dumps(
        [
            {
                "operation": "create_file",
                "parameters": {
                    "root": "downloads",
                    "path": "voice test.txt",
                    "text": "hello world",
                },
            }
        ]
    )
    step = tool._parse_plan(plan, tool._latest_user_turn().text)[0]
    assert step.operation == "create_text_file"
    assert step.parameters == {
        "root": "downloads",
        "path": "voice test.txt",
        "text": "hello world",
    }


def test_voice_winget_transcription_variant_warrants_non_mutating_search() -> None:
    tool = tools(
        "Yeah could you list my Bluetooth devices and search Wing It for PowerToys"
    )
    plan = json.dumps(
        [
            {"operation": "list_bluetooth_devices", "parameters": {}},
            {
                "operation": "winget_search",
                "parameters": {"query": "PowerToys"},
            },
        ]
    )
    steps = tool._parse_plan(plan, tool._latest_user_turn().text)
    assert [step.operation for step in steps] == [
        "list_bluetooth_devices",
        "search_software",
    ]
    assert steps[1].parameters == {"query": "PowerToys"}


def test_voice_reduce_is_an_explicit_volume_action() -> None:
    grounded = parse(
        tools("Jarvis reduce the master volume to 25% again."),
        "set_master_volume",
        {"percent": 25},
    )
    assert grounded == {"percent": 25.0}


def test_voice_close_app_is_a_grounded_lifecycle_action() -> None:
    tool = tools("Jarvis close calculator")
    plan = json.dumps([{"operation": "close_app", "parameters": {"app": "calculator"}}])
    step = tool._parse_plan(plan, tool._latest_user_turn().text)[0]
    assert step.operation == "close_app"
    assert step.parameters == {"app": "calculator"}


def test_named_playlist_in_local_app_uses_structured_windows_plan() -> None:
    tool = tools("Okay. Jarvis, play Bhakti playlist on Apple Music app.")
    plan = json.dumps(
        [
            {
                "operation": "execute_windows_plan",
                "parameters": {
                    "app": "Apple Music",
                    "plan": [
                        {"action": "search", "query": "Bhakti"},
                        {"action": "click", "selector": "Bhakti"},
                        {"action": "click", "selector": "Play"},
                    ],
                },
            }
        ]
    )
    step = tool._parse_plan(plan, tool._latest_user_turn().text)[0]
    assert step.operation == "execute_windows_plan"
    assert step.parameters["app"] == "Apple Music"
    assert step.parameters["task"] == tool._latest_user_turn().text
    assert step.parameters["allow_existing_app"] is True
    assert step.parameters["plan"][0] == {"action": "search", "query": "Bhakti"}


def test_voice_natural_desire_form_authorizes_named_game_launch() -> None:
    grounded = parse(
        tools("Jarvis, I want to play FIFA."),
        "open_app",
        {"app": "FIFA"},
    )
    assert grounded == {"app": "FIFA"}


def test_voice_embedded_polite_request_authorizes_named_game_launch() -> None:
    grounded = parse(
        tools("Jarvis, I want to play FIFA. Could you please start it?"),
        "open_app",
        {"app": "FIFA"},
    )
    assert grounded == {"app": "FIFA"}


def test_explicit_software_discovery_is_still_warranted() -> None:
    grounded = parse(
        tools("Jarvis search software for Spotify"),
        "search_software",
        {"query": "Spotify"},
    )
    assert grounded == {"query": "Spotify"}


@pytest.mark.parametrize(
    "utterance",
    [
        "Jarvis, fire up FIFA for me.",
        "Could we get FIFA going?",
        "FIFA chala do.",
        "I would like FIFA running, please.",
        "Can you get FIFA started?",
        "Let's launch FIFA.",
    ],
)
def test_semantic_app_grounding_is_not_tied_to_designated_command_phrases(
    utterance: str,
) -> None:
    grounded = parse(tools(utterance), "open_app", {"app": "FIFA"})
    assert grounded == {"app": "FIFA"}


def test_phrase_independence_does_not_allow_model_to_substitute_app_target() -> None:
    with pytest.raises(HandsGoalGroundingError, match="model-selected app target"):
        parse(
            tools("Could we get FIFA going?"),
            "open_app",
            {"app": "Calculator"},
        )


def test_open_app_can_resolve_recent_conversation_target_from_pronoun() -> None:
    conversation = ConversationSession(session_id="hands-contextual-app")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "I want to play FIFA.")
    conversation.accept_turn(ConversationRole.USER, "Could you start it?")
    tool = HandsGoalAgentTools(runtime(), conversation)
    plan = json.dumps([{"operation": "open_app", "parameters": {"app": "FIFA"}}])
    step = tool._parse_plan(plan, tool._latest_user_turn().text)[0]
    assert step.parameters == {"app": "FIFA"}


def test_use_computer_schema_is_generated_from_canonical_registry() -> None:
    from jarvis.hands.registry import HandsCapabilityRegistry
    from jarvis.voice.hands_goal_tools import _USE_COMPUTER_RAW_SCHEMA

    plan = _USE_COMPUTER_RAW_SCHEMA["parameters"]["properties"]["plan"]
    operation_schema = plan["items"]["properties"]["operation"]
    assert set(operation_schema["enum"]) == {
        item.operation for item in HandsCapabilityRegistry.default().operations
    }
    assert plan["maxItems"] == 8
