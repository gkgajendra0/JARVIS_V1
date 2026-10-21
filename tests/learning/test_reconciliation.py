import json

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_reconciliation import LearningReconciler


def inputs(text, values, intent="new"):
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, text)
    source = AcceptedLearningSource.from_turn("runtime", c, t, now=100)
    batch = LearningBatch(
        candidates=[
            LearningCandidate(
                category="owned_item",
                kind="vehicle",
                intent=intent,
                label=v,
                value=v,
                state="not_owned" if intent == "change" else "owned",
                evidence=[EvidenceSpan(turn_id=t.turn_id, start=0, end=len(text))],
            )
            for v in values
        ]
    )
    return source, batch


def resolutions(*items):
    return LearningResolutionBatch(
        resolutions=[
            LearningResolution(candidate_index=i, decision=decision, target_id=target)
            for i, (decision, target) in enumerate(items)
        ]
    )


def entry(id, label, predicate=None):
    return LearningCatalogEntry(
        assertion_id=id,
        predicate=predicate or f"owned_item_{id}",
        category="owned_item",
        text=label,
        value=json.dumps(
            {
                "schema": "personal-learning-v1",
                "category": "owned_item",
                "kind": "vehicle",
                "label": label,
                "value": label,
                "state": "owned",
            }
        ),
        kind="vehicle",
    )


def test_two_vehicles_have_independent_server_identities():
    s, b = inputs("I own City and Classic", ["City", "Classic"])
    plan = LearningReconciler(None, None).plan(
        s, b, LearningCatalog(), resolutions(("new", None), ("new", None))
    )
    assert len(plan.mutations) == 2
    assert len({m.predicate for m in plan.mutations}) == 2
    assert all(m.action == "create" for m in plan.mutations)
    assert plan.binding().payload_sha256 == plan.digest


def test_sale_targets_only_actual_bike_version():
    s, b = inputs("I sold Classic", ["Classic"], "change")
    catalog = LearningCatalog(entries=[entry("car", "City"), entry("bike", "Classic")])
    plan = LearningReconciler(None, None).plan(
        s, b, catalog, resolutions(("match", "bike"))
    )
    assert len(plan.mutations) == 1
    m = plan.mutations[0]
    assert m.expected_assertion_id == "bike" and m.action == "change"
    assert m.draft.value["state"] == "not_owned"


def test_exact_duplicate_cannot_be_reinvented_as_new():
    s, b = inputs("City is mine", ["City"])
    catalog = LearningCatalog(entries=[entry("car", "City")])
    plan = LearningReconciler(None, None).plan(
        s, b, catalog, resolutions(("new", None))
    )
    assert plan.mutations == ()


def test_ambiguous_and_unknown_target_have_no_effect():
    s, b = inputs("I sold City", ["City"], "change")
    catalog = LearningCatalog(entries=[entry("one", "City"), entry("two", "City")])
    for result in [
        resolutions(("uncertain", None)),
        resolutions(("match", "invented")),
        resolutions(("match", "one")),
    ]:
        assert not LearningReconciler(None, None).plan(s, b, catalog, result).mutations


def test_legacy_plural_text_is_preserved():
    s, b = inputs("I own City", ["City"])
    old = LearningCatalogEntry(
        assertion_id="old",
        predicate="vehicles",
        category="legacy",
        text="City and Classic",
        value="City and Classic",
    )
    assert (
        not LearningReconciler(None, None)
        .plan(s, b, LearningCatalog(entries=[old]), resolutions(("match", "old")))
        .mutations
    )


def test_semantic_duplicate_is_not_a_lowercase_update():
    s, b = inputs("मेरे पास सिटी है", ["सिटी"])
    plan = LearningReconciler(None, None).plan(
        s,
        b,
        LearningCatalog(entries=[entry("car", "City")]),
        resolutions(("duplicate", "car")),
    )
    assert not plan.mutations


def test_routine_schedule_change_replaces_supported_value_and_preserves_identity():
    s, b = inputs("My evening walk is now at 6 pm", ["evening walk"], "change")
    candidate = b.candidates[0].model_copy(
        update={
            "category": "routine",
            "kind": "other",
            "value": "6 pm",
            "state": "active",
        }
    )
    prior = LearningCatalogEntry(
        assertion_id="routine",
        predicate="routine_stable",
        category="routine",
        text="evening walk at 5 pm",
        value=json.dumps(
            {
                "schema": "personal-learning-v1",
                "category": "routine",
                "label": "evening walk",
                "value": "5 pm",
                "state": "active",
                "kind": "other",
            }
        ),
    )
    plan = LearningReconciler(None, None).plan(
        s,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=[prior]),
        resolutions(("match", "routine")),
    )
    assert plan.mutations[0].draft.value["value"] == "6 pm"
    assert "6 pm" in plan.mutations[0].draft.normalized_text
