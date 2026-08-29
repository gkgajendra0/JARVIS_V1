from jarvis.voice.agent import INSTRUCTIONS


def test_voice_instructions_define_language_routing() -> None:
    assert "Language matching is mandatory" in INSTRUCTIONS
    assert "default to natural conversational Hinglish" in INSTRUCTIONS
    assert "do not switch to an English-only answer" in INSTRUCTIONS
    assert "retain it for the rest of the session" in INSTRUCTIONS


def test_voice_instructions_limit_wake_only_acknowledgement() -> None:
    normalized = " ".join(INSTRUCTIONS.split())
    assert "give exactly one short acknowledgement and wait" in normalized
    assert "Do not add a second check-in" in normalized


def test_voice_instructions_forbid_unobserved_scene_claims() -> None:
    normalized = " ".join(INSTRUCTIONS.split())
    assert "NOT a general image-understanding system" in normalized
    assert "does not expose raw image pixels" in normalized
    assert "Never invent scene details" in normalized
    assert "clothing colour" in normalized
    assert "general object" in normalized
