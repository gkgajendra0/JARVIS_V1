"""Real authority and canonical workers, with only OS/Hello substituted."""

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_checkpoint import EncryptedTopicCheckpointStore


def wake():
    conversation = ConversationSession()
    conversation.start()
    return conversation


def patch(text, action, value="", key=""):
    return {"action": action, "quote": text, "value": value, "key": key}


def coordinator(learning, clock):
    from jarvis.memory.topic_continuity import TopicContinuity

    return TopicContinuity(
        store=EncryptedTopicCheckpointStore(
            writer=learning.writer, reader=learning.reader
        ),
        authority=learning.authority,
        grant=learning.grant,
        accepted_plan_epoch=lambda _: 0,
        admit_source=lambda _: True,
        admit_snapshot=lambda *_: True,
        clock=clock,
    )


async def update(service, conversation, text, proposals=(), topic_hint=""):
    turn = conversation.accept_turn(ConversationRole.USER, text)
    service.observe_turn(conversation, turn)
    return await service.prepare(
        conversation,
        turn,
        topic_hint=topic_hint,
        proposals=list(proposals),
        authorize_read=lambda: True,
    )


@pytest.mark.asyncio
async def test_nepal_survives_sleep_and_restart_then_accepts_correction_and_forget(
    learning, clock
):
    service = coordinator(learning, clock)
    first = wake()
    result = await update(
        service,
        first,
        "I am planning a Nepal trip",
        [patch("I am planning a Nepal trip", "topic", "Nepal trip")],
    )
    assert result["status"] == "ready"
    assert result["context"]["title"] == "Nepal trip"
    result = await update(
        service,
        first,
        "My vehicle is a Jimny",
        [patch("My vehicle is a Jimny", "constraint", "Jimny", "vehicle")],
    )
    assert result["context"]["constraints"] == {"vehicle": "Jimny"}
    first.close()
    second = wake()
    result = await update(
        service,
        second,
        "The permits are already sorted",
        [patch("The permits are already sorted", "constraint", "sorted", "permits")],
    )
    assert result["context"]["title"] == "Nepal trip"
    assert result["context"]["constraints"] == {"vehicle": "Jimny", "permits": "sorted"}
    second.close()
    restarted = coordinator(learning, clock)
    third = wake()
    assert (await update(restarted, third, "Continue"))["status"] == "topic_required"
    result = await update(restarted, third, "Continue Nepal trip", topic_hint="Nepal")
    assert result["context"]["constraints"]["vehicle"] == "Jimny"
    await update(
        restarted,
        third,
        "Departure is 9 November",
        [patch("Departure is 9 November", "constraint", "9 November", "Departure")],
    )
    result = await update(
        restarted,
        third,
        "Correction departure is 10 November",
        [
            patch(
                "Correction departure is 10 November",
                "correct",
                "10 November",
                "departure",
            )
        ],
    )
    assert result["context"]["constraints"]["departure"] == "10 November"
    assert (
        await update(
            restarted,
            third,
            "Forget Nepal trip",
            [patch("Forget Nepal trip", "forget_topic")],
            topic_hint="Nepal",
        )
    )["status"] == "forgotten"
    assert (await update(service, wake(), "Continue Nepal trip", topic_hint="Nepal"))[
        "status"
    ] == "no_match"


@pytest.mark.asyncio
async def test_expired_continuation_requires_topic_name(learning, clock):
    service = coordinator(learning, clock)
    await update(
        service, wake(), "Nepal trip", [patch("Nepal trip", "topic", "Nepal trip")]
    )
    clock.advance(601)
    assert (await update(service, wake(), "Continue"))["status"] == "topic_required"


@pytest.mark.asyncio
async def test_revoked_owner_cannot_read_or_save(learning, clock):
    service = coordinator(learning, clock)
    await update(
        service, wake(), "Nepal trip", [patch("Nepal trip", "topic", "Nepal trip")]
    )
    learning.authority.revoke(learning.grant)
    with pytest.raises(PermissionError):
        await update(service, wake(), "Continue Nepal trip", topic_hint="Nepal")


@pytest.mark.asyncio
async def test_forged_quote_and_uncertain_vehicle_cannot_be_saved(learning, clock):
    service = coordinator(learning, clock)
    conversation = wake()
    await update(
        service,
        conversation,
        "Nepal trip",
        [patch("Nepal trip", "topic", "Nepal trip")],
    )
    with pytest.raises(ValueError):
        await update(
            service,
            conversation,
            "My vehicle is a Jimny",
            [patch("Invented", "constraint", "Jimny", "vehicle")],
        )
    result = await update(
        service,
        conversation,
        "My vehicle is Gemini",
        [patch("My vehicle is Gemini", "constraint", "Gemini", "vehicle")],
    )
    assert result["status"] == "confirmation_required"
    result = await update(
        service, conversation, "Continue Nepal trip", topic_hint="Nepal"
    )
    assert result["context"]["constraints"] == {}


@pytest.mark.asyncio
async def test_concurrent_checkpoint_change_cannot_lose_an_earlier_vehicle_update(
    learning, clock, monkeypatch
):
    first = coordinator(learning, clock)
    await update(
        first, wake(), "Nepal trip", [patch("Nepal trip", "topic", "Nepal trip")]
    )
    earlier = wake()
    earlier_text = "Nepal trip my vehicle is a Jimny"
    earlier_turn = earlier.accept_turn(ConversationRole.USER, earlier_text)
    first.observe_turn(earlier, earlier_turn)
    later = coordinator(learning, clock)
    original = later.store.save

    async def race(*args, **kwargs):
        await first.prepare(
            earlier,
            earlier_turn,
            topic_hint="Nepal",
            proposals=[patch(earlier_text, "constraint", "Jimny", "vehicle")],
            authorize_read=lambda: True,
        )
        return await original(*args, **kwargs)

    monkeypatch.setattr(later.store, "save", race)
    with pytest.raises(PermissionError):
        await update(
            later,
            wake(),
            "Nepal trip permits are sorted",
            [patch("Nepal trip permits are sorted", "constraint", "sorted", "permits")],
            topic_hint="Nepal",
        )
    result = await update(first, wake(), "Continue Nepal trip", topic_hint="Nepal")
    assert result["context"]["constraints"] == {"vehicle": "Jimny"}


@pytest.mark.asyncio
async def test_update_after_commit_cannot_stamp_stale_result_with_new_revision(
    learning, clock, monkeypatch
):
    service = coordinator(learning, clock)
    await update(
        service, wake(), "Nepal trip", [patch("Nepal trip", "topic", "Nepal trip")]
    )
    original = service.store.save

    async def race(*args, **kwargs):
        saved = await original(*args, **kwargs)
        await learning.writer.run(
            lambda c: (
                c.execute(
                    "UPDATE conversation_topic_checkpoint SET state_json=replace(state_json, 'Jimny', 'Other')"
                ),
                c.commit(),
            )
        )
        return saved

    monkeypatch.setattr(service.store, "save", race)
    with pytest.raises(PermissionError):
        await update(
            service,
            wake(),
            "My vehicle is a Jimny",
            [patch("My vehicle is a Jimny", "constraint", "Jimny", "vehicle")],
        )


@pytest.mark.asyncio
async def test_model_quote_cannot_hide_that_canonical_source_is_a_question(
    learning, clock
):
    from jarvis.memory.topic_continuity_policy import (
        standard_plan_snapshot,
        standard_plan_source,
    )

    service = coordinator(learning, clock)
    service._source_allowed, service._snapshot_allowed = (
        standard_plan_source,
        standard_plan_snapshot,
    )
    conversation = wake()
    await update(
        service,
        conversation,
        "Nepal trip",
        [patch("Nepal trip", "topic", "Nepal trip")],
    )
    with pytest.raises(ValueError):
        await update(
            service,
            conversation,
            "Is my vehicle a Jimny?",
            [patch("my vehicle a Jimny", "constraint", "Jimny", "vehicle")],
        )
    result = await update(
        service, conversation, "Continue Nepal trip", topic_hint="Nepal"
    )
    assert result["context"]["constraints"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "I cannot confirm my vehicle is Gemini",
        "My vehicle is Gemini, not confirmed",
        "Can you confirm my vehicle is Gemini?",
    ],
)
async def test_negated_or_interrogative_confirmation_never_saves_gemini(
    learning, clock, text
):
    service = coordinator(learning, clock)
    conversation = wake()
    await update(
        service,
        conversation,
        "Nepal trip",
        [patch("Nepal trip", "topic", "Nepal trip")],
    )
    result = await update(
        service, conversation, text, [patch(text, "constraint", "Gemini", "vehicle")]
    )
    assert result["status"] == "confirmation_required"
    result = await update(
        service, conversation, "Continue Nepal trip", topic_hint="Nepal"
    )
    assert result["context"]["constraints"] == {}


@pytest.mark.asyncio
async def test_rotated_grant_cannot_inherit_old_automatic_topic_selection(
    learning, clock
):
    service = coordinator(learning, clock)
    await update(
        service, wake(), "Nepal trip", [patch("Nepal trip", "topic", "Nepal trip")]
    )
    service.grant = learning.authority.open("new-owner-runtime", "gemini")
    assert (await update(service, wake(), "Continue"))["status"] == "topic_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text", ["Confirmed, my vehicle is Gemini", "I confirm that my vehicle is Gemini"]
)
async def test_positive_explicit_vehicle_confirmation_can_be_saved(
    learning, clock, text
):
    service = coordinator(learning, clock)
    conversation = wake()
    await update(
        service,
        conversation,
        "Nepal trip",
        [patch("Nepal trip", "topic", "Nepal trip")],
    )
    result = await update(
        service, conversation, text, [patch(text, "constraint", "Gemini", "vehicle")]
    )
    assert result["context"]["constraints"]["vehicle"] == "Gemini"


@pytest.mark.asyncio
async def test_uncertain_vehicle_cannot_bypass_confirmation_with_an_article(
    learning, clock
):
    service = coordinator(learning, clock)
    conversation = wake()
    await update(
        service,
        conversation,
        "Nepal trip",
        [patch("Nepal trip", "topic", "Nepal trip")],
    )
    text = "My vehicle is a Gemini"
    result = await update(
        service, conversation, text, [patch(text, "constraint", "a Gemini", "vehicle")]
    )
    assert result["status"] == "confirmation_required"
