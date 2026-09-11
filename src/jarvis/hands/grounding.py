"""Generic multilingual grounding for JARVIS Hands.

This module is deliberately independent of applications and languages. It answers one
question: does a provider-suggested material value have enough deterministic evidence in
the accepted USER conversation to be used by a governed capability?

Grounding never invents machine identity. Installed-app catalogues, observed UI state,
paths, URLs and other machine-owned sources remain authoritative. This layer only proves
that two human-facing strings are plausibly the same spoken material across scripts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from jarvis.hands.multilingual import phonetic_phrase_score, romanize


class GroundingMode(StrEnum):
    """How permissive cross-script matching may be for one material class."""

    ENTITY = "entity"
    SEARCH = "search"
    LITERAL = "literal"
    IDENTIFIER = "identifier"


_THRESHOLDS: dict[GroundingMode, float] = {
    # Human-facing fuzzy evidence is still an authorization boundary. Keep the floor
    # conservative: exact/romanized literal matches score above this naturally, while
    # unrelated conversational text must not become a machine target by resemblance.
    GroundingMode.ENTITY: 0.90,
    GroundingMode.SEARCH: 0.90,
    GroundingMode.LITERAL: 0.90,
    GroundingMode.IDENTIFIER: 1.0,
}


@dataclass(frozen=True, slots=True)
class GroundingProof:
    matched: bool
    score: float
    method: str
    source: str | None = None


class GroundingService:
    """Local, deterministic, fail-closed multilingual material grounding."""

    @staticmethod
    def normalized(value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        return " ".join(re.sub(r"[^\w]+", " ", text).split())

    @classmethod
    def spoken_punctuation(cls, value: object) -> str:
        text = str(value or "").casefold()
        for symbol, spoken in (
            ("\\", " backslash "),
            ("/", " slash "),
            ("_", " underscore "),
            ("-", " dash "),
            (".", " dot "),
        ):
            text = text.replace(symbol, spoken)
        return cls.normalized(text)

    @classmethod
    def _score_one(
        cls,
        value: object,
        source: str,
        *,
        mode: GroundingMode,
    ) -> tuple[float, str]:
        candidate = str(value or "").strip()
        if not candidate or not str(source or "").strip():
            return 0.0, "empty"

        normalized_candidate = cls.normalized(candidate)
        normalized_source = cls.normalized(source)
        if normalized_candidate and normalized_candidate in normalized_source:
            return 1.0, "literal"

        spoken = cls.spoken_punctuation(candidate)
        if spoken and spoken in normalized_source:
            return 1.0, "spoken_punctuation"

        # Identifiers/paths/package IDs remain strict. Cross-script fuzzy evidence is
        # reserved for human-facing entities, search terms and literal spoken payloads.
        if mode is GroundingMode.IDENTIFIER:
            return 0.0, "identifier_mismatch"

        roman_candidate = romanize(candidate)
        roman_source = romanize(source)
        if (
            roman_candidate
            and roman_source
            and (roman_candidate == roman_source or roman_candidate in roman_source)
        ):
            return 0.99, "romanized_literal"

        phonetic = phonetic_phrase_score(candidate, source)
        if phonetic > 0:
            return phonetic, "phonetic"
        return 0.0, "no_match"

    def prove(
        self,
        value: object,
        sources: tuple[str, ...],
        *,
        mode: GroundingMode = GroundingMode.ENTITY,
        threshold: float | None = None,
    ) -> GroundingProof:
        required = _THRESHOLDS[mode] if threshold is None else float(threshold)
        best = GroundingProof(False, 0.0, "no_match", None)
        for source in sources:
            score, method = self._score_one(value, source, mode=mode)
            if score > best.score:
                best = GroundingProof(score >= required, score, method, source)
        return best

    def related(
        self,
        left: object,
        right: object,
        *,
        mode: GroundingMode = GroundingMode.ENTITY,
        threshold: float | None = None,
    ) -> bool:
        forward = self.prove(left, (str(right or ""),), mode=mode, threshold=threshold)
        if forward.matched:
            return True
        reverse = self.prove(right, (str(left or ""),), mode=mode, threshold=threshold)
        return reverse.matched


DEFAULT_GROUNDING = GroundingService()
