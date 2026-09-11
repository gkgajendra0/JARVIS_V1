"""Canonical entity resolution for JARVIS Hands.

Entity resolution is deliberately separate from natural-language intent. The model may
suggest a user-facing alias, but JARVIS resolves that alias against machine-owned identity
sources and refuses unrelated target substitution.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from jarvis.hands.app_catalog import AppCatalog, AppCatalogError, InstalledApp
from jarvis.hands.grounding import DEFAULT_GROUNDING, GroundingMode
from jarvis.hands.multilingual import has_contextual_reference

LOGGER = logging.getLogger(__name__)

_GENERIC_APP_WORDS = frozenset({"app", "application", "game", "program", "software"})
_REFERENCE_WORDS = frozenset({"it", "that", "this", "one", "again", "same"})
_ENTITY_THRESHOLD = 0.82
_AMBIGUITY_MARGIN = 15


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
    return DEFAULT_GROUNDING.prove(
        value,
        (text,),
        mode=GroundingMode.ENTITY,
        threshold=_ENTITY_THRESHOLD,
    ).matched


def _alias_related(query: str, display_name: str) -> bool:
    left = _compact(query)
    right = _compact(display_name)
    if left and right and (left in right or right in left):
        return True
    left_tokens = _tokens(query)
    right_tokens = _tokens(display_name)
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens)
        if overlap > 0 and overlap / min(len(left_tokens), len(right_tokens)) >= 0.5:
            return True
    return DEFAULT_GROUNDING.related(
        query,
        display_name,
        mode=GroundingMode.ENTITY,
        threshold=_ENTITY_THRESHOLD,
    )


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

    proof = DEFAULT_GROUNDING.prove(
        app.display_name,
        (text,),
        mode=GroundingMode.ENTITY,
        threshold=_ENTITY_THRESHOLD,
    )
    if proof.matched:
        return 800 + int(proof.score * 100)
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
        best_score, best_app, best_text = ranked[0]
        best_identity = (best_app.app_id, best_app.display_name.casefold())
        peers = [
            item
            for item in ranked[1:]
            if (item[1].app_id, item[1].display_name.casefold()) != best_identity
        ]
        if peers and best_score - peers[0][0] < _AMBIGUITY_MARGIN:
            return None
        return best_app, best_text

    @staticmethod
    def _resolved(
        app: InstalledApp,
        grounded_from: str,
    ) -> ResolvedAppRef:
        return ResolvedAppRef(
            app_id=app.app_id,
            display_name=app.display_name,
            source=app.source,
            grounded_from=grounded_from,
        )

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

        latest_text = str(latest_user_text or "").strip()
        recent_texts = tuple(text for text in recent_user_texts if str(text).strip())
        proposed: InstalledApp | None = None
        try:
            proposed = self._catalog.resolve(bounded_query)
        except AppCatalogError:
            pass

        # First prove the planner's machine-owned candidate directly against the latest
        # USER turn. This avoids a catalogue-wide fuzzy search winning over a clearly
        # grounded candidate while still rejecting unrelated model substitutions.
        latest_query_grounded = _literal_grounded(bounded_query, latest_text)
        if latest_query_grounded and proposed is not None:
            return self._resolved(proposed, latest_text)

        latest_mentioned = self._unique_best(self._mentioned_apps((latest_text,)))
        if latest_mentioned is not None:
            app, grounded_from = latest_mentioned
            if proposed is not None and proposed.app_id == app.app_id:
                return self._resolved(app, grounded_from)
            if _alias_related(bounded_query, app.display_name):
                return self._resolved(app, grounded_from)
            LOGGER.warning(
                "Hands app grounding conflict | planner_query=%r | planner_app=%r | "
                "spoken_app=%r | spoken_app_id=%r",
                bounded_query,
                proposed.display_name if proposed is not None else None,
                app.display_name,
                app.app_id,
            )
            raise EntityResolutionError(
                "planner-selected app target conflicts with the app named by the user"
            )

        # Conversation history may ground an app only when the latest utterance actually
        # references prior context. This prevents stale app mentions from authorizing a
        # planner-selected target for an unrelated new request.
        evidence_tokens = set(_normalized(evidence).split())
        can_use_recent_reference = bool(evidence_tokens & _REFERENCE_WORDS) or any(
            has_contextual_reference(value) for value in (latest_text, evidence)
        )
        if can_use_recent_reference and recent_texts:
            recent_ranked = self._mentioned_apps(tuple(reversed(recent_texts)))
            recent = self._unique_best(recent_ranked)
            if recent is not None:
                app, grounded_from = recent
                if (
                    proposed is None
                    or proposed.app_id == app.app_id
                    or _alias_related(bounded_query, app.display_name)
                ):
                    return self._resolved(app, grounded_from)
                LOGGER.warning(
                    "Hands recent-app grounding conflict | planner_query=%r | "
                    "planner_app=%r | recent_app=%r | recent_app_id=%r",
                    bounded_query,
                    proposed.display_name if proposed is not None else None,
                    app.display_name,
                    app.app_id,
                )
                raise EntityResolutionError(
                    "planner-selected app target conflicts with the referenced recent app"
                )

        raise EntityResolutionError(
            "application target could not be grounded to one installed app identity"
        )
