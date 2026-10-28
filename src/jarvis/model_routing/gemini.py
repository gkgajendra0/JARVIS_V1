"""Gemini credential targets/configuration subordinate to ModelRouter policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jarvis.ai_provider import gemini_credential_ref
from jarvis.machine_config import configured_text
from jarvis.model_routing.models import (
    BenchmarkStatus,
    CostProfile,
    ModelLocality,
    ModelTarget,
)


@dataclass(frozen=True, slots=True)
class GeminiFallbackConfig:
    enabled: bool = False
    budget_enforced: bool = True
    budget_id: str = "gemini-paid-fallback-v1"
    ceiling_inr_minor: int = 35000
    cooldown_seconds: int = 60
    max_cooldown_seconds: int = 900
    pricing_path: Path | None = None
    live_policy_mode: str = "strict"

    def __post_init__(self) -> None:
        if self.live_policy_mode not in {"strict", "operational_v1"}:
            raise ValueError("Unsupported Gemini Paid Live policy")
        if type(self.budget_enforced) is not bool:
            raise TypeError("Gemini budget_enforced must be bool")
        if type(self.enabled) is not bool:
            raise TypeError("Gemini fallback enabled must be bool")
        if not isinstance(self.budget_id, str) or not self.budget_id.strip():
            raise ValueError("Gemini fallback budget_id required")
        for name in ("ceiling_inr_minor", "cooldown_seconds", "max_cooldown_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"Gemini fallback {name} must be a positive integer")
        if self.max_cooldown_seconds < self.cooldown_seconds:
            raise ValueError("Gemini fallback cooldown cap is below base")
        if self.pricing_path is not None and not isinstance(self.pricing_path, Path):
            raise TypeError("Gemini pricing_path must be a Path")

    @classmethod
    def from_settings(cls, settings: Mapping[str, str]) -> GeminiFallbackConfig:
        enabled = configured_text(
            "JARVIS_GEMINI_PAID_FALLBACK_ENABLED", settings, "false"
        )
        normalized = str(enabled).strip().casefold()
        if normalized not in {"true", "1", "yes", "on", "false", "0", "no", "off"}:
            raise ValueError("Unsupported JARVIS_GEMINI_PAID_FALLBACK_ENABLED")
        budget_text = (
            str(configured_text("JARVIS_GEMINI_PAID_BUDGET_ENABLED", settings, "true"))
            .strip()
            .casefold()
        )
        if budget_text not in {"true", "1", "yes", "on", "false", "0", "no", "off"}:
            raise ValueError("Unsupported JARVIS_GEMINI_PAID_BUDGET_ENABLED")
        values = {}
        for field_name, env_name, default in (
            ("ceiling_inr_minor", "JARVIS_GEMINI_PAID_CEILING_INR_MINOR", 35000),
            ("cooldown_seconds", "JARVIS_GEMINI_FREE_COOLDOWN_SECONDS", 60),
            ("max_cooldown_seconds", "JARVIS_GEMINI_FREE_MAX_COOLDOWN_SECONDS", 900),
        ):
            try:
                values[field_name] = int(
                    configured_text(env_name, settings, str(default))
                )
            except (TypeError, ValueError):
                raise ValueError(f"Unsupported {env_name}") from None
        path = configured_text("JARVIS_GEMINI_PAID_PRICING_FILE", settings)
        return cls(
            enabled=normalized in {"true", "1", "yes", "on"},
            budget_enforced=budget_text in {"true", "1", "yes", "on"},
            budget_id=configured_text(
                "JARVIS_GEMINI_PAID_BUDGET_ID", settings, "gemini-paid-fallback-v1"
            ),
            pricing_path=Path(path) if path else None,
            live_policy_mode=configured_text(
                "JARVIS_GEMINI_PAID_LIVE_POLICY", settings, "strict"
            ),
            **values,
        )


_ROLE_CAPABILITIES = {
    "work": ("engineering_reasoning", "structured_output"),
    "hands": ("hands_planning", "structured_output"),
    "memory.extraction": ("memory_extraction", "structured_output"),
    "memory.resolution": ("memory_resolution", "structured_output"),
    "memory.recall": ("memory_recall", "structured_output"),
    "voice.live": ("realtime_voice", "tool_calling"),
}


def build_gemini_role_targets(
    *,
    role: str,
    model: str,
    adapter_id: str,
    config: GeminiFallbackConfig,
    cost_profile: CostProfile | None = None,
) -> tuple[ModelTarget, ...]:
    if role not in _ROLE_CAPABILITIES:
        raise ValueError("Unsupported Gemini routing role")
    if not isinstance(config, GeminiFallbackConfig):
        raise TypeError("GeminiFallbackConfig required")
    live = role == "voice.live"
    return tuple(
        ModelTarget(
            target_id=f"{role}.gemini.{slot}.{model}",
            adapter_id=adapter_id,
            provider_id="gemini",
            model_id=model,
            locality=ModelLocality.CLOUD,
            capabilities=_ROLE_CAPABILITIES[role],
            roles=("efficient", "capable"),
            max_context_tokens=32000,
            supports_structured_output=not live,
            supports_tools=live,
            supports_streaming=live,
            latency_class="realtime" if live else "standard",
            benchmark_status=BenchmarkStatus.ACCEPTED,
            registry_version=2,
            credential_ref=gemini_credential_ref(slot),
            cost_profile=cost_profile if slot == "paid" else None,
        )
        for slot in (("free", "paid") if config.enabled else ("free",))
    )


def gemini_paid_fallback_allowed(failure, *, source_target: ModelTarget) -> bool:
    """Admit Free quota pressure, plus explicit HTTP 503 for Hands planning."""
    from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind

    return (
        isinstance(failure, ProviderFailure)
        and failure.provider == "gemini"
        and source_target.provider_id == "gemini"
        and source_target.credential_ref == gemini_credential_ref("free")
        and (
            (
                failure.status_code in {None, 429}
                and failure.kind
                in {
                    ProviderFailureKind.QUOTA_EXHAUSTED,
                    ProviderFailureKind.RATE_LIMITED,
                }
            )
            or (
                failure.status_code == 503
                and failure.kind is ProviderFailureKind.SERVICE_UNAVAILABLE
                and "hands_planning" in source_target.capabilities
            )
        )
    )
