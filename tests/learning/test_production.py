import pytest

from jarvis.config import JarvisConfig
from jarvis.voice import production_runtime


def test_learning_apply_preserves_explicit_transcript_choice(monkeypatch):
    config = JarvisConfig(personal_learning_mode="apply", show_transcript=True)
    assert (
        config.personal_context_mode == "apply"
        and config.memory_enabled
        and config.show_transcript
    )
    monkeypatch.setenv("JARVIS_PERSONAL_LEARNING_MODE", "apply")
    assert JarvisConfig.from_environment().personal_learning_mode == "apply"
    with pytest.raises(ValueError):
        JarvisConfig(personal_learning_mode="shadow")


def test_cli_learning_override_and_explicit_conflict(monkeypatch):
    seen = []

    async def run(context=None, learning=None):
        seen.append((context, learning))

    monkeypatch.setattr(production_runtime, "_run_from_configuration", run)
    assert production_runtime.main(["--personal-learning", "apply"]) == 0
    assert seen == [(None, "apply")]
    with pytest.raises(SystemExit):
        production_runtime.main(
            ["--personal-learning", "apply", "--personal-context", "off"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reenable", [False, True])
@pytest.mark.parametrize("transcript", [False, True])
async def test_controller_opens_one_session_and_reuses_worker_on_fresh_wakes(
    learning, authority_parts, monkeypatch, reenable, transcript
):
    from types import SimpleNamespace

    import jarvis.memory.learning_extractors as adapters
    from jarvis.memory.learning_contracts import LearningBatch, LearningResolutionBatch
    from jarvis.memory.retrieval import SemanticRetrievalService
    from jarvis.memory.service import MemoryService
    from jarvis.voice.canonical_active_speaker_runtime import (
        CanonicalActiveSpeakerRuntimeController,
    )

    class Adapter:
        async def extract(self, source):
            return LearningBatch()

        async def resolve(self, *args):
            return LearningResolutionBatch()

        async def close(self):
            pass

    adapter = Adapter()

    def build(provider, *, diagnostics=False):
        assert diagnostics is transcript
        return adapter, adapter

    monkeypatch.setattr(adapters, "build_learning_adapters", build)
    capabilities = capability(authority_parts.broker)
    capabilities._authority = authority_parts.broker
    service = MemoryService(learning.lifecycle, learning.service.canonical_reader)
    memory = SimpleNamespace(
        service=service,
        retrieval=SemanticRetrievalService(learning.reader),
        bind_learning_authority=service.bind_learning_authority,
    )
    if reenable:
        await learning.writer.run(
            lambda c: (
                c.execute(
                    "INSERT INTO personal_learning_suppression VALUES ('owned_item.vehicle',1,1,'fictional')"
                ),
                c.commit(),
            )
        )
    config = JarvisConfig(
        personal_learning_mode="apply",
        show_transcript=transcript,
        personal_learning_reenable_categories=("owned_item.vehicle",)
        if reenable
        else (),
    )
    controller = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(),
        memory_runtime=memory,
        capability_runtime=capabilities,
        session_factory=lambda config: _session_pair(),
    )
    before = len(authority_parts.hello.calls)
    await controller._start_personal_learning()
    worker = controller._personal_learning
    assert worker.diagnostics is transcript
    assert worker.reconciler.diagnostics is transcript
    await controller._start_personal_learning()
    try:
        for _ in range(2):
            session, bridge = controller._session_factory(config)
            bridge.conversation.start()
            from livekit.agents.llm import ChatMessage

            session.emit(
                "conversation_item_added",
                SimpleNamespace(
                    item=ChatMessage(role="user", content=["I own a City"])
                ),
            )
            assert (
                controller._personal_context._learning_grant
                is controller._learning_grant
            )
            controller._personal_context.close()
        await worker.drain()
        assert worker.status().processed == 2
        assert controller._personal_learning is worker
        assert len(authority_parts.hello.calls) == before + 1 + int(reenable)
        assert not (await service.learning_suppression()).suppressed
    finally:
        await worker.close()
        capabilities.close_personal_learning(controller._learning_grant)


@pytest.mark.asyncio
async def test_controller_off_or_denial_never_auto_reopens(learning, authority_parts):
    from types import SimpleNamespace

    from jarvis.voice.canonical_active_speaker_runtime import (
        CanonicalActiveSpeakerRuntimeController,
    )

    capabilities = capability(authority_parts.broker)
    capabilities._authority = authority_parts.broker
    controller = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(), SimpleNamespace(), capability_runtime=capabilities
    )
    await controller._start_personal_learning()
    assert controller._personal_learning is None
    controller.config = JarvisConfig(personal_learning_mode="apply")
    controller._memory_runtime = SimpleNamespace(service=learning.service)
    authority_parts.hello.denied = True
    await controller._start_personal_learning()
    await controller._start_personal_learning()
    assert controller._personal_learning is None
    assert len(authority_parts.hello.calls) == 2


def capability(broker):
    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime

    return CapabilityRuntime(
        executors=(), resolver=CapabilityResolver((), builtins=()), authority=broker
    )


def _session_pair():
    from collections import defaultdict
    from types import SimpleNamespace

    from jarvis.conversation import ConversationSession
    from jarvis.memory.live_context import LiveContext
    from jarvis.voice.livekit_session import LiveKitConversationBridge

    handlers = defaultdict(list)
    session = SimpleNamespace(
        on=lambda event, callback: handlers[event].append(callback),
        emit=lambda event, value: [
            callback(value) for callback in tuple(handlers[event])
        ],
    )
    return session, LiveKitConversationBridge(
        session,
        ConversationSession(),
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )


def test_cli_reenable_is_exact_local_control(monkeypatch):
    seen = []

    async def run(context=None, learning=None, reenable=()):
        seen.append((context, learning, reenable))

    monkeypatch.setattr(production_runtime, "_run_from_configuration", run)
    assert (
        production_runtime.main(
            [
                "--personal-learning",
                "apply",
                "--reenable-learning-category",
                "owned_item.vehicle",
            ]
        )
        == 0
    )
    assert seen == [(None, "apply", ("owned_item.vehicle",))]
    with pytest.raises(SystemExit):
        production_runtime.main(
            [
                "--personal-learning",
                "off",
                "--reenable-learning-category",
                "owned_item.vehicle",
            ]
        )


def test_reenable_configuration_is_ephemeral_and_scoped():
    c = JarvisConfig(
        personal_learning_mode="apply",
        personal_learning_reenable_categories=("owned_item.vehicle",),
    )
    assert c.personal_learning_reenable_categories == ("owned_item.vehicle",)
    with pytest.raises(ValueError):
        JarvisConfig(
            personal_learning_mode="off",
            personal_learning_reenable_categories=("owned_item.vehicle",),
        )
    with pytest.raises(ValueError):
        JarvisConfig(
            personal_learning_mode="apply",
            personal_learning_reenable_categories=("home_city",),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["authorize", "memory_binding"])
async def test_learning_start_failure_logs_safe_phase_and_reason(
    authority_parts, monkeypatch, caplog, phase
):
    import logging
    from types import SimpleNamespace

    from jarvis.voice.canonical_active_speaker_runtime import (
        CanonicalActiveSpeakerRuntimeController,
    )

    capabilities = capability(authority_parts.broker)
    closed = []

    def fail():
        raise RuntimeError("PRIVATE-STARTUP-CANARY") from PermissionError(
            "strong owner verification was not granted: helper_timeout"
        )

    def open_grant(*_):
        if phase == "authorize":
            fail()
        return "synthetic-grant"

    def bind(*_):
        fail()

    monkeypatch.setattr(capabilities, "open_personal_learning", open_grant)
    monkeypatch.setattr(capabilities, "close_personal_learning", closed.append)
    controller = CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(), SimpleNamespace(), capability_runtime=capabilities
    )
    controller.config = JarvisConfig(personal_learning_mode="apply")
    controller._memory_runtime = SimpleNamespace(bind_learning_authority=bind)
    with caplog.at_level(logging.WARNING):
        await controller._start_personal_learning()
    assert f"phase={phase}" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "reason=helper_timeout" in caplog.text
    assert "PRIVATE-STARTUP-CANARY" not in caplog.text
    assert "strong owner verification" not in caplog.text
    assert controller._learning_grant is None
    assert closed == (["synthetic-grant"] if phase == "memory_binding" else [])
