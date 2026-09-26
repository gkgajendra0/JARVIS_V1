from types import SimpleNamespace

import google.genai
import openai

from jarvis.hands.provider_adapters import build_structured_output_client
from jarvis.model_routing import invoker


def test_routed_client_factory_disables_provider_sdk_retries(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        provider_name = "gemini"
        model_name = "gemini-test"

    def fake_builder(**kwargs):
        calls.append(dict(kwargs))
        return FakeClient()

    monkeypatch.setattr(invoker, "build_structured_output_client", fake_builder)

    client = invoker._default_client_factory("gemini", "gemini-test")

    assert isinstance(client, FakeClient)
    assert calls == [
        {
            "provider": "gemini",
            "model": "gemini-test",
            "provider_retries": False,
        }
    ]


def test_structured_client_can_disable_openai_sdk_retries(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            responses=SimpleNamespace(parse=lambda **_: None),
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(openai, "AsyncOpenAI", fake_openai)

    client = build_structured_output_client(
        provider="openai",
        model="openai-test",
        provider_retries=False,
    )

    assert client.provider_name == "openai"
    assert captured["api_key"] == "test-openai-key"
    assert captured["max_retries"] == 0


def test_structured_client_can_disable_gemini_interactions_retries(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_gemini(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            aio=SimpleNamespace(
                interactions=SimpleNamespace(create=lambda **_: None),
            )
        )

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setattr(google.genai, "Client", fake_gemini)

    client = build_structured_output_client(
        provider="gemini",
        model="gemini-test",
        provider_retries=False,
    )

    assert client.provider_name == "gemini"
    assert captured["api_key"] == "test-google-key"
    assert captured["http_options"] == {
        "retry_options": {
            "attempts": 0,
        }
    }
