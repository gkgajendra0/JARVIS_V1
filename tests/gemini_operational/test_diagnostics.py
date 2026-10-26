from dataclasses import replace

import pytest

from jarvis.capabilities.authority_bridge import CapabilityAuthorizationError
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.model_routing.live_policy import digest

from .admin_helpers import broker
from .test_governor import reserve


def plan(env, **changes):
    from jarvis.voice.gemini_live_diagnostics import LiveDiagnosticPlan

    values = {
        "target_id": env.target.target_id,
        "model_id": env.target.model_id,
        "policy_ref": env.policy.fingerprint,
        "price_ref": digest(env.price.to_payload()),
        "profile_ref": env.profile.fingerprint,
        "fixture_ref": digest("fictional-colour-blue"),
        "nonce": "one-fixed-experiment",
        "faults": ("free_quota",),
        "max_connections": 1,
        "max_generations": 1,
        "max_seconds": 15,
        "scope": "qualification_capture",
    }
    return LiveDiagnosticPlan(**(values | changes))


def test_diagnostic_requires_exact_financial_authorization(op_env):
    from jarvis.voice.gemini_live_diagnostics import (
        authorize_live_experiment,
        install_live_diagnostics,
    )

    b, v = broker()
    p = plan(op_env)
    v.allowed = False
    with pytest.raises(CapabilityAuthorizationError):
        authorize_live_experiment(op_env.runtime, p, broker=b, session_id="owner")
    assert op_env.governor.status().reserved_inr_minor == 0
    v.allowed = True
    auth = authorize_live_experiment(op_env.runtime, p, broker=b, session_id="owner")
    with pytest.raises(PaidBudgetDenied):
        install_live_diagnostics(
            op_env.runtime, p, authorization=replace(auth, nonce="forged")
        )
    assert install_live_diagnostics(op_env.runtime, p, authorization=auth).validate(
        auth
    )


def test_expired_or_replayed_diagnostic_cannot_spend(op_env):
    from jarvis.voice.gemini_live_diagnostics import authorize_live_experiment

    b, _ = broker()
    auth = authorize_live_experiment(
        op_env.runtime, plan(op_env), broker=b, session_id="owner"
    )
    control = op_env.runtime.live_diagnostics
    r = reserve(op_env)
    control.bind_parent(auth, r, op_env.price)
    with pytest.raises(PaidBudgetDenied):
        control.bind_parent(auth, r, op_env.price)
    op_env.runtime.clock = lambda: auth.expires_at_epoch + 1
    assert not control.validate(auth)


def test_diagnostic_counters_are_in_shared_parent_journal(op_env):
    from jarvis.voice.gemini_live_diagnostics import authorize_live_experiment

    from .test_governor import checkpoint

    b, _ = broker()
    auth = authorize_live_experiment(
        op_env.runtime, plan(op_env), broker=b, session_id="owner"
    )
    r = reserve(op_env)
    op_env.runtime.live_diagnostics.bind_parent(auth, r, op_env.price)
    checkpoint(op_env, r)
    with pytest.raises(PaidBudgetDenied):
        op_env.governor.checkpoint_operational_live(
            reservation_id=r.reservation_id,
            trigger_id="too-many",
            kind="initial",
            round_id="extra",
            tool_call_ids=(),
        )


def test_diagnostic_plan_rejects_unbounded_and_unsupported_faults(op_env):
    for changes in (
        {"max_seconds": 46},
        {"max_connections": True},
        {"faults": ("anything",)},
        {"scope": "qualification_capture", "max_generations": 2},
    ):
        with pytest.raises(ValueError):
            plan(op_env, **changes)
