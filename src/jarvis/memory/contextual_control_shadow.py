"""Research-only distinction: explicit memory commands vs conversational corrections.

The existing Phase-4.3 explicit authorization function is NOT modified.
This module is used ONLY by opt-in contextual revision shadows, which never
write or release memory. No decision here authorizes a real memory action.

Reason: the legacy explicit recognizer treats bare "galat tha"/"that's wrong"
as an explicit CORRECT command even when no memory action was requested.
In a shadow analysis we may examine those sentences *as evidence* without
enabling any mutation or bypassing real tool authorization.
"""

from __future__ import annotations

import re
from enum import StrEnum

from .explicit import is_explicit_memory_control_text


class ContextualBoundaryDisposition(StrEnum):
    CONTEXT_REVIEW = "context_review"
    EXPLICIT_CONTROL = "explicit_control"


_STRONG_MEMORY_COMMAND = (
    # Explicit memory verbs or phrases, not bare natural-language disagreement.
    re.compile(r"\b(?:remember|forget|inspect)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:save|store|delete|remove|correct|update|show|change)\b"
        r".{0,42}\b(?:memory|memories|remembered|stored)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:yaad\s+rakh(?:na)?|bhool\s+ja(?:o)?)\b", re.IGNORECASE),
    re.compile(r"\b(?:kya\s+yaad|yaad\s+hai)\b", re.IGNORECASE),
    re.compile(r"(?:याद\s+रख|भूल\s+जा|क्या\s+याद)", re.IGNORECASE),
    re.compile(r"\b(?:that|this|my|the)\s+memory\s+is\s+wrong\b", re.IGNORECASE),
)


def assess_contextual_memory_boundary(text: str) -> ContextualBoundaryDisposition:
    """Assess only the eligibility of an *offline* contextual review.

    No claims of complete multilingual intent detection. Return
    EXPLICIT_CONTROL whenever an existing recognized action appears to
    contain an actual memory command; bare "wrong"/"galat" should not
    falsely block a review-only natural-language revision.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not text.strip():
        raise ValueError("text must not be empty")
    if not is_explicit_memory_control_text(text):
        return ContextualBoundaryDisposition.CONTEXT_REVIEW
    if any(pattern.search(text) for pattern in _STRONG_MEMORY_COMMAND):
        return ContextualBoundaryDisposition.EXPLICIT_CONTROL
    return ContextualBoundaryDisposition.CONTEXT_REVIEW
