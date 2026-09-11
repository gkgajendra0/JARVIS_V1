"""Local multilingual normalization helpers for deterministic Hands grounding.

JARVIS must be able to ground a provider-suggested Latin app identity against a USER
transcript that may contain the same spoken name in Devanagari, Arabic/Urdu, or another
script.  This module keeps that evidence path local and deterministic:

- ICU provides Unicode script -> Latin transliteration.
- Jellyfish provides mature phonetic/string similarity primitives.
- A conservative consonant skeleton handles common code-mixed loanword spellings such
  as ``Apple Music`` vs ``एप्पल म्यूजिक`` without teaching JARVIS app-specific aliases.

The Windows installed-app catalogue remains the authority for app identity.  These
helpers only answer whether two user-facing strings are plausibly the same spoken name;
ambiguous catalogue matches still fail closed in the entity resolver.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

try:  # Installed by the unified ``hands`` extra; keep base imports graceful.
    import jellyfish
except ImportError:  # pragma: no cover - exercised only without the Hands extra.
    jellyfish = None  # type: ignore[assignment]

try:  # ``pyicu-wheels`` exposes the canonical ``icu`` import.
    from icu import Transliterator
except ImportError:  # pragma: no cover - exercised only without the Hands extra.
    Transliterator = None  # type: ignore[assignment,misc]

_WORD_RE = re.compile(r"[a-z0-9]+")
_REFERENCE_MARKERS = frozenset(
    {
        "again",
        "same",
        "repeat",
        "it",
        "that",
        "this",
        "one",
        # Common Hindi/Hinglish/Urdu conversational references after romanization.
        "phir",
        "fir",
        "dobara",
        "wahi",
        "usi",
        "isko",
        "usko",
        "ise",
    }
)


@lru_cache(maxsize=1)
def _latin_transliterator():
    if Transliterator is None:
        return None
    # Any-Latin is ICU's generic script romanizer; Latin-ASCII removes diacritics so
    # downstream comparison is stable across provider/transcript Unicode variants.
    return Transliterator.createInstance("Any-Latin; Latin-ASCII")


def _ascii_normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).casefold())
    ascii_text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii")
    return " ".join(_WORD_RE.findall(ascii_text))


@lru_cache(maxsize=2_048)
def romanize(value: str) -> str:
    """Return a bounded, comparison-oriented Latin representation.

    ASCII text is normalized without ICU.  Non-ASCII text requires the Hands
    transliteration dependency; if it is unavailable we fail closed by returning an
    empty string rather than pretending two cross-script strings match.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    if text.isascii():
        return _ascii_normalized(text)
    transliterator = _latin_transliterator()
    if transliterator is None:
        return ""
    try:
        transliterated = str(transliterator.transliterate(text))
    except Exception:  # ICU errors must not make grounding permissive.
        return ""
    return _ascii_normalized(transliterated)


def _phonetic_skeleton(token: str) -> str:
    """Collapse romanized loanword spelling differences conservatively."""

    value = _ascii_normalized(token).replace(" ", "")
    if not value:
        return ""
    for source, target in (
        ("tch", "c"),
        ("sch", "s"),
        ("sh", "s"),
        ("zh", "s"),
        ("ch", "c"),
        ("ph", "f"),
        ("th", "t"),
        ("dh", "d"),
        ("kh", "k"),
        ("gh", "g"),
        ("ck", "k"),
        ("qu", "k"),
    ):
        value = value.replace(source, target)
    value = value.translate(str.maketrans({"c": "k", "q": "k", "j": "s", "z": "s"}))
    value = value.replace("x", "ks")
    value = re.sub(r"[aeiouy]", "", value)
    value = re.sub(r"(.)\1+", r"\1", value)
    return value


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_skeleton = _phonetic_skeleton(left)
    right_skeleton = _phonetic_skeleton(right)
    if left_skeleton and left_skeleton == right_skeleton:
        return 1.0

    scores: list[float] = []
    if jellyfish is not None:
        try:
            scores.append(float(jellyfish.jaro_winkler_similarity(left, right)))
            if left_skeleton and right_skeleton:
                scores.append(
                    float(
                        jellyfish.jaro_winkler_similarity(
                            left_skeleton,
                            right_skeleton,
                        )
                    )
                )
            left_metaphone = str(jellyfish.metaphone(left) or "")
            right_metaphone = str(jellyfish.metaphone(right) or "")
            if left_metaphone and right_metaphone:
                scores.append(
                    float(
                        jellyfish.jaro_winkler_similarity(
                            left_metaphone,
                            right_metaphone,
                        )
                    )
                )
        except Exception:  # Optional similarity assistance must fail closed.
            pass
    return max(scores, default=0.0)


def phonetic_phrase_score(alias: object, text: object) -> float:
    """Score whether ``text`` contains the same spoken phrase as ``alias``.

    Matching is token-aligned and deliberately conservative.  A single badly matching
    token rejects the window, which prevents one shared brand word from grounding a
    different installed application.
    """

    alias_text = romanize(str(alias or ""))
    haystack = romanize(str(text or ""))
    alias_tokens = alias_text.split()
    text_tokens = haystack.split()
    if not alias_tokens or len(text_tokens) < len(alias_tokens):
        return 0.0

    best = 0.0
    width = len(alias_tokens)
    for start in range(len(text_tokens) - width + 1):
        window = text_tokens[start : start + width]
        token_scores = [
            _similarity(expected, actual)
            for expected, actual in zip(alias_tokens, window, strict=True)
        ]
        if min(token_scores, default=0.0) < 0.72:
            continue
        best = max(best, sum(token_scores) / len(token_scores))
    return best


def phonetic_alias_related(left: object, right: object) -> bool:
    left_text = romanize(str(left or ""))
    right_text = romanize(str(right or ""))
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    return (
        max(
            phonetic_phrase_score(left, right),
            phonetic_phrase_score(right, left),
        )
        >= 0.90
    )


def has_contextual_reference(value: object) -> bool:
    """Detect natural repeat/pronoun follow-ups across common supported scripts."""

    normalized = romanize(str(value or ""))
    if not normalized:
        return False
    for token in normalized.split():
        stem = token.rstrip("a")
        if any(
            token == marker
            or stem == marker
            or (len(marker) >= 3 and token.startswith(marker))
            for marker in _REFERENCE_MARKERS
        ):
            return True
    return False
