from __future__ import annotations

import json
import urllib.error

import pytest

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    OpaPolicyEngine,
    PolicyInput,
    RiskClass,
    TrustTier,
)


class Response:
    def __init__(self, payload: object) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def policy_input() -> PolicyInput:
    p = ActionProposal.create(
        session_id="s1",
        capability="test",
        operation="read",
        target={},
        parameters={},
        material_summary="read",
        attributes=ActionAttributes(),
        origin=ActionOrigin.DIRECT_USER,
        now_monotonic=100,
    )
    return PolicyInput(
        proposal=p,
        risk_class=RiskClass.ROUTINE,
        context=InteractionContext(
            session_id="s1",
            trust_tier=TrustTier.UNVERIFIED,
            attention_state=AttentionState.UNAVAILABLE,
        ),
        approval=None,
    )


def test_opa_requires_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OpaPolicyEngine(
            endpoint="http://192.0.2.10:8181/v1/data/jarvis/authority/decision"
        )


def test_opa_unavailable_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    decision = OpaPolicyEngine().evaluate(policy_input())
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("policy_unavailable_or_invalid",)


def test_opa_malformed_result_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: Response({"result": {"allow": "yes"}}),
    )
    decision = OpaPolicyEngine().evaluate(policy_input())
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("policy_malformed_result",)


def test_opa_policy_version_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "result": {
            "allow": True,
            "required_trust": 0,
            "approval_requirement": "none",
            "require_owner_attentive": False,
            "require_actor_unambiguous": False,
            "audit_required": False,
            "reason_codes": [],
            "policy_version": "unexpected",
        }
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: Response(payload),
    )
    decision = OpaPolicyEngine().evaluate(policy_input())
    assert decision.effect is AuthorityEffect.DENY
    assert decision.reason_codes == ("policy_version_mismatch",)


def test_opa_valid_result_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "result": {
            "allow": True,
            "required_trust": 0,
            "approval_requirement": "none",
            "require_owner_attentive": False,
            "require_actor_unambiguous": False,
            "audit_required": False,
            "reason_codes": [],
            "policy_version": "step3-v1",
        }
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: Response(payload),
    )
    decision = OpaPolicyEngine().evaluate(policy_input())
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.policy_version == "step3-v1"
