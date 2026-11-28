"""An explicitly saved standard fact can be read back, corrected and forgotten.

Live voice acceptance, 27 Nov 2026: "Remember that my home city is Jaipur."
was approved and committed as a plain-text "home_city" record (receipt
"Saved: home_city."), and every later read missed it: in a learning session
owner-memory reads see only registered personal-learning records
(personal_learning_scope.record_scope), and a plain "home_city" record has
no registered scope. It also could not be targeted for correction or
deletion through those reads.

In such a session an explicit standard fact outside the registered facets is
stored as a personal_fact in the registered shape, with owner-explicit
provenance: it is in read scope, correction keeps its shape, forgetting
removes it, and the personal_fact suppression applies. Nothing is added to an
allowlist: a plain record stays out of scope.
"""

from types import SimpleNamespace

import pytest
from test_runtime import conversation

from jarvis.conversation import ConversationRole
from jarvis.memory.explicit import build_owner_explicit_source
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.types import MemorySourceClass, Sensitivity


def _source(c, text):
    turn = c.accept_turn(ConversationRole.USER, text)
    return build_owner_explicit_source(
        conversation=c, turn=turn, sensitivity=Sensitivity.STANDARD
    )


async def _scoped(learning):
    return {
        (record.predicate, scope): record
        for record, scope in await learning.service.canonical_reader.learning_current_scoped()
    }


@pytest.mark.asyncio
async def test_the_recorded_plain_home_city_record_is_out_of_read_scope(learning):
    c = conversation()
    await learning.service.remember_text(
        predicate="home_city",
        value="Jaipur",
        source=_source(c, "Remember that my home city is Jaipur."),
    )
    assert not any(p == "home_city" for p, _ in await _scoped(learning))


@pytest.mark.asyncio
async def test_an_explicit_personal_fact_is_read_corrected_and_forgotten(learning):
    c = conversation()
    saved = await learning.service.remember_personal_fact(
        label="home city",
        value="Jaipur",
        source=_source(c, "Remember that my home city is Jaipur."),
    )
    scoped = await _scoped(learning)
    record = scoped[(saved.predicate, "personal_fact")]
    assert record.value["label"] == "home city"
    assert record.value["value"] == "Jaipur"
    # The learning session's facet catalog (what correct/forget target) has it.
    retrieval = SemanticRetrievalService(learning.reader)
    catalog = await retrieval.learning_facet_catalog()
    assert any(f.predicate == saved.predicate for f in catalog.facets)
    assert await retrieval.learning_record_in_scope(record.assertion_id)

    corrected = await learning.service.correct_text(
        predicate=saved.predicate,
        value="Udaipur",
        source=_source(c, "Correction, my home city is Udaipur."),
        expected_assertion_id=record.assertion_id,
    )
    after = (await _scoped(learning))[(saved.predicate, "personal_fact")]
    assert after.assertion_id == corrected.record.assertion_id
    assert after.value == {**record.value, "value": "Udaipur"}

    await learning.service.forget_exact(
        predicate=saved.predicate,
        source=_source(c, "Forget my home city."),
        expected_assertion_id=after.assertion_id,
    )
    assert (saved.predicate, "personal_fact") not in await _scoped(learning)


@pytest.mark.asyncio
async def test_the_same_label_twice_asks_for_a_correction(learning):
    from jarvis.memory.service import MemoryAlreadyExistsError

    c = conversation()
    await learning.service.remember_personal_fact(
        label="home city", value="Jaipur", source=_source(c, "My home city is Jaipur.")
    )
    with pytest.raises(MemoryAlreadyExistsError):
        await learning.service.remember_personal_fact(
            label="Home City",
            value="Udaipur",
            source=_source(c, "My home city is Udaipur."),
        )


@pytest.mark.asyncio
async def test_provenance_stays_owner_explicit(learning):
    c = conversation()
    saved = await learning.service.remember_personal_fact(
        label="home city", value="Jaipur", source=_source(c, "My home city is Jaipur.")
    )
    classes = await learning.reader.run(
        lambda connection: connection.execute(
            "SELECT s.source_class FROM memory_source s JOIN semantic_assertion a "
            "ON a.source_id = s.source_id WHERE a.assertion_id=?",
            (saved.record.assertion_id,),
        ).fetchall()
    )
    assert classes == [(MemorySourceClass.OWNER_EXPLICIT.value,)]


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped_reads", [True, False])
async def test_remember_memory_picks_the_readable_shape_for_the_session(
    learning, scoped_reads
):
    from jarvis.voice.memory_tools import MemoryAgentTools

    c = conversation()
    c.accept_turn(ConversationRole.USER, "Remember that my home city is Jaipur.")
    tools = MemoryAgentTools(learning.service, c)
    tools._personal_context = SimpleNamespace(learning_scoped_reads=scoped_reads)
    assert (
        tools._readable_only_as_personal_fact("home_city", Sensitivity.STANDARD)
        is scoped_reads
    )
    # Registered facets and sensitive facts keep their existing paths.
    assert not tools._readable_only_as_personal_fact(
        "diet_preference", Sensitivity.STANDARD
    )
    assert not tools._readable_only_as_personal_fact("home_city", Sensitivity.PRIVATE)


def test_the_receipt_names_the_fact_in_words():
    from jarvis.voice.memory_tools import _receipt_label

    assert _receipt_label({"predicate": "home_city"}) == "home city"
    assert (
        _receipt_label({"predicate": "personal_fact_ab12", "label": "home city"})
        == "home city"
    )


def test_memory_status_is_never_an_answer_about_stored_facts():
    import inspect

    from jarvis.memory.memory_receipts import MemoryReceipts
    from jarvis.voice.memory_tools import MemoryAgentTools

    doc = inspect.getsource(MemoryAgentTools)
    assert "not an answer about stored facts" in doc
    rule = MemoryReceipts().view("s", [])["rule"]
    assert "never answers what a stored fact is" in rule
