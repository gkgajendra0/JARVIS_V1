from dataclasses import replace

import pytest

from jarvis.model_routing.models import RoutingAttemptKind
from jarvis.model_routing.store import RoutingStoreError

from .helpers import make_router, scoped_request


def test_scoped_decision_creates_no_workitem(tmp_path):
    router, store = make_router(tmp_path)
    request = scoped_request()
    selected = router.route(request)
    assert selected.target.credential_ref == "GOOGLE_API_KEY"
    assert selected.reused_decision is False
    saved = store.find_scoped_decision_by_request("scope-request-1")
    assert (saved.scope_kind, saved.scope_id) == ("memory", "source-1")
    assert not hasattr(request, "work_id")
    with store.work_store.extension_transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
    again = router.route(request)
    assert again.reused_decision and again.decision == selected.decision


def test_request_id_cannot_rebind_scope_or_privacy(tmp_path):
    from jarvis.model_routing.models import PrivacyClass
    from jarvis.model_routing.router import RoutingProvenanceError

    router, _ = make_router(tmp_path)
    request = scoped_request()
    router.route(request)
    for changed in (
        replace(request, scope_id="other-source"),
        replace(request, privacy_class=PrivacyClass.LOCAL_ONLY),
        replace(request, estimated_context_tokens=10000),
    ):
        with pytest.raises(RoutingProvenanceError):
            router.route(changed)


def test_scoped_attempt_is_bound_to_decision_and_survives_restart(tmp_path):
    from jarvis.model_routing.models import ScopedRoutingAttempt

    router, store = make_router(tmp_path)
    decision = router.route(scoped_request()).decision
    attempt = ScopedRoutingAttempt(
        attempt_id="scope-attempt-1",
        decision_id=decision.decision_id,
        scope_kind="memory",
        scope_id="source-1",
        target_id=decision.selected_target_id,
        attempt_ordinal=1,
        started_at_epoch=100,
        kind=RoutingAttemptKind.PRIMARY,
    )
    store.record_scoped_attempt(attempt)
    _, restarted = make_router(tmp_path)
    assert restarted.list_scoped_attempts(decision.decision_id) == (attempt,)
    with pytest.raises(RoutingStoreError):
        store.record_scoped_attempt(replace(attempt, scope_id="other"))
    with pytest.raises(RoutingStoreError):
        store.record_scoped_attempt(replace(attempt, target_id="unregistered"))


@pytest.mark.parametrize(
    "changes",
    [
        {"scope_kind": "work"},
        {"scope_id": ""},
        {"scope_kind": "unknown"},
        {"estimated_context_tokens": -1},
        {"strategy_version": False},
    ],
)
def test_scoped_request_validates_common_and_scope_facts(changes):
    with pytest.raises((ValueError, TypeError)):
        scoped_request(**changes)


def test_default_eligibility_does_not_borrow_free_key_for_paid(tmp_path, monkeypatch):
    from jarvis.model_routing.registry import RoutingStrategyRegistry
    from jarvis.model_routing.router import ModelRouter

    from .helpers import Strategy

    monkeypatch.setenv("GOOGLE_API_KEY", "free-canary")
    original, store = make_router(tmp_path)
    router = ModelRouter(
        target_registry=original.target_registry,
        adapter_registry=original.adapter_registry,
        strategy_registry=RoutingStrategyRegistry((Strategy(),)),
        routing_store=store,
        clock=lambda: 100,
    )
    selected = router.route(scoped_request())
    assert selected.eligibility.eligible_target_ids == ("work.gemini.free.gemini-test",)
