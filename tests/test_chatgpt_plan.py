from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from jarvis.config import JarvisConfig
from jarvis.chatgpt_plan import (
    CHATGPT_PLAN_REQUIRED_SCOPE,
    CHATGPT_PLAN_TARGET_ID,
    ChatGPTPlanCredentials,
    ChatGPTPlanResponse,
    ChatGPTPlanUsageUnavailable,
    load_or_create_chatgpt_plan_host_id,
)
from jarvis.machine_config import load_machine_settings, save_machine_settings
from jarvis.hands.provider_adapters import (
    ChatGPTPlanStructuredOutputClient,
    FallbackStructuredOutputClient,
    StructuredOutputTelemetry,
)
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
async def test_chatgpt_plan_client_falls_back_when_plan_allowance_is_unavailable() -> None:
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
