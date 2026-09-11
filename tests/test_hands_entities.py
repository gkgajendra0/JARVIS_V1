from __future__ import annotations

import pytest

from jarvis.hands.app_catalog import AppCatalogError, InstalledApp
from jarvis.hands.entities import AppEntityResolver, EntityResolutionError


class FakeCatalog:
    def __init__(self) -> None:
        self._entries = (
            InstalledApp("Apple Music", "app.apple.music"),
            InstalledApp("Calculator", "app.calculator"),
            InstalledApp("FIFA 23", "app.fifa23"),
        )

    def entries(self):
        return self._entries

    def resolve(self, query: str):
        normalized = " ".join(query.casefold().split())
        matches = [
            app
            for app in self._entries
            if normalized == app.display_name.casefold()
            or app.display_name.casefold().startswith(normalized + " ")
        ]
        if len(matches) != 1:
            raise AppCatalogError(f"not uniquely resolved: {query}")
        return matches[0]

    def launch(self, app):
        raise AssertionError("entity tests never launch applications")


def test_app_alias_is_canonicalized_to_user_named_installed_identity() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    resolved = resolver.resolve(
        "Apple Music application",
        latest_user_text="Open Apple Music",
        evidence="Open Apple Music",
    )

    assert resolved.app_id == "app.apple.music"
    assert resolved.display_name == "Apple Music"


def test_model_cannot_substitute_unrelated_app_target() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    with pytest.raises(EntityResolutionError, match="conflicts"):
        resolver.resolve(
            "Calculator",
            latest_user_text="Open Apple Music",
            evidence="Open Apple Music",
        )


def test_short_user_alias_can_resolve_longer_installed_app_name() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    resolved = resolver.resolve(
        "FIFA",
        latest_user_text="Could you get FIFA going for me?",
        evidence="get FIFA going",
    )

    assert resolved.display_name == "FIFA 23"
    assert resolved.app_id == "app.fifa23"


def test_pronoun_followup_can_use_recent_grounded_app_identity() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    resolved = resolver.resolve(
        "Apple Music",
        latest_user_text="Could you start it?",
        recent_user_texts=("I want Apple Music open.",),
        evidence="start it",
    )

    assert resolved.display_name == "Apple Music"


def test_devanagari_transliteration_can_ground_windows_owned_app_identity() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    resolved = resolver.resolve(
        "Apple Music",
        latest_user_text="जार्विस, एप्पल म्यूजिक ऑन करो और प्लेलिस्ट खोलो।",
        evidence="एप्पल म्यूजिक",
    )

    assert resolved.app_id == "app.apple.music"
    assert resolved.display_name == "Apple Music"


def test_urdu_transliteration_can_ground_windows_owned_app_identity() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    resolved = resolver.resolve(
        "Apple Music",
        latest_user_text="جاروس، ایپل میوزک کھولو۔",
        evidence="ایپل میوزک",
    )

    assert resolved.app_id == "app.apple.music"
    assert resolved.display_name == "Apple Music"


def test_cross_script_grounding_does_not_allow_unrelated_app_substitution() -> None:
    resolver = AppEntityResolver(FakeCatalog())

    with pytest.raises(EntityResolutionError, match="conflicts"):
        resolver.resolve(
            "Calculator",
            latest_user_text="जार्विस, एप्पल म्यूजिक खोलो।",
            evidence="एप्पल म्यूजिक",
        )
