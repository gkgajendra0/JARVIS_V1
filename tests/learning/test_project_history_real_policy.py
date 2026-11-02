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
        context = wire.inputs[-1]["context"]
        assert isinstance(context, dict)
        assert any(
            source["role"] == "user"
            and source["text"] == "We will take the Jimny. The permit is pending."
            and source["thread_id"] == response.packet.selection.thread_id
            for source in context["sources"]
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


@pytest.mark.asyncio
async def test_production_policy_admits_session_reads_and_rejects_session_writes(
    learning, production_policy
):
    from jarvis.authority.personal_context_session import (
        PersonalContextSessionBinding,
    )
    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.memory.retrieval import SemanticRetrievalService
    from jarvis.voice.project_memory_lab import build_session_personal_factory

    await learning.service.admit_learning(learning.plan, learning.new_permit())
    capability = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=production_policy.broker,
    )
    memory = SimpleNamespace(retrieval=SemanticRetrievalService(learning.reader))
    factory, session = build_session_personal_factory(memory, capability)
    before = len(production_policy.hello.calls)
    try:
        for text in ("What vehicle do I have?", "Which car needs tyres?"):
            conversation = ConversationSession()
            conversation.start()
            conversation.accept_turn(ConversationRole.USER, text)
            personal = factory(conversation)
            try:
                result = await personal.query_for_question(
                    [{"scope_key": "owned_item.vehicle"}]
                )
            finally:
                personal.close()
            assert result["status"] == "selected"
            assert "City" in str(result["facts"])
        assert len(production_policy.hello.calls) == before + 1
        issuer = capability.personal_context_session_authority
        grant = await session.active_grant()
        with pytest.raises(PermissionError):
            issuer.issue_child(
                grant,
                PersonalContextSessionBinding(
                    "admit", "receipt", "0" * 64, ("owned_item",)
                ),
            )
    finally:
        session.close()


@pytest.mark.asyncio
async def test_production_policy_allows_labelled_other_project_fallback(
    tmp_path, production_policy
):
    from dataclasses import replace

    from test_project_conversation_store import event

    from jarvis.authority.conversation_history import HistoryActionBinding
    from jarvis.memory.project_conversation_store import archive_digest
    from jarvis.memory.project_conversations import ProjectSelection
    from jarvis.voice.project_memory_tools import ProjectMemoryTools

    _, store, selection, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, production_policy
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    foreign = ProjectSelection("project-interview", "thread-interview", 0)
    try:
        await access.create_project(foreign, "Interview preparation")
        value = replace(event("foreign", text="My salary expectation is fixed"))
        material = store.append_material(foreign, value, 0)
        issuer.register_source(grant, value.event_id, source=value)
        permit = issuer.issue_child(
            grant,
            HistoryActionBinding(
                "admit",
                value.event_id,
                archive_digest(material),
                targets=(
                    ("project", foreign.project_id),
                    ("thread", foreign.thread_id),
                ),
            ),
        )
        await store.append_event(foreign, value, permit=permit, expected_revision=0)
        issuer.release_source(grant, value.event_id)
        tools = ProjectMemoryTools(
            access, selection=selection, request_id="question", is_current=lambda: True
        )
        found = await tools.search_conversation_memory(selection.project_id, "salary")
        assert found.status == "other_projects"
        assert [s.project_title for s in found.sources] == ["Interview preparation"]
        read = await tools.read_conversation_sources(("foreign",))
        assert [s.event.event_id for s in read.sources] == ["foreign"]
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_production_policy_allows_owner_approved_quarantine_resolution(
    tmp_path, production_policy
):
    from test_project_upgrade_quarantine import open_lab, text_of

    for action in ("restore", "delete"):
        root = tmp_path / action
        root.mkdir()
        path, _, controls, _, _, writer, reader = await open_lab(
            root, production_policy
        )
        try:
            report = await controls.resolve_quarantine(action)
            assert report.count == 3
            assert (await controls.quarantine_report()).count == 0
            expected = (
                "[forgotten]"
                if action == "delete"
                else "Your interview topic is SQL window functions."
            )
            assert text_of(path, "n4") == expected
        finally:
            await reader.close()
            await writer.close()
