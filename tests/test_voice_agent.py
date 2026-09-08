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


def test_voice_instructions_forbid_implicit_remember_tool_calls() -> None:
    normalized = " ".join(INSTRUCTIONS.split())
    assert '"My home city is Sagar"' in normalized
    assert '"My candidate test animal is falcon"' in normalized
    assert "are NOT explicit remember requests" in normalized
    assert "do not call `remember_memory` for them" in normalized
    assert "Implicit facts are handled separately" in normalized
    assert "candidate extraction path" in normalized


def test_voice_instructions_keep_implicit_memory_handling_invisible() -> None:
    normalized = " ".join(INSTRUCTIONS.split())
    assert "Implicit memory handling must remain invisible" in normalized
    assert "Do NOT ask whether the user wants the fact remembered" in normalized
    assert "do NOT offer to save/store it" in normalized
    assert "do NOT mention candidate extraction, quarantine" in normalized
    assert '"My favorite wild bird is falcon"' in normalized
    assert '"Do you want me to remember that?"' in normalized
