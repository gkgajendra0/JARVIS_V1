from __future__ import annotations

from types import SimpleNamespace

from jarvis.config import JarvisConfig
from jarvis.voice import production_runtime


class FakeBridge:
    def __init__(self) -> None:
        self.conversation = object()
        self.accepted_turn_observers = []
        self.close_observers = []

    def add_accepted_turn_observer(self, observer) -> None:
        self.accepted_turn_observers.append(observer)

    def add_close_observer(self, observer) -> None:
        self.close_observers.append(observer)


class FakeController:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class FakeContextShadowRuntime:
    def __init__(
        self,
        *,
        retrieval,
        embedding_store,
        query_encoder,
        reranker,
    ) -> None:
        self.retrieval = retrieval
        self.embedding_store = embedding_store
        self.query_encoder = query_encoder
        self.reranker = reranker

    def observe_turn(self, turn) -> None:
        del turn

    def close(self) -> None:
        return None


def test_production_context_shadow_uses_shared_models_and_session_local_runtime(
    monkeypatch,
) -> None:
    retrieval = object()
    embedding_store = object()
    memory_runtime = SimpleNamespace(
        retrieval=retrieval,
        embedding_store=embedding_store,
        service=object(),
    )
    encoder = object()
    reranker = object()
    created_bridges: list[FakeBridge] = []

    monkeypatch.setattr(
        production_runtime, "load_livekit_predictor", lambda path: object()
    )
    monkeypatch.setattr(
        production_runtime,
        "LiveKitWakeDetector",
        lambda predictor, **kwargs: object(),
    )
    monkeypatch.setattr(
        production_runtime,
        "MediaDevicesConversationRuntime",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        production_runtime,
        "build_default_memory_runtime",
        lambda: memory_runtime,
    )
    monkeypatch.setattr(
        production_runtime,
        "Qwen3EmbeddingEncoder",
        lambda: encoder,
    )
    monkeypatch.setattr(
        production_runtime,
        "Qwen3RetrievalReranker",
        lambda: reranker,
    )
    monkeypatch.setattr(
        production_runtime,
        "MemoryContextShadowRuntime",
        FakeContextShadowRuntime,
    )
    monkeypatch.setattr(
        production_runtime,
        "CanonicalActiveSpeakerRuntimeController",
        FakeController,
    )

    def create_session(config):
        del config
        bridge = FakeBridge()
        created_bridges.append(bridge)
        return object(), bridge

    monkeypatch.setattr(production_runtime, "create_voice_session", create_session)

    config = JarvisConfig(
        wake_model_path="jarvis.onnx",
        memory_enabled=True,
        memory_context_shadow_enabled=True,
    )
    controller = production_runtime.build_production_voice_runtime(config)
    session_factory = controller.kwargs["session_factory"]

    session_factory(config)
    session_factory(config)

    assert len(created_bridges) == 2
    shadows = []
    for bridge in created_bridges:
        assert len(bridge.accepted_turn_observers) == 1
        assert len(bridge.close_observers) == 1
        observe = bridge.accepted_turn_observers[0]
        close = bridge.close_observers[0]
        assert isinstance(observe.__self__, FakeContextShadowRuntime)
        assert close.__self__ is observe.__self__
        shadows.append(observe.__self__)

    assert shadows[0] is not shadows[1]
    assert shadows[0].retrieval is retrieval
    assert shadows[0].embedding_store is embedding_store
    assert shadows[0].query_encoder is encoder
    assert shadows[0].reranker is reranker
    assert shadows[1].query_encoder is encoder
    assert shadows[1].reranker is reranker
