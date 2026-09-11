from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.hands.app_catalog import AppCatalogError, InstalledApp
from jarvis.hands.contracts import PlannedAction, parameter_model_for
from jarvis.hands.entities import AppEntityResolver
from jarvis.hands.grounding import DEFAULT_GROUNDING, GroundingMode
from jarvis.hands.orchestrator import GroundingContext
from jarvis.voice.generic_grounded_hands import GenericGroundedVoiceHandsOrchestrator
from jarvis.voice.hands_fast_path import canonicalize_fast_parameters


class _AppCatalog:
    def __init__(self) -> None:
        self._entries = (
            InstalledApp("WhatsApp", "app.whatsapp"),
            InstalledApp("Calculator", "app.calculator"),
        )

    def entries(self):
        return self._entries

    def resolve(self, query: str):
        normalized = " ".join(query.casefold().split())
        for app in self._entries:
            if normalized == app.display_name.casefold():
                return app
        raise AppCatalogError(f"not found: {query}")

    def launch(self, app):
        raise AssertionError("grounding unit tests never launch applications")


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


def test_windows_owned_whatsapp_identity_resolves_from_devanagari_transcript() -> None:
    resolver = AppEntityResolver(_AppCatalog())

    resolved = resolver.resolve(
        "WhatsApp",
        latest_user_text="जार्विस व्हाट्सऐप खोलो और शुभांग टीपी को मैसेज भेजो",
        evidence="व्हाट्सऐप खोलो",
    )

    assert resolved.app_id == "app.whatsapp"
    assert resolved.display_name == "WhatsApp"


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


def test_fast_scalar_synonyms_are_canonicalized_without_weakening_contract() -> None:
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
    with pytest.raises(ValidationError):
        parameter_model_for("set_master_volume").model_validate(unknown)


def test_conflicting_fast_scalar_synonyms_fail_closed() -> None:
    with pytest.raises(ValueError, match="conflicting fast-path parameters"):
        canonicalize_fast_parameters(
            "set_master_volume",
            {"percent": 20, "level": 35},
        )
