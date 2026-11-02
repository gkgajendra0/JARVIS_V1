"""Detect what a spoken reply claims about project changes.

Used to check Jarvis's committed reply against the action the application
actually committed (created / switched / nothing), and by the acceptance
report. Deliberately narrow: only affirmative sentences that say a project
was created or that the owner was switched. Negated sentences ("No project
was created") are not claims.
"""

from __future__ import annotations

import re

_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_NEGATION = re.compile(
    r"\b(?:no|not|nothing|never|cannot|didn['’]?t|wasn['’]?t|haven['’]?t|"
    r"hasn['’]?t|couldn['’]?t|won['’]?t|isn['’]?t|aren['’]?t)\b|n['’]t\b",
    re.IGNORECASE,
)
_CREATED = re.compile(
    r"\b(?:created|made|set\s+up|started|opened|added)\b[^.!?]{0,40}\bprojects?\b"
    r"|\bprojects?\b[^.!?]{0,40}\b(?:created|has\s+been\s+created|is\s+(?:now\s+)?ready|set\s+up)\b"
    r"|\bnew\s+project\b[^.!?]{0,30}\b(?:ready|created|set\s+up)\b",
    re.IGNORECASE,
)
_SWITCHED = re.compile(
    r"\b(?:switched|switching)\b[^.!?]{0,25}\bto\b"
    r"|\byou(?:['’]re|\s+are)\s+now\s+in\b|\bnow\s+in\s+(?:the\s+|your\s+)?project\b",
    re.IGNORECASE,
)

_ALLOWED = {
    "created": {"created"},
    "switched": {"switched"},
    "new_thread": {"created"},  # "new conversation" may be phrased as started
}


def project_claims(text: str) -> set[str]:
    claims = set()
    for sentence in _SENTENCES.split(text or ""):
        if _NEGATION.search(sentence):
            continue
        if _CREATED.search(sentence):
            claims.add("created")
        if _SWITCHED.search(sentence):
            claims.add("switched")
    return claims


def false_project_claims(text: str, action: str | None) -> set[str]:
    """Claims in ``text`` that the committed ``action`` does not support."""
    return project_claims(text) - _ALLOWED.get(action or "", set())
