import pytest

from jarvis.config import JarvisConfig
from jarvis.model_routing.invoker import build_default_model_adapter_registry
from jarvis.model_routing.router import build_default_work_targets


def test_disabled_legacy_digest():
    r = build_default_work_targets(
        configured_provider="gemini",
        configured_model="gemini-3.5-flash",
        adapter_registry=build_default_model_adapter_registry(),
    )
    assert (
        r.registry.digest()
        == "c200287907fdc1b68ad95c5ce4d3ba4b059a8372015885df14fcfd960af1d00c"
    )
    assert tuple(t.target_id for t in r.registry.all()) == (
        "work.gemini.default",
        "work.openai.default",
    )


def test_disabled_targets_never_offer_paid():
    from jarvis.model_routing.gemini import (
        GeminiFallbackConfig,
        build_gemini_role_targets,
    )

    targets = build_gemini_role_targets(
        role="hands",
        model="gemini-test",
        adapter_id="gemini",
        config=GeminiFallbackConfig(),
    )
    assert len(targets) == 1
    assert targets[0].credential_ref == "GOOGLE_API_KEY"


def test_enabled_targets_are_independent_and_same_model():
    from jarvis.model_routing.gemini import (
        GeminiFallbackConfig,
        build_gemini_role_targets,
    )

    free, paid = build_gemini_role_targets(
        role="memory.extraction",
        model="gemini-test",
        adapter_id="gemini",
        config=GeminiFallbackConfig(enabled=True),
    )
    assert free.target_id != paid.target_id
    assert free.model_id == paid.model_id == "gemini-test"
    assert free.credential_ref == "GOOGLE_API_KEY"
    assert paid.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
    assert free.cost_profile is None and paid.cost_profile is None


def test_live_target_preserves_streaming_and_tools():
    from jarvis.model_routing.gemini import (
        GeminiFallbackConfig,
        build_gemini_role_targets,
    )

    free, paid = build_gemini_role_targets(
        role="voice.live",
        model="gemini-test-live",
        adapter_id="gemini.live",
        config=GeminiFallbackConfig(enabled=True),
    )
    assert all(t.supports_streaming and t.supports_tools for t in (free, paid))
    assert all("realtime_voice" in t.capabilities for t in (free, paid))


@pytest.mark.parametrize(
    "values",
    [
        {"ceiling_inr_minor": True},
        {"ceiling_inr_minor": 0},
        {"ceiling_inr_minor": -1},
        {"ceiling_inr_minor": 350.0},
        {"cooldown_seconds": 0},
        {"max_cooldown_seconds": 30},
        {"enabled": "yes"},
        {"budget_id": ""},
    ],
)
def test_invalid_cap_and_config_rejected(values):
    from jarvis.model_routing.gemini import GeminiFallbackConfig

    with pytest.raises((TypeError, ValueError)):
        GeminiFallbackConfig(**values)


def test_machine_config_precedence(monkeypatch):
    monkeypatch.setenv("JARVIS_GEMINI_PAID_FALLBACK_ENABLED", "true")
    monkeypatch.setattr(
        "jarvis.config.load_machine_settings",
        lambda: {
            "JARVIS_GEMINI_PAID_FALLBACK_ENABLED": "false",
            "JARVIS_GEMINI_PAID_CEILING_INR_MINOR": "12345",
        },
    )
    cfg = JarvisConfig.from_environment()
    assert cfg.gemini_fallback.enabled is False
    assert cfg.gemini_fallback.ceiling_inr_minor == 12345
    monkeypatch.setenv("JARVIS_RUNTIME_ENV_OVERRIDES", "true")
    assert JarvisConfig.from_environment().gemini_fallback.enabled is True


def test_default_config_never_enables_paid():
    assert JarvisConfig().gemini_fallback.enabled is False
    assert JarvisConfig().gemini_fallback.ceiling_inr_minor == 35000
