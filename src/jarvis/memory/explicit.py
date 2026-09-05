"""Deterministic authorization and credential guards for explicit memory tools."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

from .provenance import MemorySource
from .types import AuthorityClass, MemorySourceClass, Sensitivity


class ExplicitMemoryAction(StrEnum):
    REMEMBER = "remember"
    CORRECT = "correct"
    FORGET = "forget"
    INSPECT = "inspect"


class ExplicitMemoryAuthorizationError(RuntimeError):
    pass


class MemorySecretRejectedError(ValueError):
    pass


_WHITESPACE = re.compile(r"\s+")
_NEGATION_PATTERNS = (
    re.compile(r"\b(?:do not|don't|dont|never)\b.{0,24}\b(?:remember|save|note|forget|delete|remove)\b"),
    re.compile(r"\b(?:mat|nahi|nahin)\b.{0,24}\b(?:yaad|bhool|save|delete|remove)\b"),
    re.compile(r"(?:मत|नहीं).{0,24}(?:याद|भूल|सेव|डिलीट)"),
)
_REMEMBER_PATTERNS = (
    re.compile(r"\bremember\b"),
    re.compile(r"\bsave\b.{0,24}\bmemory\b"),
    re.compile(r"\b(?:note|store)\b.{0,24}\b(?:this|that|memory)\b"),
    re.compile(r"\byaad\s+rakh(?:na)?\b"),
    re.compile(r"याद\s+रख"),
)
_REMEMBER_QUESTION_PATTERNS = (
    re.compile(r"\b(?:do|did|can)\s+you\s+remember\b"),
    re.compile(r"\bwhat\s+do\s+you\s+remember\b"),
    re.compile(r"\bkya\s+yaad\b"),
    re.compile(r"क्या\s+याद"),
)
_CORRECT_PATTERNS = (
    re.compile(r"\bcorrect\b"),
    re.compile(r"\bupdate\b.{0,24}\b(?:memory|remembered|stored)\b"),
    re.compile(r"\bchange\b.{0,24}\b(?:memory|remembered|stored)\b"),
    re.compile(r"\b(?:that(?:'s| is)|this is)\s+wrong\b"),
    re.compile(r"\bgalat\s+(?:hai|tha|thi)\b"),
    re.compile(r"गलत\s+(?:है|था|थी)"),
)
_FORGET_PATTERNS = (
    re.compile(r"\bforget\b"),
    re.compile(r"\b(?:remove|delete)\b.{0,32}\bmemory\b"),
    re.compile(r"\bbhool\s+ja(?:o)?\b"),
    re.compile(r"भूल\s+जा"),
)
_INSPECT_PATTERNS = (
    re.compile(r"\bwhat\s+do\s+you\s+remember\b"),
    re.compile(r"\bdo\s+you\s+remember\b"),
    re.compile(r"\bshow\b.{0,24}\bmemory\b"),
    re.compile(r"\bwhat\s+do\s+you\s+know\s+about\s+me\b"),
    re.compile(r"\bkya\s+yaad\b"),
    re.compile(r"\bkya\s+yaad\s+hai\b"),
    re.compile(r"क्या\s+याद"),
)
_SECRET_LABEL_PATTERNS = (
    re.compile(r"\bpassword\b"),
    re.compile(r"\bpasscode\b"),
    re.compile(r"\bpin\s*(?:number|code)?\b"),
    re.compile(r"\bapi[ _-]?key\b"),
    re.compile(r"\baccess[ _-]?key\b"),
    re.compile(r"\bclient[ _-]?secret\b"),
    re.compile(r"\b(?:access|refresh|session|auth)[ _-]?token\b"),
    re.compile(r"\botp\b"),
    re.compile(r"\bone[ -]?time\s+(?:password|code)\b"),
    re.compile(r"\b(?:recovery|backup)\s+code\b"),
    re.compile(r"\bprivate\s+key\b"),
    re.compile(r"\bseed\s+phrase\b"),
    re.compile(r"\bmnemonic\b"),
    re.compile(r"\bcvv\b"),
    re.compile(r"\b(?:password|pin|otp)\s+(?:yaad|remember)\b"),
    re.compile(r"पासवर्ड|पिन|ओटीपी|रिकवरी\s+कोड|प्राइवेट\s+की|सीड\s+फ्रेज"),
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _normalized(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _WHITESPACE.sub(" ", text.strip().casefold())


def latest_user_turn(conversation: ConversationSession) -> ConversationTurn:
    if not isinstance(conversation, ConversationSession):
        raise TypeError("conversation must be a ConversationSession")
    for turn in reversed(conversation.turns):
        if turn.role is ConversationRole.USER:
            return turn
    raise ExplicitMemoryAuthorizationError("no canonical user turn is available")


def authorize_explicit_memory_action(
    conversation: ConversationSession,
    action: ExplicitMemoryAction,
) -> ConversationTurn:
    if not isinstance(action, ExplicitMemoryAction):
        raise TypeError("action must be an ExplicitMemoryAction")
    turn = latest_user_turn(conversation)
    text = _normalized(turn.text)

    if action is not ExplicitMemoryAction.INSPECT and any(
        pattern.search(text) for pattern in _NEGATION_PATTERNS
    ):
        raise ExplicitMemoryAuthorizationError(
            f"latest user turn negates explicit {action.value} authorization"
        )

    patterns = {
        ExplicitMemoryAction.REMEMBER: _REMEMBER_PATTERNS,
        ExplicitMemoryAction.CORRECT: _CORRECT_PATTERNS,
        ExplicitMemoryAction.FORGET: _FORGET_PATTERNS,
        ExplicitMemoryAction.INSPECT: _INSPECT_PATTERNS,
    }[action]

    if action is ExplicitMemoryAction.REMEMBER and any(
        pattern.search(text) for pattern in _REMEMBER_QUESTION_PATTERNS
    ):
        raise ExplicitMemoryAuthorizationError(
            "latest user turn asks about memory rather than authorizing a write"
        )
    if not any(pattern.search(text) for pattern in patterns):
        raise ExplicitMemoryAuthorizationError(
            f"latest user turn does not explicitly authorize {action.value}"
        )
    return turn


def reject_prohibited_secret(*, predicate: str, value: str) -> None:
    combined = f"{predicate}\n{value}"
    normalized = _normalized(combined)
    if any(pattern.search(normalized) for pattern in _SECRET_LABEL_PATTERNS) or any(
        pattern.search(combined) for pattern in _SECRET_VALUE_PATTERNS
    ):
        raise MemorySecretRejectedError(
            "credentials and authentication secrets cannot be stored in JARVIS memory"
        )


def parse_memory_sensitivity(value: str) -> Sensitivity:
    if not isinstance(value, str):
        raise TypeError("sensitivity must be a string")
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    try:
        sensitivity = Sensitivity(normalized)
    except ValueError as exc:
        raise ValueError(
            "sensitivity must be standard, private, or local_only"
        ) from exc
    if sensitivity is Sensitivity.SECRET_PROHIBITED:
        raise MemorySecretRejectedError("secret-prohibited content cannot be stored")
    return sensitivity


def build_owner_explicit_source(
    *,
    conversation: ConversationSession,
    turn: ConversationTurn,
    sensitivity: Sensitivity,
    source_id: str | None = None,
    created_at: datetime | None = None,
) -> MemorySource:
    if not isinstance(conversation, ConversationSession):
        raise TypeError("conversation must be a ConversationSession")
    if not isinstance(turn, ConversationTurn) or turn.role is not ConversationRole.USER:
        raise TypeError("turn must be a canonical USER ConversationTurn")
    if turn not in conversation.turns:
        raise ExplicitMemoryAuthorizationError(
            "memory source turn does not belong to the active conversation"
        )
    if not isinstance(sensitivity, Sensitivity):
        raise TypeError("sensitivity must be a Sensitivity")
    if sensitivity is Sensitivity.SECRET_PROHIBITED:
        raise MemorySecretRejectedError("secret-prohibited content cannot be stored")
    resolved_source_id = source_id or str(uuid.uuid4())
    resolved_created_at = created_at or datetime.now(UTC)
    return MemorySource(
        source_id=resolved_source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"conversation:{conversation.session_id}:turn:{turn.turn_id}",
        observed_at=turn.accepted_at,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=sensitivity,
        created_at=resolved_created_at,
        evidence_text=None,
        evidence_hash=None,
        external_ref=None,
    )
