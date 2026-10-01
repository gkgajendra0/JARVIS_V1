from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import jarvis.chatgpt_plan as chatgpt_plan_module
from jarvis.chatgpt_plan import (
    CHATGPT_PLAN_REQUIRED_SCOPE,
    CHATGPT_PLAN_TARGET_ID,
    ChatGPTPlanCredentials,
    ChatGPTPlanHTTPError,
    ChatGPTPlanResponse,
    ChatGPTPlanSessionManager,
    ChatGPTPlanUsageUnavailable,
    _strict_json_schema,
    load_or_create_chatgpt_plan_host_id,
)
from jarvis.config import JarvisConfig
from jarvis.hands import planner as hands_planner_module
from jarvis.hands.contracts import build_action_response_model
from jarvis.hands.provider_adapters import (
    ChatGPTPlanStructuredOutputClient,
    FallbackStructuredOutputClient,
    StructuredOutputTelemetry,
)
from jarvis.machine_config import load_machine_settings, save_machine_settings
from jarvis.model_routing.models import ModelLocality
from jarvis.model_routing.registry import ModelAdapterRegistry
from jarvis.model_routing.router import build_default_work_targets
from jarvis.provider_resilience import ProviderFailureKind, classify_provider_failure


class _DummyAdapter:
    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id

    async def invoke_structured(self, **kwargs: object) -> object:
        return kwargs


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    message: str


def _credentials() -> ChatGPTPlanCredentials:
    return ChatGPTPlanCredentials(
        email="owner@example.com",
        issuer="https://auth.openai.com",
        subject="subject-1",
        client_id="oaiapp_test",
        ext_agent_host_id="urn:uuid:00000000-0000-0000-0000-000000000001",
        id_token="id-token",
        access_token="access-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_in=3600,
        scopes=(
            "openid",
            "profile",
            "email",
            "offline_access",
            "resource.invoke",
            CHATGPT_PLAN_REQUIRED_SCOPE,
        ),
        saved_at_epoch=100.0,
        earliest_refresh_at_epoch=200.0,
    )


def test_chatgpt_plan_credentials_round_trip_without_losing_scope() -> None:
    restored = ChatGPTPlanCredentials.from_bytes(_credentials().to_bytes())

    assert restored == _credentials()
    assert restored.plan_usage_enabled is True
    assert restored.access_expires_at_epoch == 3700.0


def test_chatgpt_plan_host_id_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "host.json"

    first = load_or_create_chatgpt_plan_host_id(path)
    second = load_or_create_chatgpt_plan_host_id(path)

    assert first == second
    assert first.startswith("urn:uuid:")
    assert "access_token" not in path.read_text(encoding="utf-8")


class _FakePlanManager:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def invoke_structured(self, **kwargs: object) -> ChatGPTPlanResponse:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return ChatGPTPlanResponse(
            output_text='{"ok":true,"message":"plan"}',
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            usage_observed=True,
        )


class _FallbackClient:
    provider_name = "gemini"
    model_name = "gemini-fallback"

    def __init__(self) -> None:
        self.calls = 0

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
    ) -> BaseModel:
        return (
            await self.parse_with_telemetry(
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
            )
        ).parsed

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry:
        del system_prompt, input_payload
        self.calls += 1
        return StructuredOutputTelemetry(
            parsed=response_model(ok=True, message="fallback"),
            usage={"input_tokens": 1},
            usage_observed=True,
            latency_ms=1.0,
        )


@pytest.mark.asyncio
async def test_chatgpt_plan_structured_client_uses_plan_transport() -> None:
    manager = _FakePlanManager()
    client = ChatGPTPlanStructuredOutputClient(
        session_manager=manager,  # type: ignore[arg-type]
        model="plan-model",
    )

    result = await client.parse_with_telemetry(
        system_prompt="system",
        input_payload={"task": "test"},
        response_model=_Result,
    )

    assert result.parsed == _Result(ok=True, message="plan")
    assert result.usage["total_tokens"] == 15
    assert manager.calls[0]["model"] == "plan-model"
    assert manager.calls[0]["instructions"] == "system"


@pytest.mark.asyncio
async def test_chatgpt_plan_client_falls_back_when_plan_allowance_is_unavailable() -> (
    None
):
    manager = _FakePlanManager(
        error=ChatGPTPlanUsageUnavailable(
            "limit",
            status_code=429,
            code="subscription_sharing_usage_limit_exceeded",
            retryable=True,
        )
    )
    primary = ChatGPTPlanStructuredOutputClient(
        session_manager=manager,  # type: ignore[arg-type]
        model="plan-model",
    )
    fallback = _FallbackClient()
    client = FallbackStructuredOutputClient(
        primary=primary,
        fallback=fallback,
    )

    result = await client.parse_with_telemetry(
        system_prompt="system",
        input_payload={"task": "test"},
        response_model=_Result,
    )

    assert result.parsed == _Result(ok=True, message="fallback")
    assert fallback.calls == 1


def test_chatgpt_plan_stream_error_maps_subscription_limit_to_usage_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CredentialStore:
        def load(self):
            return _credentials()

        def save(self, credentials) -> None:
            del credentials

    class _StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def __iter__(self):
            event = {
                "type": "error",
                "error": {
                    "code": "subscription_sharing_usage_limit_exceeded",
                    "message": (
                        "The ChatGPT user has reached their Subscription Sharing "
                        "usage limit. Ask the user to try again after their usage "
                        "limit resets or use an API key instead."
                    ),
                },
            }
            yield f"data: {json.dumps(event)}\n".encode()

    monkeypatch.setattr(
        chatgpt_plan_module.request,
        "urlopen",
        lambda request, timeout: _StreamResponse(),
    )
    manager = ChatGPTPlanSessionManager(
        credential_store=_CredentialStore(),  # type: ignore[arg-type]
        clock=lambda: 100.0,
    )

    with pytest.raises(ChatGPTPlanUsageUnavailable) as captured:
        manager.invoke_structured(
            model="plan-model",
            instructions="system",
            input_payload={"task": "test"},
            schema_name="result",
            schema={"type": "object", "properties": {}},
            timeout_seconds=1.0,
        )

    assert captured.value.status_code == 429
    assert captured.value.code == "subscription_sharing_usage_limit_exceeded"
    assert captured.value.retryable is True


def test_raw_chatgpt_plan_subscription_limit_is_provider_pressure() -> None:
    failure = classify_provider_failure(
        ChatGPTPlanHTTPError(
            (
                "The ChatGPT user has reached their Subscription Sharing usage "
                "limit. Ask the user to try again after their usage limit resets "
                "or use an API key instead."
            ),
            code="subscription_sharing_usage_limit_exceeded",
        ),
        provider="chatgpt_plan",
    )

    assert failure.kind is ProviderFailureKind.RATE_LIMITED


def test_chatgpt_plan_usage_error_maps_to_rate_limit_for_work_fallback() -> None:
    failure = classify_provider_failure(
        ChatGPTPlanUsageUnavailable(
            "limit",
            status_code=429,
            code="subscription_sharing_usage_limit_exceeded",
            retryable=True,
        ),
        provider="chatgpt_plan",
    )

    assert failure.kind is ProviderFailureKind.RATE_LIMITED
    assert failure.retryable is True


def test_plan_enabled_work_pool_is_plan_primary_plus_configured_paid_fallback() -> None:
    adapters = ModelAdapterRegistry(
        (
            _DummyAdapter("chatgpt_plan"),
            _DummyAdapter("gemini"),
            _DummyAdapter("openai"),
        )
    )

    targets = build_default_work_targets(
        configured_provider="gemini",
        configured_model=None,
        adapter_registry=adapters,
        chatgpt_plan_enabled=True,
        chatgpt_plan_model="plan-model",
    )

    all_targets = targets.registry.all()
    assert targets.primary_target_id == CHATGPT_PLAN_TARGET_ID
    assert tuple(target.target_id for target in all_targets) == (
        CHATGPT_PLAN_TARGET_ID,
        "work.gemini.default",
    )
    plan = targets.registry.require(CHATGPT_PLAN_TARGET_ID)
    assert plan.locality is ModelLocality.CLOUD
    assert plan.cost_profile is not None
    assert plan.cost_profile.input_usd_per_million_tokens == 0.0
    assert plan.cost_profile.output_usd_per_million_tokens == 0.0


def test_legacy_work_pool_is_unchanged_when_plan_is_disabled() -> None:
    adapters = ModelAdapterRegistry(
        (
            _DummyAdapter("gemini"),
            _DummyAdapter("openai"),
        )
    )

    targets = build_default_work_targets(
        configured_provider="openai",
        configured_model=None,
        adapter_registry=adapters,
    )

    assert targets.primary_target_id == "work.openai.default"
    assert tuple(target.target_id for target in targets.registry.all()) == (
        "work.gemini.default",
        "work.openai.default",
    )


def test_chatgpt_plan_config_requires_model_when_enabled() -> None:
    with pytest.raises(ValueError, match="CHATGPT_PLAN_MODEL"):
        JarvisConfig(chatgpt_plan_enabled=True)

    config = JarvisConfig(
        chatgpt_plan_enabled=True,
        chatgpt_plan_model=" plan-model ",
    )
    assert config.chatgpt_plan_enabled is True
    assert config.chatgpt_plan_model == "plan-model"


def test_chatgpt_plan_machine_settings_are_persistable_without_credentials(
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_CHATGPT_PLAN_ENABLED": "true",
            "JARVIS_CHATGPT_PLAN_MODEL": "plan-model",
        },
        path,
    )

    settings = load_machine_settings(path)
    assert settings["JARVIS_CHATGPT_PLAN_ENABLED"] == "true"
    assert settings["JARVIS_CHATGPT_PLAN_MODEL"] == "plan-model"
    assert all("TOKEN" not in key and "SECRET" not in key for key in settings)


def _schema_nodes(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _schema_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _schema_nodes(nested)


def test_chatgpt_plan_strict_schema_normalizes_dynamic_hands_contract() -> None:
    response_model = build_action_response_model(("open_app", "set_master_volume"))
    schema = _strict_json_schema(response_model.model_json_schema())

    assert isinstance(schema, dict)
    for node in _schema_nodes(schema):
        assert "default" not in node
        if node.get("type") != "object":
            continue
        assert node.get("additionalProperties") is False
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert set(node.get("required", ())) == set(properties)


class _OptionalStrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_name: str
    optional_type: str | None = None


def test_chatgpt_plan_invoke_structured_sends_normalized_strict_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CredentialStore:
        def load(self):
            return _credentials()

        def save(self, credentials) -> None:
            del credentials

    captured: dict[str, object] = {}

    class _StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def __iter__(self):
            delta = {
                "type": "response.output_text.delta",
                "delta": json.dumps(
                    {"required_name": "ok", "optional_type": None},
                    separators=(",", ":"),
                ),
            }
            completed = {
                "type": "response.completed",
                "response": {"usage": {"input_tokens": 1, "output_tokens": 1}},
            }
            yield f"data: {json.dumps(delta)}\\n".encode()
            yield f"data: {json.dumps(completed)}\\n".encode()

    def _urlopen(req, timeout):
        del timeout
        captured.update(json.loads(req.data.decode("utf-8")))
        return _StreamResponse()

    monkeypatch.setattr(chatgpt_plan_module.request, "urlopen", _urlopen)
    manager = ChatGPTPlanSessionManager(
        credential_store=_CredentialStore(),  # type: ignore[arg-type]
        clock=lambda: 100.0,
    )

    response = manager.invoke_structured(
        model="plan-model",
        instructions="system",
        input_payload={"task": "test"},
        schema_name=_OptionalStrictResult.__name__,
        schema=_OptionalStrictResult.model_json_schema(),
        timeout_seconds=1.0,
    )

    schema = captured["text"]["format"]["schema"]  # type: ignore[index]
    assert schema["additionalProperties"] is False  # type: ignore[index]
    assert set(schema["required"]) == {"required_name", "optional_type"}  # type: ignore[index]
    assert "default" not in schema["properties"]["optional_type"]  # type: ignore[index]
    assert response.output_text == '{"required_name":"ok","optional_type":null}'


def test_hands_plan_primary_does_not_require_paid_fallback_key(monkeypatch) -> None:
    class _PlanClient:
        provider_name = "chatgpt_plan"
        model_name = "plan-model"

        async def parse(self, **kwargs):
            raise AssertionError("parse should not run in builder test")

        async def parse_with_telemetry(self, **kwargs):
            raise AssertionError("parse should not run in builder test")

    seen: dict[str, object] = {}

    def _fake_plan_builder(**kwargs):
        seen.update(kwargs)
        return _PlanClient()

    monkeypatch.setattr(hands_planner_module, "provider_api_key", lambda provider: None)
    monkeypatch.setattr(
        hands_planner_module,
        "build_chatgpt_plan_structured_output_client",
        _fake_plan_builder,
    )

    planner = hands_planner_module.build_hands_planner(
        provider="gemini",
        model=None,
        chatgpt_plan_enabled=True,
        chatgpt_plan_model="plan-model",
    )

    assert planner.provider_name == "chatgpt_plan"
    assert planner.model_name == "plan-model"
    assert seen["fallback_provider"] is None
    assert seen["fallback_model"] is None
