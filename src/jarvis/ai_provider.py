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
