import pytest

from jarvis.memory.personal_context_projection import (
    PersonalContextRequest,
    parse_context_requests,
)
from jarvis.personal_learning_scope import SUPPRESSION_KEYS


def test_registered_scopes_are_accepted_without_coercion():
    for scope in SUPPRESSION_KEYS:
        result = parse_context_requests(
            [{"scope_key": scope}], question="My information?"
        )
        assert result[0].scope_key == scope and result[0].target_quote is None
    four = [{"scope_key": k} for k in sorted(SUPPRESSION_KEYS)[:4]]
    assert len(parse_context_requests(four, question="My plans?")) == 4


@pytest.mark.parametrize(
    "requests",
    [
        None,
        {},
        (),
        [],
        True,
        "vehicles",
        [{"scope_key": k} for k in sorted(SUPPRESSION_KEYS)[:5]],
        [{"scope_key": "owned_item.vehicle", "owner": "other"}],
        [{"scope_key": "home_address"}],
        [{"scope_key": True}],
        [{"scope_key": 1}],
        [{"scope_key": ["goal"]}],
        [{}],
        [False],
        [{"scope_key": "goal", "target_quote": None}],
        [{"scope_key": "goal", "target_quote": 123}],
        [{"scope_key": "goal", "target_quote": ""}],
        [{"scope_key": "goal", "target_quote": " "}],
        [{"scope_key": "food_preference", "target_quote": "food"}],
        [{"scope_key": "response_preference", "target_quote": "food"}],
        [{"scope_key": "goal"}, {"scope_key": "goal"}],
        [{"scope_key": "goal", "target_quote": "food"}] * 2,
    ],
)
def test_invalid_requests_cannot_select_facts(requests):
    with pytest.raises(ValueError):
        parse_context_requests(requests, question="food " * 100)


@pytest.mark.parametrize(
    "quote,question",
    [
        ("City", "Which City should I take?"),
        ("सिटी", "मेरी सिटी कैसी है?"),
        ("सिटी", "Meri सिटी kaisi hai?"),
        ("City ", "City ka mileage?"),
    ],
)
def test_current_question_quote_keeps_original_script(quote, question):
    result = parse_context_requests(
        [{"scope_key": "owned_item.vehicle", "target_quote": quote}], question=question
    )
    assert result[0].target_quote == quote


@pytest.mark.parametrize("quote", ["city", "सिटी", "Ｃｉｔｙ", "old label"])
def test_translated_normalized_or_previous_question_quotes_are_not_grounding(quote):
    with pytest.raises(ValueError):
        parse_context_requests(
            [{"scope_key": "owned_item.vehicle", "target_quote": quote}],
            question="What about City?",
        )


@pytest.mark.parametrize("quote", ["x" * 256, "अ" * 85 + "x"])
def test_quote_byte_boundary_is_256_not_character_count(quote):
    assert len(quote.encode("utf-8")) == 256
    assert (
        parse_context_requests(
            [{"scope_key": "goal", "target_quote": quote}], question=quote
        )[0].target_quote
        == quote
    )
    with pytest.raises(ValueError):
        parse_context_requests(
            [{"scope_key": "goal", "target_quote": quote + "x"}], question=quote + "x"
        )


def test_validated_models_are_revalidated_not_trusted_as_authority():
    request = PersonalContextRequest(scope_key="goal")
    assert parse_context_requests([request], question="My goal?") == (request,)
    forged = PersonalContextRequest.model_construct(scope_key="private_address")
    with pytest.raises(ValueError):
        parse_context_requests([forged], question="My information?")


@pytest.mark.parametrize("scope", [[], {}])
def test_structured_scope_values_are_invalid_not_parser_exceptions(scope):
    with pytest.raises(ValueError):
        parse_context_requests(
            [{"scope_key": scope, "target_quote": "City"}], question="City?"
        )


def test_learning_source_default_keeps_four_turn_window_and_original_byte_bound():
    from jarvis.conversation import ConversationRole, ConversationSession
    from jarvis.memory.learning_contracts import AcceptedLearningSource

    conversation = ConversationSession()
    conversation.start()
    for text in ("one", "two", "three", "four", "five"):
        latest = conversation.accept_turn(ConversationRole.USER, text)
    source = AcceptedLearningSource.from_turn("runtime", conversation, latest, now=100)
    assert [t.text for t in source.turns] == ["two", "three", "four", "five"]
    conversation.accept_turn(ConversationRole.USER, "x" * 8000)
    latest = conversation.accept_turn(ConversationRole.USER, "new")
    with pytest.raises(ValueError, match="8000"):
        AcceptedLearningSource.from_turn("runtime", conversation, latest, now=100)
