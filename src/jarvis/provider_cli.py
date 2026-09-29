"""Safe command-line switch for the single production JARVIS AI provider."""

from __future__ import annotations

import argparse

from jarvis.ai_provider import (
    AI_PROVIDER_SETTING,
    LEGACY_REALTIME_PROVIDER_SETTING,
    TTS_PROVIDER_SETTING,
    configured_ai_provider,
    configured_tts_provider,
    credential_environment_name,
    normalize_ai_provider,
    normalize_tts_provider,
    provider_api_key,
    tts_credential_environment_name,
    tts_credential_is_separated,
    tts_provider_api_key,
)
from jarvis.machine_config import (
    default_machine_config_path,
    load_machine_settings,
    save_machine_settings,
)


def _provider_status() -> tuple[str, str, bool]:
    settings = load_machine_settings()
    provider = configured_ai_provider(settings)
    credential_name = credential_environment_name(provider)
    credential_available = provider_api_key(provider) is not None
    return provider, credential_name, credential_available


def _tts_status() -> tuple[str, str, bool, bool]:
    settings = load_machine_settings()
    provider = configured_tts_provider(settings)
    credential_name = tts_credential_environment_name(provider)
    credential_available = tts_provider_api_key(provider) is not None
    return (
        provider,
        credential_name,
        credential_available,
        tts_credential_is_separated(provider),
    )


def show_provider() -> int:
    provider, credential_name, credential_available = _provider_status()
    (
        tts_provider,
        tts_credential_name,
        tts_credential_available,
        tts_separated,
    ) = _tts_status()
    print(f"JARVIS active AI provider: {provider}")
    print(f"Credential variable: {credential_name}")
    print(f"Credential available: {'yes' if credential_available else 'no'}")
    print(f"JARVIS scripted TTS provider: {tts_provider}")
    print(f"TTS credential variable: {tts_credential_name}")
    print(f"TTS credential available: {'yes' if tts_credential_available else 'no'}")
    print(f"TTS credential separated: {'yes' if tts_separated else 'no'}")
    settings = load_machine_settings()
    project_verified = settings.get(
        "JARVIS_TTS_PROJECT_BILLING_ISOLATION_VERIFIED", ""
    ).strip().casefold() in {"1", "true", "yes", "on"}
    print(
        f"TTS project billing isolation verified: {'yes' if project_verified else 'no'}"
    )
    print(f"Machine configuration: {default_machine_config_path()}")
    return 0 if credential_available else 2


def switch_provider(provider: str) -> int:
    selected = normalize_ai_provider(provider)
    credential_name = credential_environment_name(selected)
    if provider_api_key(selected) is None:
        print(
            f"Provider not changed: {credential_name} is not available in this process."
        )
        print(
            "Open a fresh terminal after setting the key, then run this command again."
        )
        return 2

    target = default_machine_config_path()
    settings = load_machine_settings(target)
    previous = configured_ai_provider(settings)
    settings[AI_PROVIDER_SETTING] = selected
    settings.pop(LEGACY_REALTIME_PROVIDER_SETTING, None)
    save_machine_settings(settings, target)

    resolved = configured_ai_provider(load_machine_settings(target))
    if resolved != selected:
        raise RuntimeError(
            f"Provider switch verification failed: expected {selected}, got {resolved}"
        )

    print(f"JARVIS AI provider: {previous} -> {selected}")
    print(f"Credential variable: {credential_name} (available)")
    print("API key value was not read back or printed.")
    print("Restart any running JARVIS voice session before testing the new provider.")
    return 0


def switch_tts_provider(provider: str) -> int:
    selected = normalize_tts_provider(provider)
    credential_name = tts_credential_environment_name(selected)
    if tts_provider_api_key(selected) is None:
        print(
            f"TTS provider not changed: neither {credential_name} nor the "
            "provider compatibility credential is available in this process."
        )
        return 2

    target = default_machine_config_path()
    settings = load_machine_settings(target)
    previous = configured_tts_provider(settings)
    settings[TTS_PROVIDER_SETTING] = selected
    save_machine_settings(settings, target)

    resolved = configured_tts_provider(load_machine_settings(target))
    if resolved != selected:
        raise RuntimeError(
            f"TTS provider switch verification failed: expected {selected}, got {resolved}"
        )

    print(f"JARVIS scripted TTS provider: {previous} -> {selected}")
    print(f"Dedicated TTS credential variable: {credential_name}")
    print(
        "Credential separation: "
        f"{'dedicated' if tts_credential_is_separated(selected) else 'compatibility/shared'}"
    )
    print("API key value was not read back or printed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show or switch the single active JARVIS cloud-AI provider"
    )
    parser.add_argument(
        "provider",
        nargs="?",
        choices=("gemini", "openai"),
        help="provider to persist for all JARVIS cloud-brain roles",
    )
    parser.add_argument(
        "--tts-provider",
        choices=("gemini", "openai"),
        help="persist the independent scripted-TTS provider",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="show brain and scripted-TTS provider/credential status",
    )
    args = parser.parse_args(argv)

    if args.provider is not None and args.tts_provider is not None:
        parser.error("choose either the brain provider or --tts-provider, not both")
    if args.tts_provider is not None:
        return switch_tts_provider(args.tts_provider)
    if args.provider is not None:
        return switch_provider(args.provider)
    return show_provider()


if __name__ == "__main__":
    raise SystemExit(main())
