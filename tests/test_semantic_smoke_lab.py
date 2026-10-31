"""The voice smoke must never reuse a production memory/profile directory."""

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import load_machine_settings, save_machine_settings
from jarvis.voice.semantic_smoke_lab import prepare_smoke_profile, smoke_config


def test_profile_copy_contains_settings_but_never_memory(tmp_path):
    original = tmp_path / "production"
    original.mkdir()
    source = original / "machine.json"
    save_machine_settings({"JARVIS_AI_PROVIDER": "gemini"}, source)
    (original / "memory.db").write_bytes(b"production memory sentinel")
    before = source.read_bytes()
    lab = tmp_path / "isolated"
    profile = prepare_smoke_profile(source, lab, tool_paths={})
    assert load_machine_settings(profile)["JARVIS_AI_PROVIDER"] == "gemini"
    assert source.read_bytes() == before
    assert not (lab / "memory.db").exists()
    assert (original / "memory.db").read_bytes() == b"production memory sentinel"
    with pytest.raises(FileExistsError):
        prepare_smoke_profile(source, lab, tool_paths={})


def test_original_profile_directory_is_never_accepted(tmp_path):
    source = tmp_path / "machine.json"
    save_machine_settings({}, source)
    with pytest.raises(ValueError):
        prepare_smoke_profile(source, tmp_path, tool_paths={})


def test_lab_environment_redirects_state_and_restores_after_failure(
    tmp_path, monkeypatch
):
    import os

    from jarvis.machine_config import default_machine_config_path
    from jarvis.promotion.release import default_deployment_root, default_releases_root
    from jarvis.voice.semantic_smoke_lab import smoke_environment

    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", "original.json")
    monkeypatch.setenv("JARVIS_RUNTIME_ENV_OVERRIDES", "true")
    profile = tmp_path / "machine.json"
    with pytest.raises(RuntimeError, match="test exit"), smoke_environment(profile):
        assert default_machine_config_path() == profile
        assert default_deployment_root() == tmp_path / "deployment"
        assert default_releases_root() == tmp_path / "releases"
        assert os.environ["JARVIS_AUTHORITY_AUDIT_DB"] == str(
            tmp_path / "authority.sqlite3"
        )
        assert os.environ["JARVIS_RUNTIME_ENV_OVERRIDES"] == "false"
        raise RuntimeError("test exit")
    assert os.environ["JARVIS_MACHINE_CONFIG"] == "original.json"
    assert os.environ["JARVIS_RUNTIME_ENV_OVERRIDES"] == "true"


def test_smoke_disables_learning_and_background_work():
    config = smoke_config(
        JarvisConfig(
            ai_provider="gemini",
            vision_enabled=True,
            speaker_shadow_enabled=True,
            pocket3_native_tracking_enabled=True,
        )
    )
    assert config.personal_context_mode == "apply"
    assert config.personal_learning_mode == "off"
    assert config.memory_enabled
    assert not config.memory_candidate_extraction_enabled
    assert not config.work_orchestration_enabled
    assert not config.github_promotion_enabled
    assert not config.show_transcript
    assert config.gemini_fallback.enabled
    assert not config.vision_enabled
    assert not config.speaker_shadow_enabled
    assert not config.active_speaker_shadow_enabled
    assert not config.pocket3_native_tracking_enabled


def test_smoke_refuses_other_provider():
    with pytest.raises(ValueError, match="Gemini"):
        smoke_config(JarvisConfig(ai_provider="openai"))


@pytest.mark.parametrize("original, expected", [(3.0, 30.0), (45.0, 45.0)])
def test_lab_inactivity_window_outlasts_cloud_extraction(original, expected):
    config = smoke_config(
        JarvisConfig(
            ai_provider="gemini",
            follow_up_timeout_seconds=original,
            initial_request_timeout_seconds=original,
        )
    )
    assert config.follow_up_timeout_seconds == expected
    assert config.initial_request_timeout_seconds == expected


def test_launcher_main_loads_isolated_config_before_voice(tmp_path, monkeypatch):
    import os
    import sys
    from types import SimpleNamespace

    import jarvis.voice.semantic_smoke_lab as lab
    from jarvis import logging_config, preflight
    from jarvis.authority import tooling

    source = tmp_path / "production" / "machine.json"
    source.parent.mkdir()
    save_machine_settings({"JARVIS_AI_PROVIDER": "gemini"}, source)
    target = tmp_path / "isolated"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(source))
    monkeypatch.setattr(lab, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(
        sys, "argv", ["smoke", "--lab-root", str(target), "--model", "gemini-test"]
    )
    monkeypatch.setattr(tooling, "resolve_opa_binary", lambda **kwargs: source)
    monkeypatch.setattr(
        tooling, "resolve_windows_hello_helper", lambda **kwargs: source
    )
    monkeypatch.setattr(
        logging_config, "configure_logging", lambda *args, **kwargs: None
    )
    seen = []
    monkeypatch.setattr(
        preflight, "require_startup_preflight", lambda config: seen.append("preflight")
    )

    async def voice(config, *, model):
        assert seen == ["preflight"]
        assert config.ai_provider == "gemini"
        assert config.personal_learning_mode == "off"
        assert os.environ["JARVIS_MACHINE_CONFIG"] == str(target / "machine.json")
        assert model == "gemini-test"
        seen.append("voice")

    monkeypatch.setattr(lab, "run_smoke_runtime", voice)
    lab.main()
    assert seen == ["preflight", "voice"]
    assert os.environ["JARVIS_MACHINE_CONFIG"] == str(source)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_run", [False, True])
async def test_smoke_uses_owner_grant_and_revokes_on_exit(fail_run):
    from types import SimpleNamespace

    from jarvis.conversation import ConversationRole, ConversationSession
    from jarvis.voice.semantic_smoke_lab import run_smoke_runtime

    grant = SimpleNamespace(token="real-test-handle")
    events = []
    closed = set()

    async def close_memory():
        closed.add("memory")

    async def close_routing():
        closed.add("routing")

    class Capabilities:
        personal_learning_authority = SimpleNamespace(
            validate=lambda handle: SimpleNamespace(status="active"),
        )

        def open_personal_learning(self, runtime_id, provider):
            assert runtime_id.startswith("semantic-script-smoke-")
            assert provider == "gemini"
            events.append("approved")
            return grant

        def close_personal_learning(self, handle):
            assert handle is grant
            events.append("revoked")

        def close(self):
            closed.add("capabilities")

    class Runtime:
        _capability_runtime = Capabilities()
        _memory_runtime = SimpleNamespace(
            accepted_plan_epoch=lambda _: 0, close=close_memory
        )
        _routing_runtime = SimpleNamespace(
            router_for=lambda *args, **kwargs: None, aclose=close_routing
        )
        _research_service = None

        async def run(self):
            assert events == ["approved"]
            conversation = ConversationSession()
            conversation.start()
            components = self.factory(conversation)
            assert components.conversation is conversation
            source = conversation.accept_turn(ConversationRole.USER, "Unreviewed")
            # No provider call: unreviewed speech fails source admission first.
            from jarvis.memory.conversation_semantics import SemanticRejected

            with pytest.raises(SemanticRejected):
                await components.producer(source)
            events.append("voice")
            if fail_run:
                raise RuntimeError("voice failed")

    runtime = Runtime()

    def builder(config, *, semantic_session_factory):
        runtime.factory = semantic_session_factory
        return runtime

    if fail_run:
        with pytest.raises(RuntimeError, match="voice failed"):
            await run_smoke_runtime(
                smoke_config(JarvisConfig(ai_provider="gemini")),
                model="gemini-test",
                runtime_builder=builder,
            )
    else:
        await run_smoke_runtime(
            smoke_config(JarvisConfig(ai_provider="gemini")),
            model="gemini-test",
            runtime_builder=builder,
        )
    assert events == ["approved", "voice", "revoked"]
    if fail_run:
        assert closed == {"memory", "routing", "capabilities"}


@pytest.mark.asyncio
async def test_denied_hello_never_starts_voice_and_closes_constructed_resources():
    from types import SimpleNamespace

    from jarvis.voice.semantic_smoke_lab import run_smoke_runtime

    closed = set()

    def denied(*args):
        raise PermissionError("Hello denied")

    async def close_memory():
        closed.add("memory")

    async def close_routing():
        closed.add("routing")

    async def run():
        pytest.fail("Voice must not start after denied Hello")

    runtime = SimpleNamespace(
        _capability_runtime=SimpleNamespace(
            open_personal_learning=denied, close=lambda: closed.add("capabilities")
        ),
        _memory_runtime=SimpleNamespace(close=close_memory),
        _routing_runtime=SimpleNamespace(aclose=close_routing),
        _research_service=None,
        run=run,
    )
    with pytest.raises(PermissionError, match="Hello denied"):
        await run_smoke_runtime(
            JarvisConfig(ai_provider="gemini"),
            model="gemini-test",
            runtime_builder=lambda *args, **kwargs: runtime,
        )
    assert closed == {"memory", "routing", "capabilities"}


def test_only_marked_isolated_continuity_profile_can_be_reopened(tmp_path):
    from jarvis.voice.semantic_smoke_lab import resume_continuity_profile

    source = tmp_path / "production" / "machine.json"
    source.parent.mkdir()
    save_machine_settings({}, source)
    lab = tmp_path / "continuity"
    profile = prepare_smoke_profile(source, lab, tool_paths={})
    with pytest.raises(ValueError):
        resume_continuity_profile(source, lab)
    (lab / "topic-continuity.marker").write_text(
        "jarvis-topic-continuity-v1", encoding="utf-8"
    )
    assert resume_continuity_profile(source, lab) == profile
    with pytest.raises(ValueError):
        resume_continuity_profile(source, source.parent)


def test_resumed_profile_cannot_redirect_back_to_production(tmp_path):
    from jarvis.voice.semantic_smoke_lab import resume_continuity_profile

    source = tmp_path / "production" / "machine.json"
    source.parent.mkdir()
    save_machine_settings({}, source)
    lab = tmp_path / "continuity"
    lab.mkdir()
    (lab / "topic-continuity.marker").write_text(
        "jarvis-topic-continuity-v1", encoding="utf-8"
    )
    try:
        (lab / "machine.json").symlink_to(source)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        resume_continuity_profile(source, lab)


@pytest.mark.asyncio
async def test_continuity_mode_uses_canonical_store_without_extraction_model():
    from types import SimpleNamespace

    from jarvis.voice.semantic_smoke_lab import run_smoke_runtime

    grant = object()
    store = object()
    events = []
    authority = SimpleNamespace(validate=lambda _: SimpleNamespace(status="active"))

    class Runtime:
        _memory_runtime = SimpleNamespace(
            topic_checkpoints=store, accepted_plan_epoch=lambda _: 0
        )
        _capability_runtime = SimpleNamespace(
            personal_learning_authority=authority,
            open_personal_learning=lambda *args: grant,
            close_personal_learning=lambda handle: events.append("revoked"),
        )

        async def run(self):
            service = self.factory()
            assert service.store is store
            assert service.grant is grant
            assert service.authority is authority
            assert self.factory() is service
            events.append("voice")

    runtime = Runtime()

    def builder(config, *, topic_continuity_factory):
        runtime.factory = topic_continuity_factory
        return runtime

    await run_smoke_runtime(
        JarvisConfig(ai_provider="gemini"),
        model="",
        continuity=True,
        runtime_builder=builder,
    )
    assert events == ["voice", "revoked"]
