from __future__ import annotations

from jarvis.hands.contracts import PlannedAction
from jarvis.hands.grounding import DEFAULT_GROUNDING, GroundingMode
from jarvis.hands.orchestrator import GroundingContext
from jarvis.voice.generic_grounded_hands import GenericGroundedVoiceHandsOrchestrator
from jarvis.voice.hands_fast_path import canonicalize_fast_parameters


def _adapter() -> GenericGroundedVoiceHandsOrchestrator:
    orchestrator = object.__new__(GenericGroundedVoiceHandsOrchestrator)
    orchestrator._grounding = DEFAULT_GROUNDING
    return orchestrator


def test_generic_grounding_matches_cross_script_human_facing_material() -> None:
    cases = (
        ("Apple Music", "एप्पल म्यूजिक"),
        ("Retro Bollywood", "रेट्रो बॉलीवुड"),
        ("WhatsApp", "व्हाट्सऐप"),
        ("Shubhang TP", "शुभांग टीपी"),
    )

    for candidate, spoken in cases:
        proof = DEFAULT_GROUNDING.prove(
            candidate,
            (spoken,),
            mode=GroundingMode.ENTITY,
        )
        assert proof.matched, (candidate, spoken, proof)


def test_literal_grounding_accepts_transliteration_but_not_translation() -> None:
    transliteration = DEFAULT_GROUNDING.prove(
        "okay joining",
        ("ओके जॉइनिंग",),
        mode=GroundingMode.LITERAL,
    )
    translation = DEFAULT_GROUNDING.prove(
        "okay",
        ("ठीक है",),
        mode=GroundingMode.LITERAL,
    )

    assert transliteration.matched is True
    assert translation.matched is False


def test_identifier_grounding_never_uses_cross_script_fuzzy_equivalence() -> None:
    proof = DEFAULT_GROUNDING.prove(
        "Microsoft.WhatsApp_8wekyb3d8bbwe",
        ("माइक्रोसॉफ्ट व्हाट्सऐप",),
        mode=GroundingMode.IDENTIFIER,
    )

    assert proof.matched is False


def test_voice_grounding_context_augments_only_proven_ui_material() -> None:
    orchestrator = _adapter()
    action = PlannedAction(
        operation="execute_windows_plan",
        parameters={
            "app": "Apple Music",
            "plan": [
                {"action": "search", "query": "Retro Bollywood"},
                {"action": "send_text", "text": "okay joining"},
            ],
        },
        evidence="playlist",
    )
    context = GroundingContext(
        "एप्पल म्यूजिक खोलो, रेट्रो बॉलीवुड खोजो और ओके जॉइनिंग लिखो",
        (),
    )

    augmented = orchestrator._grounding_context(action, context)

    assert "Retro Bollywood" in augmented.latest_user_text
    assert "okay joining" in augmented.latest_user_text
    assert augmented.latest_user_text.startswith(context.latest_user_text)


def test_voice_grounding_context_does_not_append_unrelated_model_material() -> None:
    orchestrator = _adapter()
    action = PlannedAction(
        operation="execute_windows_plan",
        parameters={
            "app": "Apple Music",
            "plan": [{"action": "search", "query": "Calculator"}],
        },
        evidence="playlist",
    )
    context = GroundingContext(
        "एप्पल म्यूजिक खोलो और रेट्रो बॉलीवुड खोजो",
        (),
    )

    augmented = orchestrator._grounding_context(action, context)

    assert "Calculator" not in augmented.latest_user_text


def test_fast_scalar_synonyms_are_canonicalized_without_accepting_unknown_fields() -> None:
    assert canonicalize_fast_parameters("set_master_volume", {"level": 35}) == {
        "percent": 35
    }
    assert canonicalize_fast_parameters(
        "set_display_brightness", {"percentage": 45}
    ) == {"percent": 45}

    unknown = canonicalize_fast_parameters(
        "set_master_volume",
        {"level": 35, "shell": "cmd.exe"},
    )
    assert unknown == {"percent": 35, "shell": "cmd.exe"}
