from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from jarvis.chatgpt_plan import ChatGPTPlanUsageUnavailable
from jarvis.provider_circuit import BackgroundProviderCircuitRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "development_engine_owner_acceptance.py"


def _load_module():
    name = "jarvis_development_engine_owner_acceptance_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class _Plan:
    def __init__(self) -> None:
        self.list_model_calls = 0

    def is_connected(self) -> bool:
        return True

    def list_models(self):
        self.list_model_calls += 1
        return (SimpleNamespace(slug="gpt-test"),)


def test_owner_preflight_skips_model_catalog_while_subscription_cools_down(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    clock = _Clock()
    registry = BackgroundProviderCircuitRegistry(
        path=tmp_path / "circuits.json",
        clock=clock,
    )
    circuit = registry.circuit("chatgpt_plan:subscription")
    trip = circuit.record_failure(
        ChatGPTPlanUsageUnavailable(
            "Subscription Sharing usage limit reached.",
            status_code=429,
            code="subscription_sharing_usage_limit_exceeded",
            retryable=True,
        )
    )
    assert trip is not None
    plan = _Plan()

    monkeypatch.setattr(module, "ChatGPTPlanSessionManager", lambda: plan)
    monkeypatch.setattr(module, "BackgroundProviderCircuitRegistry", lambda: registry)
    monkeypatch.setattr(module, "_docker_available", lambda: True)
    monkeypatch.setattr(module, "_docker_image_available", lambda _image: True)
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: "git" if name == "git" else None,
    )
    monkeypatch.setitem(
        sys.modules,
        "openai_codex",
        SimpleNamespace(__version__=module.REVIEWED_CODEX_SDK_VERSION),
    )

    report = module._preflight(model="gpt-test", test_image="jarvis-tests:local")

    assert report["passed"] is False
    assert report["quota_consumed"] is False
    assert report["checks"]["chatgpt_plan_circuit_allows_request"] is False
    assert report["checks"]["development_model_visible"] is None
    assert plan.list_model_calls == 0
    state = report["chatgpt_plan_subscription_circuit"]
    assert state["key"] == "chatgpt_plan:subscription"
    assert state["failed_attempts"] == 1
    assert state["allows_request"] is False
    assert state["remaining_seconds"] == 1800.0


def test_owner_preflight_checks_model_after_subscription_cooldown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    clock = _Clock()
    registry = BackgroundProviderCircuitRegistry(
        path=tmp_path / "circuits.json",
        clock=clock,
    )
    circuit = registry.circuit("chatgpt_plan:subscription")
    circuit.record_failure(
        ChatGPTPlanUsageUnavailable(
            "Subscription Sharing usage limit reached.",
            status_code=429,
            code="subscription_sharing_usage_limit_exceeded",
            retryable=True,
        )
    )
    clock.value += 1800.0
    plan = _Plan()

    monkeypatch.setattr(module, "ChatGPTPlanSessionManager", lambda: plan)
    monkeypatch.setattr(module, "BackgroundProviderCircuitRegistry", lambda: registry)
    monkeypatch.setattr(module, "_docker_available", lambda: True)
    monkeypatch.setattr(module, "_docker_image_available", lambda _image: True)
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: "git" if name == "git" else None,
    )
    monkeypatch.setitem(
        sys.modules,
        "openai_codex",
        SimpleNamespace(__version__=module.REVIEWED_CODEX_SDK_VERSION),
    )

    report = module._preflight(model="gpt-test", test_image="jarvis-tests:local")

    assert report["passed"] is True
    assert report["quota_consumed"] is False
    assert report["checks"]["chatgpt_plan_circuit_allows_request"] is True
    assert report["checks"]["development_model_visible"] is True
    assert plan.list_model_calls == 1
    state = report["chatgpt_plan_subscription_circuit"]
    assert state["failed_attempts"] == 1
    assert state["allows_request"] is True
    assert state["remaining_seconds"] == 0.0


def test_owner_main_accepts_legacy_development_test_image_setting(
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    args = SimpleNamespace(
        model=None,
        test_image=None,
        output=None,
        preflight_only=True,
    )
    parser = SimpleNamespace(parse_args=lambda: args)
    observed: dict[str, str] = {}

    monkeypatch.setattr(module, "_parser", lambda: parser)
    monkeypatch.setattr(
        module,
        "load_machine_settings",
        lambda: {
            "JARVIS_DEVELOPMENT_ENGINE_MODEL": "gpt-reviewed",
            "JARVIS_DEV_TEST_DOCKER_IMAGE": "jarvis-dev-tests:local",
        },
    )
    monkeypatch.setattr(
        module,
        "configured_text",
        lambda name, settings: settings.get(name),
    )

    def _preflight(*, model: str, test_image: str):
        observed["model"] = model
        observed["test_image"] = test_image
        return {"passed": True}

    monkeypatch.setattr(module, "_preflight", _preflight)

    assert module.main() == 0
    assert observed == {
        "model": "gpt-reviewed",
        "test_image": "jarvis-dev-tests:local",
    }
    assert '"passed": true' in capsys.readouterr().out.casefold()


def test_owner_main_resolves_persisted_production_configuration(
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    args = SimpleNamespace(
        model=None,
        test_image=None,
        output=None,
        preflight_only=True,
    )
    parser = SimpleNamespace(parse_args=lambda: args)
    observed: dict[str, str] = {}

    monkeypatch.setattr(module, "_parser", lambda: parser)
    monkeypatch.setattr(
        module,
        "load_machine_settings",
        lambda: {
            "JARVIS_DEVELOPMENT_ENGINE_MODEL": "gpt-reviewed",
            "JARVIS_CHATGPT_PLAN_MODEL": "gpt-plan-fallback",
            "JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE": "jarvis-tests:local",
        },
    )
    monkeypatch.setattr(
        module,
        "configured_text",
        lambda name, settings: settings.get(name),
    )

    def _preflight(*, model: str, test_image: str):
        observed["model"] = model
        observed["test_image"] = test_image
        return {"passed": True}

    monkeypatch.setattr(module, "_preflight", _preflight)

    assert module.main() == 0
    assert observed == {
        "model": "gpt-reviewed",
        "test_image": "jarvis-tests:local",
    }
    assert '"passed": true' in capsys.readouterr().out.casefold()
