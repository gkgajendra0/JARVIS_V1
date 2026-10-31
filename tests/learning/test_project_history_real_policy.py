"""Production Rego + authority/store integration; only OS/Hello/cloud are fake."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_project_conversation_store import setup_store

from jarvis.authority.local_opa import ManagedOpaServer
from jarvis.authority.policy import OpaPolicyEngine
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator


@pytest.fixture
def production_policy(authority_parts, monkeypatch):
    binary = os.environ.get("JARVIS_TEST_OPA_BINARY") or shutil.which("opa")
    if not binary:
        if os.environ.get("JARVIS_REQUIRE_REAL_OPA") == "1":
            pytest.fail(
                "Required real OPA binary unavailable; cannot substitute the permissive fixture policy"
            )
        pytest.skip("real OPA not provisioned; mandatory in the Linux policy CI step")
    monkeypatch.setenv("JARVIS_OPA_PATH", str(Path(binary).resolve()))
    with ManagedOpaServer(
        policy_path=Path(__file__).resolve().parents[2]
        / "policies/step3_authority.rego"
    ) as server:
        authority_parts.broker._authority._policy_engine = OpaPolicyEngine(
            endpoint=server.endpoint
        )
        yield authority_parts


@pytest.mark.asyncio
async def test_production_policy_allows_authorized_project_routing_recording_and_recall(
    tmp_path, production_policy
):
    _, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, production_policy
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)

    class CloudBoundary:
        def __init__(self):
            self.inputs = []

        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            self.inputs.append(kwargs["input_payload"])
            return SimpleNamespace(
                parsed=kwargs["response_model"](
                    response={"answer": "Project context received."}
                ),
                usage={},
                usage_observed=False,
                latency_ms=0,
            )

    wire = CloudBoundary()
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    conversation = ConversationSession()
    conversation.start()
    try:
        for text in (
            "Let's plan my Nepal trip",
            "We will take the Jimny. The permit is pending.",
            "What is the status of my Nepal trip?",
        ):
            turn = conversation.accept_turn(ConversationRole.USER, text)
            response = await coordinator.respond(
                conversation,
                turn,
                provider=ProjectAnswerProvider(wire),
                authorize=access.current,
            )
            await coordinator.record_assistant(
                conversation, response, delivered_text=response.answer
            )
        assert (
            "Jimny" in wire.inputs[-1]["context"]
            and "permit is pending" in wire.inputs[-1]["context"]
        )
        assert len(production_policy.hello.calls) == 1
        issuer.revoke(grant)
        with pytest.raises(PermissionError):
            await access.catalog()
    finally:
        coordinator.invalidate("test_done")
        await reader.close()
        await writer.close()


@pytest.mark.parametrize(
    "operation,risk",
    [
        ("read", "PRIVATE_READ"),
        ("admit", "PERSISTENT_OR_EXTERNAL"),
        ("suppress", "PERSISTENT_OR_EXTERNAL"),
    ],
)
def test_real_history_policy_requires_registered_delegation_fields(
    production_policy, operation, risk
):
    import json
    import urllib.request

    engine = production_policy.broker._authority._policy_engine
    payload = {
        "proposal": {
            "capability": "memory:conversation_history",
            "operation": operation,
            "origin": "system",
        },
        "risk_class": risk,
        "approval": {
            "method": "delegated_policy",
            "parent_delegation_id": "registered-parent",
        },
    }

    def evaluate(value):
        request = urllib.request.Request(
            engine._endpoint,
            data=json.dumps({"input": value}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read())["result"]

    allowed = evaluate(payload)
    assert (
        allowed["allow"]
        and not allowed["require_owner_attentive"]
        and not allowed["require_actor_unambiguous"]
    )
    assert allowed["audit_required"] and allowed["approval_requirement"] == "explicit"
    for invalid_parent in ("", None, 123):
        denied = evaluate(
            {
                **payload,
                "approval": {
                    "method": "delegated_policy",
                    "parent_delegation_id": invalid_parent,
                },
            }
        )
        assert denied["allow"] is False
    denied = evaluate({**payload, "approval": {"method": "delegated_policy"}})
    assert denied["allow"] is False
    denied = evaluate(
        {**payload, "proposal": {**payload["proposal"], "origin": "direct_user"}}
    )
    assert denied["allow"] is False
    critical = evaluate({**payload, "risk_class": "CRITICAL"})
    assert critical["approval_requirement"] == "strong"
    denied = evaluate({**payload, "approval": None})
    assert denied["allow"] is False
    denied = evaluate(
        {
            **payload,
            "approval": {
                "method": "spoken",
                "parent_delegation_id": "registered-parent",
            },
        }
    )
    assert denied["allow"] is False


def test_unrelated_system_private_read_keeps_attention_and_actor_requirements(
    production_policy,
):
    import json
    import urllib.request

    engine = production_policy.broker._authority._policy_engine
    payload = {
        "proposal": {
            "capability": "files:private",
            "operation": "read",
            "origin": "system",
        },
        "risk_class": "PRIVATE_READ",
        "approval": {"method": "delegated_policy", "parent_delegation_id": "anything"},
    }
    request = urllib.request.Request(
        engine._endpoint,
        data=json.dumps({"input": payload}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        decision = json.loads(response.read())["result"]
    assert decision["require_owner_attentive"] and decision["require_actor_unambiguous"]
