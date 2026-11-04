"""Conservative plan-only eligibility for the explicit continuity runtime.

This is a bounded application policy, not a universal privacy classifier.
Ordinary unrelated conversation is not admitted to topic storage. Owner consent,
canonical evidence and transaction-time plan suppression are separate gates.
"""

import re

from jarvis.conversation import ConversationRole, ConversationTurn

from .conversation_checkpoint import _snapshot_payload
from .explicit import (
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    reject_negated_memory_change,
    reject_prohibited_secret,
)

_RESTRICTED = re.compile(
    r"\b(?:password|passcode|secret|token|credential|otp|passport|aadhaar|pan\s+card|"
    r"account|bank|card\s+number|medical|diagnos\w*|disease|medicat\w*|health|"
    r"salary|loan|balance|private|confidential|address|phone\s+number|"
    r"friend['’]?s|wife['’]?s|husband['’]?s|client['’]?s)\b|"
    r"पासवर्ड|बीमारी|खाता|आधार|गुप्त|निजी",
    re.IGNORECASE,
)
_PLAN_SCOPE = re.compile(
    r"\b(?:trip|travel|journey|route|vehicle|permit\w*|document\w*|budget|"
    r"departure|flight|hotel|project|plan\w*|deadline|milestone|task|"
    r"continue|resume|forget|delete|correction)\b|यात्रा|योजना|रूट|बजट",
    re.IGNORECASE,
)


def _standard_text(text):
    if _RESTRICTED.search(text):
        return False
    try:
        reject_negated_memory_change(text)
        reject_prohibited_secret(predicate="", value=text)
    except (ExplicitMemoryAuthorizationError, MemorySecretRejectedError):
        return False
    return True


def standard_plan_source(turn):
    return (
        isinstance(turn, ConversationTurn)
        and turn.role is ConversationRole.USER
        and len(turn.text.encode("utf-8")) <= 4000
        and bool(_PLAN_SCOPE.search(turn.text))
        and _standard_text(turn.text)
    )


def standard_plan_snapshot(snapshot, turn):
    return standard_plan_source(turn) and _standard_text(_snapshot_payload(snapshot))
