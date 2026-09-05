from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.explicit import (
    ExplicitMemoryAction,
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    authorize_explicit_memory_action,
    build_owner_explicit_source,
    parse_memory_sensitivity,
    reject_prohibited_secret,
)
from jarvis.memory.types import AuthorityClass, MemorySourceClass, Sensitivity

BASE = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


def _conversation(text: str) -> ConversationSession:
    conversation = ConversationSession(session_id="session-1")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    return conversation


@pytest.mark.parametrize(
    ("action", "text"),
    [
        (ExplicitMemoryAction.REMEMBER, "Remember that my Jimny tyre size is 235/75 R15."),
        (ExplicitMemoryAction.REMEMBER, "Mera tyre size 235/75 R15 yaad rakhna."),
        (ExplicitMemoryAction.REMEMBER, "याद रखो कि मेरा टायर साइज़ 235/75 R15 है।"),
        (ExplicitMemoryAction.CORRECT, "That memory is wrong; it is 215/75 R15."),
        (ExplicitMemoryAction.CORRECT, "Nahi, galat hai. Tyre size 215/75 R15 hai."),
        (ExplicitMemoryAction.CORRECT, "नहीं, गलत है। टायर साइज़ 215/75 R15 है।"),
        (ExplicitMemoryAction.FORGET, "Forget my Jimny tyre size."),
        (ExplicitMemoryAction.FORGET, "Mera tyre size bhool jao."),
        (ExplicitMemoryAction.FORGET, "मेरा टायर साइज़ भूल जाओ।"),
        (ExplicitMemoryAction.INSPECT, "What do you remember about my Jimny tyre size?"),
        (ExplicitMemoryAction.INSPECT, "Mere tyre size ke baare mein kya yaad hai?"),
        (ExplicitMemoryAction.INSPECT, "मेरे टायर साइज़ के बारे में क्या याद है?"),
    ],
)
def test_explicit_action_guard_accepts_bounded_multilingual_cues(
    action: ExplicitMemoryAction,
    text: str,
) -> None:
    conversation = _conversation(text)
    turn = authorize_explicit_memory_action(conversation, action)
    assert turn.role is ConversationRole.USER
    assert turn.text == text


@pytest.mark.parametrize(
    ("action", "text"),
    [
        (ExplicitMemoryAction.REMEMBER, "Do not remember this tyre size."),
        (ExplicitMemoryAction.REMEMBER, "What do you remember about my tyre size?"),
        (ExplicitMemoryAction.REMEMBER, "Mera password yaad mat rakhna."),
        (ExplicitMemoryAction.FORGET, "Do not forget my tyre size."),
        (ExplicitMemoryAction.FORGET, "Tyre size bhoolna mat."),
        (ExplicitMemoryAction.CORRECT, "Tell me what correction means."),
    ],
)
def test_mutation_guard_rejects_negated_discussed_or_wrong_action_cues(
    action: ExplicitMemoryAction,
    text: str,
) -> None:
    with pytest.raises(ExplicitMemoryAuthorizationError):
        authorize_explicit_memory_action(_conversation(text), action)


def test_latest_canonical_user_turn_is_authority_not_assistant_output() -> None:
    conversation = ConversationSession(session_id="session-1")
    conversation.start()
    user_turn = conversation.accept_turn(
        ConversationRole.USER,
        "Remember that my home city is Sagar.",
    )
    conversation.accept_turn(
        ConversationRole.ASSISTANT,
        "I will remember your password if you tell me.",
    )

    assert (
        authorize_explicit_memory_action(conversation, ExplicitMemoryAction.REMEMBER)
        is user_turn
    )


def test_explicit_source_uses_jarvis_refs_and_never_copies_raw_utterance() -> None:
    conversation = _conversation("Remember that my home city is Sagar.")
    turn = authorize_explicit_memory_action(
        conversation,
        ExplicitMemoryAction.REMEMBER,
    )
    source = build_owner_explicit_source(
        conversation=conversation,
        turn=turn,
        sensitivity=Sensitivity.PRIVATE,
        source_id="source-1",
        created_at=BASE,
    )

    assert source.source_id == "source-1"
    assert source.source_class is MemorySourceClass.OWNER_EXPLICIT
    assert source.authority_class is AuthorityClass.OWNER_EXPLICIT
    assert source.sensitivity is Sensitivity.PRIVATE
    assert source.canonical_ref == f"conversation:session-1:turn:{turn.turn_id}"
    assert source.observed_at == turn.accepted_at
    assert source.evidence_text is None
    assert source.evidence_hash is None
    assert source.external_ref is None


@pytest.mark.parametrize(
    ("predicate", "value"),
    [
        ("password", "correct horse battery staple"),
        ("api key", "abc123"),
        ("github token", "ghp_abcdefghijklmnopqrstuvwxyz123456"),
        ("note", "sk-abcdefghijklmnopqrstuvwxyz"),
        ("otp", "123456"),
        ("recovery code", "ABCD-EFGH"),
        ("private key", "-----BEGIN PRIVATE KEY-----\nsecret"),
        ("पासवर्ड", "mera secret"),
    ],
)
def test_obvious_credentials_are_rejected(predicate: str, value: str) -> None:
    with pytest.raises(MemorySecretRejectedError):
        reject_prohibited_secret(predicate=predicate, value=value)


def test_normal_personal_fact_is_not_secret_prohibited() -> None:
    reject_prohibited_secret(predicate="jimny tyre size", value="235/75 R15")
    reject_prohibited_secret(predicate="home city", value="Sagar")


def test_memory_sensitivity_parser_allows_only_non_secret_classes() -> None:
    assert parse_memory_sensitivity("standard") is Sensitivity.STANDARD
    assert parse_memory_sensitivity("private") is Sensitivity.PRIVATE
    assert parse_memory_sensitivity("local only") is Sensitivity.LOCAL_ONLY
    with pytest.raises(MemorySecretRejectedError):
        parse_memory_sensitivity("secret_prohibited")
    with pytest.raises(ValueError):
        parse_memory_sensitivity("public")
