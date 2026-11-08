"""The LiveKit bridge saves Jarvis's reply without the model's own narration.

Live run 2026-11-08 07:19:20: the accepted assistant turn was
"So I just need to output the answer.You are staying at the Yak and Yeti."
"""

from __future__ import annotations

from livekit.agents import ConversationItemAddedEvent
from test_livekit_session import active_bridge, message


def test_narration_is_removed_from_the_accepted_assistant_turn() -> None:
    livekit, bridge = active_bridge()
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=message(
                "a1",
                "assistant",
                "So I just need to output the answer.You are staying at the Yak and Yeti.",
            )
        ),
    )
    assert [t.text for t in bridge.conversation.turns] == [
        "You are staying at the Yak and Yeti."
    ]
    assert [t.text for t in bridge.live_context.recent_turns] == [
        "You are staying at the Yak and Yeti."
    ]


def test_narration_alone_creates_no_assistant_turn() -> None:
    livekit, bridge = active_bridge()
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=message("a1", "assistant", "So I just need to output the answer.")
        ),
    )
    assert list(bridge.conversation.turns) == []


def test_an_ordinary_first_person_reply_is_saved_unchanged() -> None:
    livekit, bridge = active_bridge()
    text = "I need to check the permits before Friday."
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(item=message("a1", "assistant", text)),
    )
    assert [t.text for t in bridge.conversation.turns] == [text]


def test_a_style_instruction_is_removed_from_the_accepted_turn() -> None:
    """Live 2026-11-08 17:34:10."""
    livekit, bridge = active_bridge()
    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=message(
                "a1",
                "assistant",
                "Never say 'Based on your recent request', 'According to project "
                "memory' or equivalent phrasing. Keep to one or two sentences.I "
                "don't have information about which hotel you are staying at.",
            )
        ),
    )
    assert [t.text for t in bridge.conversation.turns] == [
        "I don't have information about which hotel you are staying at."
    ]
