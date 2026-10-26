from dataclasses import FrozenInstanceError, replace

import pytest

from .helpers import policy, profile


def test_default_controls_and_hash_are_exact():
    from jarvis.voice.gemini_live_controls import LiveTransportControls

    p = policy()
    c = LiveTransportControls.from_operational(p)
    assert (p.allowance_minor, p.soft_stop_minor) == (1000, 800)
    assert (c.max_physical_seconds, c.max_activity_seconds) == (45, 20)
    assert (c.output_token_limit, c.max_tool_continuations) == (1024, 2)
    assert c.dispatch_seconds == 42
    assert replace(p, provenance="other").fingerprint != p.fingerprint
    with pytest.raises(FrozenInstanceError):
        p.allowance_minor = 500


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"allowance_minor": True},
        {"soft_stop_minor": 1000},
        {"model_id": "models/gemini-3.8-live"},
        {"max_physical_seconds": float("nan")},
        {"max_activity_seconds": 46},
        {"provenance": ""},
        {"output_token_limit": -1},
        {"allowance_minor": 2000},
        {"setup_timeout_seconds": 50},
    ],
)
def test_policy_rejects_unreviewed_or_malformed_controls(changes):
    with pytest.raises(ValueError):
        replace(policy(), **changes)


def test_synthetic_profile_cannot_claim_production_qualification():
    from jarvis.model_routing.live_policy import LiveUsageProfile

    p = profile()
    assert not hasattr(p, "qualified")
    assert LiveUsageProfile.from_payload(p.to_payload()).fingerprint == p.fingerprint
    payload = p.to_payload() | {"qualified": True}
    with pytest.raises(ValueError):
        LiveUsageProfile.from_payload(payload)
    with pytest.raises(TypeError):
        p.field_map["input_tokens"] = "forged"


@pytest.mark.parametrize(
    "changes",
    [
        {"counter_scope": "guess"},
        {"field_map": {}},
        {"transcription_mode": "unknown"},
        {"evidence_digest": "fake"},
        {"sdk_versions": {}},
        {"terminal_mode": "any"},
        {"zero_rules": {"thoughts_token_count": "just assume"}},
    ],
)
def test_profile_rejects_ambiguous_accounting(changes):
    with pytest.raises(ValueError):
        profile(**changes)
