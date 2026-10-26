import pytest

from jarvis.model_routing.budget import PaidBudgetDenied

from .admin_helpers import broker, unknown_complete


def test_synthetic_profile_never_becomes_production_qualification(op_env):
    from jarvis.model_routing.live_budget_admin import (
        LiveBudgetAdministration,
        resolve_qualified_live_profile,
    )

    _, e = unknown_complete(op_env)
    b, _ = broker()
    assert resolve_qualified_live_profile(op_env.runtime, policy=op_env.policy) is None
    with pytest.raises(PaidBudgetDenied):
        LiveBudgetAdministration(op_env.runtime, broker=b).qualify_profile(
            op_env.profile, evidence=e, session_id="owner"
        )
    assert op_env.runtime.config.enabled is True  # unchanged by qualification denial
    assert resolve_qualified_live_profile(op_env.runtime, policy=op_env.policy) is None


def test_profile_receipt_requires_audited_external_capture_boundary(
    op_env, monkeypatch
):
    from dataclasses import replace

    from jarvis.model_routing import live_budget_admin as module
    from jarvis.model_routing.live_policy import LiveUsageProfile
    from jarvis.model_routing.operational_budget import _evidence_binding

    op_env.price = replace(
        op_env.price, source="https://ai.google.dev/gemini-api/docs/pricing"
    )
    op_env.profile = LiveUsageProfile.from_payload(
        op_env.profile.to_payload()
        | {"source_refs": ["https://ai.google.dev/api/live#UsageMetadata"]}
    )
    _r, e = unknown_complete(op_env)
    b, _ = broker()

    def externally_verified_capture(runtime, c, evidence, profile):
        # Only this external provenance boundary is synthetic. Real authority,
        # event bindings, profile hashes, receipt persistence and resolver run.
        row, data, _, price, _ = _evidence_binding(runtime.paid_budget, c, evidence)
        module._profile_sources(profile, price)
        return row, data, price

    monkeypatch.setattr(module, "_validated_capture", externally_verified_capture)
    receipt = module.LiveBudgetAdministration(op_env.runtime, broker=b).qualify_profile(
        op_env.profile, evidence=e, session_id="owner"
    )
    assert receipt.startswith("live-profile-")
    result = module.resolve_qualified_live_profile(op_env.runtime, policy=op_env.policy)
    assert result.fingerprint == op_env.profile.fingerprint
    assert op_env.governor.status().reserved_inr_minor == 150
    assert op_env.governor.status().unknown_reservations == 1
