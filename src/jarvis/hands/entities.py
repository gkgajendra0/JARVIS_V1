"""Canonical entity resolution for JARVIS Hands.

Entity resolution is deliberately separate from natural-language intent.  The model
may suggest a user-facing alias, but JARVIS resolves that alias against machine-owned
identity sources and refuses unrelated target substitution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.hands.app_catalog import AppCatalog, AppCatalogError, InstalledApp

_GENERIC_APP_WORDS = frozenset({"app", "application", "game", "program", "software"})
_REFERENCE_WORDS = frozenset({"it", "that", "this", "one"})


class EntityResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedAppRef:
    app_id: str
    display_name: str
    source: str
    grounded_from: str

    def payload(self) -> dict[str, str]:
        return {
            "app_id": self.app_id,
            "display_name": self.display_name,
            "source": self.source,
            "grounded_from": self.grounded_from,
        }


def _normalized(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _tokens(value: object) -> set[str]:
    return {
        token
        for token in _normalized(value).split()
        if token and token not in _GENERIC_APP_WORDS
    }


def _literal_grounded(value: str, text: str) -> bool:
    needle = _normalized(value)
    haystack = _normalized(text)
    if needle and needle in haystack:
        return True
    compact_needle = _compact(value)
    compact_haystack = _compact(text)
    return len(compact_needle) >= 3 and compact_needle in compact_haystack


def _alias_related(query: str, display_name: str) -> bool:
    left = _compact(query)
    right = _compact(display_name)
    if left and right and (left in right or right in left):
        return True
    left_tokens = _tokens(query)
    right_tokens = _tokens(display_name)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap > 0 and overlap / min(len(left_tokens), len(right_tokens)) >= 0.5


def _mention_score(app: InstalledApp, text: str) -> int:
    normalized_name = _normalized(app.display_name)
    normalized_text = _normalized(text)
    if normalized_name and normalized_name in normalized_text:
        return 1_000 + min(len(normalized_name), 200)
    compact_name = _compact(app.display_name)
    compact_text = _compact(text)
    if len(compact_name) >= 4 and compact_name in compact_text:
        return 950
    name_tokens = _tokens(app.display_name)
    text_tokens = set(normalized_text.split())
    if len(name_tokens) >= 2 and name_tokens.issubset(text_tokens):
        return 850 + len(name_tokens)
    return -1


class AppEntityResolver:
    """Resolve a model alias to one Windows-owned installed-app identity."""

    def __init__(self, catalog: AppCatalog) -> None:
        self._catalog = catalog

    def _mentioned_apps(
        self, texts: tuple[str, ...]
    ) -> list[tuple[int, InstalledApp, str]]:
        entries = self._catalog.entries()
        ranked: list[tuple[int, InstalledApp, str]] = []
        for recency, text in enumerate(texts):
            recency_bonus = max(0, 100 - recency * 10)
            for app in entries:
                score = _mention_score(app, text)
                if score >= 0:
                    ranked.append((score + recency_bonus, app, text))
        ranked.sort(key=lambda item: (-item[0], item[1].display_name.casefold()))
        return ranked

    @staticmethod
    def _unique_best(
        ranked: list[tuple[int, InstalledApp, str]],
    ) -> tuple[InstalledApp, str] | None:
        if not ranked:
            return None
        best_score = ranked[0][0]
        best = [item for item in ranked if item[0] == best_score]
        identities = {
            (item[1].app_id, item[1].display_name.casefold()) for item in best
        }
        if len(identities) != 1:
            return None
        return best[0][1], best[0][2]

    def resolve(
        self,
        query: str,
        *,
        latest_user_text: str,
        recent_user_texts: tuple[str, ...] = (),
        evidence: str = "",
    ) -> ResolvedAppRef:
        bounded_query = " ".join(str(query).split())
        if not bounded_query or len(bounded_query) > 160:
            raise EntityResolutionError("app target must be a bounded non-empty name")

        texts = tuple(
            text
            for text in (latest_user_text, *reversed(recent_user_texts))
            if str(text).strip()
        )
        query_is_grounded = any(
            _literal_grounded(bounded_query, text) for text in texts
        )
        proposed: InstalledApp | None = None
        try:
            proposed = self._catalog.resolve(bounded_query)
        except AppCatalogError:
            pass

        mentioned = self._unique_best(self._mentioned_apps(texts))
        if query_is_grounded and proposed is not None:
            grounded_from = next(
                text for text in texts if _literal_grounded(bounded_query, text)
            )
            return ResolvedAppRef(
                app_id=proposed.app_id,
                display_name=proposed.display_name,
                source=proposed.source,
                grounded_from=grounded_from,
            )

        if mentioned is not None:
            app, grounded_from = mentioned
            if proposed is not None and proposed.app_id == app.app_id:
                return ResolvedAppRef(
                    app_id=app.app_id,
                    display_name=app.display_name,
                    source=app.source,
                    grounded_from=grounded_from,
                )
            if _alias_related(bounded_query, app.display_name):
                return ResolvedAppRef(
                    app_id=app.app_id,
                    display_name=app.display_name,
                    source=app.source,
                    grounded_from=grounded_from,
                )
            raise EntityResolutionError(
                "planner-selected app target conflicts with the app named by the user"
            )

        evidence_tokens = set(_normalized(evidence).split())
        can_use_recent_reference = bool(evidence_tokens & _REFERENCE_WORDS)
        if can_use_recent_reference and recent_user_texts:
            recent_ranked = self._mentioned_apps(tuple(reversed(recent_user_texts)))
            recent = self._unique_best(recent_ranked)
            if recent is not None:
                app, grounded_from = recent
                if (
                    proposed is None
                    or proposed.app_id == app.app_id
                    or _alias_related(bounded_query, app.display_name)
                ):
                    return ResolvedAppRef(
                        app_id=app.app_id,
                        display_name=app.display_name,
                        source=app.source,
                        grounded_from=grounded_from,
                    )

        raise EntityResolutionError(
            "application target could not be grounded to one installed app identity"
        )
