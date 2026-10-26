from types import SimpleNamespace

import pytest
from tests.gemini_fallback.test_hands_memory import shared

from jarvis.config import JarvisConfig
from jarvis.model_routing.gemini import GeminiFallbackConfig


def test_disabled_production_routing_is_lazy(monkeypatch):
    from jarvis.model_routing.runtime import build_production_routing_runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled mode opened protected storage")

    monkeypatch.setattr("jarvis.work.store.SQLiteWorkStore", forbidden)
    assert build_production_routing_runtime(JarvisConfig()) is None
    assert (
        build_production_routing_runtime(
            JarvisConfig(
                ai_provider="openai", gemini_fallback=GeminiFallbackConfig(enabled=True)
            )
        )
        is None
    )


def test_work_disabled_routing_uses_existing_protected_store_without_starting_dbos(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.runtime import build_production_routing_runtime
    from jarvis.work.store import SQLiteWorkStore

    codec_calls = []
    monkeypatch.setattr(
        "jarvis.work.privacy.build_default_work_payload_codec",
        lambda path: codec_calls.append(path),
    )
    monkeypatch.setattr(
        "jarvis.work.runtime.initialize_dbos_work_runtime",
        lambda **_: pytest.fail("DBOS started"),
    )
    config = JarvisConfig(
        ai_provider="gemini", gemini_fallback=GeminiFallbackConfig(enabled=True)
    )
    runtime = build_production_routing_runtime(
        config, store_path=tmp_path / "routing.db"
    )
    assert isinstance(runtime.work_store, SQLiteWorkStore)
    assert codec_calls == [tmp_path / "routing.db"]
    with runtime.work_store.extension_transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
    assert runtime.paid_budget.status().ceiling_inr_minor == 35000


def production_harness(tmp_path, monkeypatch, *, enabled, work, memory=False):
    from tests.test_production_hands_voice_wiring import NoopAuthority

    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.hands.planner import build_hands_planner
    from jarvis.voice import production_runtime as production

    runtime, _ = shared(tmp_path, monkeypatch, {})
    capture = {}
    from jarvis.memory.retrieval import SemanticRetrievalService

    monkeypatch.setattr(
        production,
        "build_default_memory_runtime",
        lambda: SimpleNamespace(retrieval=SemanticRetrievalService(None)),
    )
    original_candidate_factory = production.build_memory_candidate_extractor

    def candidate(**kwargs):
        result = original_candidate_factory(**kwargs)
        capture["candidate"] = result
        return result

    monkeypatch.setattr(production, "build_memory_candidate_extractor", candidate)
    monkeypatch.setattr(production, "load_livekit_predictor", lambda _: object())
    monkeypatch.setattr(production, "LiveKitWakeDetector", lambda *a, **kw: object())
    monkeypatch.setattr(
        production,
        "MediaDevicesConversationRuntime",
        lambda *a, **kw: SimpleNamespace(output=None),
    )
    monkeypatch.setattr(production, "load_active_release_for_startup", lambda: None)
    monkeypatch.setattr(
        production,
        "build_current_research_service",
        lambda: SimpleNamespace(provider_name="fictional"),
    )
    monkeypatch.setattr(production, "build_local_status_speech", lambda: None)
    monkeypatch.setattr(
        production,
        "build_production_routing_runtime",
        lambda config: capture.setdefault("routing", runtime),
    )

    def capabilities(**kwargs):
        capture["capabilities"] = kwargs
        planner_kwargs = {
            k: kwargs[k]
            for k in (
                "hands_planner_model",
                "chatgpt_plan_enabled",
                "chatgpt_plan_model",
            )
        }
        planner_kwargs["model"] = planner_kwargs.pop("hands_planner_model")
        planner = build_hands_planner(
            provider="gemini",
            routing_runtime=kwargs.get("routing_runtime"),
            **planner_kwargs,
        )
        return CapabilityRuntime(
            executors=(),
            resolver=CapabilityResolver((), builtins=()),
            authority=NoopAuthority(),
            hands_planner=planner,
        )

    def build_work(**kwargs):
        capture["work"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(production, "build_default_capability_runtime", capabilities)
    monkeypatch.setattr(production, "build_work_runtime", build_work)
    config = JarvisConfig(
        ai_provider="gemini",
        wake_model_path="fictional.onnx",
        vision_enabled=False,
        speaker_shadow_enabled=False,
        active_speaker_shadow_enabled=False,
        pocket3_native_tracking_enabled=False,
        memory_enabled=memory,
        memory_semantic_recall_model="gemini-budget-test" if memory else None,
        memory_candidate_extraction_enabled=memory,
        memory_candidate_extraction_model="gemini-budget-test" if memory else None,
        work_orchestration_enabled=work,
        work_dbos_database_url="postgresql://fictional.invalid/jarvis"
        if work
        else None,
        gemini_fallback=GeminiFallbackConfig(enabled=enabled),
    )
    controller = production.build_production_voice_runtime(config)
    return controller, runtime, capture


@pytest.mark.asyncio
@pytest.mark.parametrize("work", [False, True])
async def test_full_production_factory_shares_routing_with_hands_work_and_controller(
    tmp_path, monkeypatch, work
):
    controller, runtime, capture = production_harness(
        tmp_path, monkeypatch, enabled=True, work=work
    )
    assert controller._routing_runtime is runtime
    assert capture["capabilities"]["routing_runtime"] is runtime
    if work:
        assert capture["work"]["routing_runtime"] is runtime
    else:
        assert "work" not in capture
    # The planner calls the existing router and uses its exact store/governor.
    assert controller._capability_runtime.hands_planner._client.runtime is runtime


def test_disabled_factory_does_not_build_new_runtime(tmp_path, monkeypatch):
    controller, _, capture = production_harness(
        tmp_path, monkeypatch, enabled=False, work=False
    )
    assert "routing" not in capture
    assert controller._routing_runtime is None
    assert "routing_runtime" not in capture["capabilities"]


@pytest.mark.asyncio
async def test_routing_owner_closes_each_cached_provider_client_once(
    tmp_path, monkeypatch
):
    runtime, _ = shared(tmp_path, monkeypatch, {})
    closed = []

    class Client:
        async def aclose(self):
            closed.append("closed")

    adapter = runtime.router.adapter_registry.require("gemini")
    client = Client()
    adapter._clients["one"] = client
    adapter._clients["two"] = client
    await runtime.aclose()
    await runtime.aclose()
    assert closed == ["closed"]


def test_real_capability_factory_passes_shared_runtime_to_hands(tmp_path, monkeypatch):
    from tests.test_production_hands_voice_wiring import NoopAuthority

    import jarvis.capabilities.runtime as capabilities

    runtime, _ = shared(tmp_path, monkeypatch, {})
    monkeypatch.setattr(capabilities, "CapabilityAuthorityBroker", NoopAuthority)
    built = capabilities.build_default_capability_runtime(
        ai_provider="gemini",
        hands_planner_model="gemini-budget-test",
        routing_runtime=runtime,
    )
    try:
        assert built.hands_planner._client.runtime is runtime
    finally:
        built.close()


@pytest.mark.asyncio
async def test_runtime_cleanup_attempts_every_client_even_if_one_close_fails(
    tmp_path, monkeypatch
):
    runtime, _ = shared(tmp_path, monkeypatch, {})
    closed = []

    class Client:
        def __init__(self, fail):
            self.fail = fail

        async def aclose(self):
            closed.append(self.fail)
            if self.fail:
                raise RuntimeError("private-canary-provider-body")

    adapter = runtime.router.adapter_registry.require("gemini")
    adapter._clients["bad"] = Client(True)
    adapter._clients["good"] = Client(False)
    await runtime.aclose()
    assert closed == [True, False]


def test_full_production_factory_shares_runtime_with_recall_verifier_and_candidate(
    tmp_path, monkeypatch
):
    controller, runtime, capture = production_harness(
        tmp_path, monkeypatch, enabled=True, work=False, memory=True
    )
    coordinator = controller._memory_query_coordinator
    assert coordinator._coordinator._interpreter._client.runtime is runtime
    assert coordinator._release_guard._client.runtime is runtime
    assert capture["candidate"]._client.runtime is runtime
