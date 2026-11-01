import asyncio
import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.model_routing.invoker import RoutedInferenceFailure
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind
from jarvis.voice.project_contract_diagnostics import DevelopmentCaseFailure
from jarvis.voice.project_memory_lab import run_text_lab


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_failure", [True, False, "cancel"])
async def test_lab_preserves_primary_diagnosis_and_closes_remaining_resources(
    tmp_path, monkeypatch, primary_failure
):
    called, locks = [], []
    original_failure = RoutedInferenceFailure(
        ProviderFailure("gemini", ProviderFailureKind.RESPONSE_CONTRACT_INVALID)
    )
    cancellation = asyncio.CancelledError()

    class Memory:
        project_conversations = object()

        async def start(self):
            pass

        def bind_conversation_history_authority(self, authority):
            pass

        async def close(self):
            called.append("memory")
            raise OSError("PRIVATE_MEMORY_CLOSE")

    class Authority:
        def __init__(self, *args):
            pass

        def open(self, *args):
            return object()

        def close(self):
            called.append("authority")

    class Routing:
        async def aclose(self):
            called.append("routing")
            raise OSError("PRIVATE_SDK_CLOSE")

    class Coordinator:
        def invalidate(self, reason):
            called.append("coordinator")

        def diagnostics(self):
            return {"stage": "generating"}

    async def seed(*args):
        return {}

    async def question(*args):
        if primary_failure == "cancel":
            raise cancellation
        if primary_failure:
            raise original_failure
        return {"case_id": "p5-q5", "status": "completed"}

    @contextmanager
    def observe():
        yield [{"reason": "validation_failed"}]

    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lambda *args: None),
    )
    monkeypatch.setattr(
        "jarvis.memory.runtime.build_default_memory_runtime", lambda *args: Memory()
    )
    monkeypatch.setattr(
        "jarvis.authority.conversation_history.ConversationHistoryAuthority", Authority
    )
    monkeypatch.setattr(
        "jarvis.capabilities.authority_bridge.CapabilityAuthorityBroker",
        lambda: object(),
    )
    monkeypatch.setattr(
        "jarvis.capabilities.discovery.CapabilityResolver",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "jarvis.capabilities.runtime.CapabilityRuntime",
        lambda **kwargs: SimpleNamespace(close=lambda: called.append("capability")),
    )
    monkeypatch.setattr(
        "jarvis.memory.project_access.ProjectArchiveAccess",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "jarvis.work.store.SQLiteWorkStore", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        "jarvis.work.privacy.build_default_work_payload_codec", lambda *args: None
    )
    monkeypatch.setattr(
        "jarvis.model_routing.runtime.build_routing_runtime", lambda **kwargs: Routing()
    )
    monkeypatch.setattr(
        "jarvis.hands.provider_adapters.RoutedStructuredOutputClient",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        "jarvis.voice.project_answer_provider.ProjectAnswerProvider",
        lambda *args: object(),
    )
    monkeypatch.setattr(
        "jarvis.voice.project_conversation.ProjectConversationCoordinator",
        lambda *args, **kwargs: Coordinator(),
    )
    monkeypatch.setattr(
        "jarvis.voice.project_memory_development.seed_development_case", seed
    )
    monkeypatch.setattr(
        "jarvis.voice.project_memory_development.run_case_question", question
    )
    monkeypatch.setattr(
        "jarvis.voice.project_contract_diagnostics.observe_contract_failures", observe
    )
    from pathlib import Path

    original_open = Path.open

    def open_file(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path.name == "project-memory.lock":
            locks.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", open_file)
    expected_error = (
        asyncio.CancelledError
        if primary_failure == "cancel"
        else DevelopmentCaseFailure
    )
    with pytest.raises(expected_error) as caught:
        await run_text_lab(
            SimpleNamespace(gemini_fallback=GeminiFallbackConfig()),
            tmp_path,
            model="configured",
            development_case=object(),
        )
    assert called == ["coordinator", "authority", "capability", "routing", "memory"]
    assert locks[0].closed
    if primary_failure == "cancel":
        assert caught.value is cancellation
        return
    report = caught.value.report
    if primary_failure:
        assert report["error"] == "RoutedInferenceFailure"
        assert report["stage"] == "generating"
        assert report["routing_failure_kind"] == "response_contract_invalid"
    else:
        assert report["error"] == "OSError" and report["stage"] == "cleanup"
    assert report["contract_observations"] == [{"reason": "validation_failed"}]
    assert report["cleanup_errors"] == [
        {"component": "routing", "error": "OSError"},
        {"component": "memory", "error": "OSError"},
    ]
    assert "PRIVATE" not in json.dumps(report)
