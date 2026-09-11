"""Single active cloud-AI provider policy for production JARVIS."""

from __future__ import annotations

import os
from collections.abc import Mapping

from jarvis.machine_config import runtime_environment_overrides_enabled

AI_PROVIDER_SETTING = "JARVIS_AI_PROVIDER"
LEGACY_REALTIME_PROVIDER_SETTING = "JARVIS_REALTIME_PROVIDER"
VALID_AI_PROVIDERS = frozenset({"gemini", "openai"})

_PROVIDER_CREDENTIAL_ENV = {
    "gemini": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# Capability-specific models are selected *inside* the one active provider family.
# These defaults are deliberately centralized so changing JARVIS_AI_PROVIDER cannot
# leave a Gemini model attached to an OpenAI client (or vice versa).
_AI_ROLE_MODEL_DEFAULTS: dict[str, dict[str, str]] = {
    "hands_planner": {
        "gemini": "gemini-3.5-flash",
        "openai": "gpt-5.6-terra",
    },
    "memory_candidate_extraction": {
        "gemini": "gemini-3.5-flash-lite",
        "openai": "gpt-5.6-terra",
    },
    "memory_semantic_recall": {
        "gemini": "gemini-3.8-flash",
        "openai": "gpt-5.6-terra",
    },
}


def normalize_ai_provider(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("AI provider must be a string")
    normalized = value.strip().casefold()
    if normalized not in VALID_AI_PROVIDERS:
        raise ValueError(f"Unsupported {AI_PROVIDER_SETTING}: {value!r}")
    return normalized


def configured_ai_provider(
    machine_settings: Mapping[str, str],
    *,
    default: str = "openai",
) -> str:
    """Resolve the one production AI provider with legacy-setting compatibility.

    Persisted machine configuration remains authoritative unless diagnostic runtime
    overrides are explicitly enabled. ``JARVIS_REALTIME_PROVIDER`` is accepted only
    as a migration alias for existing installations; new configuration owns
    ``JARVIS_AI_PROVIDER``.
    """

    if runtime_environment_overrides_enabled():
        candidates = (
            os.getenv(AI_PROVIDER_SETTING),
            os.getenv(LEGACY_REALTIME_PROVIDER_SETTING),
            machine_settings.get(AI_PROVIDER_SETTING),
            machine_settings.get(LEGACY_REALTIME_PROVIDER_SETTING),
            default,
        )
    else:
        candidates = (
            machine_settings.get(AI_PROVIDER_SETTING),
            machine_settings.get(LEGACY_REALTIME_PROVIDER_SETTING),
            os.getenv(AI_PROVIDER_SETTING),
            os.getenv(LEGACY_REALTIME_PROVIDER_SETTING),
            default,
        )

    for value in candidates:
        if value is not None and value.strip():
            return normalize_ai_provider(value)
    return normalize_ai_provider(default)


def credential_environment_name(provider: str) -> str:
    return _PROVIDER_CREDENTIAL_ENV[normalize_ai_provider(provider)]


def provider_api_key(provider: str) -> str | None:
    value = os.getenv(credential_environment_name(provider))
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def require_provider_api_key(provider: str, *, purpose: str = "cloud AI") -> str:
    normalized = normalize_ai_provider(provider)
    environment_name = credential_environment_name(normalized)
    api_key = provider_api_key(normalized)
    if api_key is None:
        raise RuntimeError(
            f"{environment_name} is required for active {normalized} {purpose}"
        )
    return api_key


def _known_model_provider(model: str) -> str | None:
    """Identify model families whose provider ownership is unambiguous."""

    normalized = model.strip().casefold()
    if normalized.startswith("gemini-"):
        return "gemini"
    if normalized.startswith(("gpt-", "chatgpt-", "codex-", "o1", "o3", "o4")):
        return "openai"
    return None


def resolve_ai_role_model(
    provider: str,
    role: str,
    *,
    configured_model: str | None = None,
) -> str:
    """Resolve a role model without allowing a stale cross-provider model to leak.

    Existing generic role-model settings remain usable for compatibility. If a known
    Gemini model is still configured after switching to OpenAI, or vice versa, JARVIS
    automatically selects the active provider's role default instead. This keeps
    ``JARVIS_AI_PROVIDER`` as the only required provider switch.
    """

    normalized_provider = normalize_ai_provider(provider)
    normalized_role = str(role).strip().casefold()
    defaults = _AI_ROLE_MODEL_DEFAULTS.get(normalized_role)
    if defaults is None:
        raise ValueError(f"Unsupported cloud-AI role: {role!r}")

    if configured_model is not None and str(configured_model).strip():
        candidate = str(configured_model).strip()
        model_provider = _known_model_provider(candidate)
        if model_provider is None or model_provider == normalized_provider:
            return candidate

    return defaults[normalized_provider]
