from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from jarvis.ai_provider import (
    AI_PROVIDER_SETTING,
    LEGACY_REALTIME_PROVIDER_SETTING,
    configured_ai_provider,
    credential_environment_name,
    require_provider_api_key,
    resolve_ai_role_model,
)
from jarvis.config import JarvisConfig

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "jarvis"


def test_provider_credential_mapping_is_central_and_explicit() -> None:
    assert credential_environment_name("gemini") == "GOOGLE_API_KEY"
    assert credential_environment_name("openai") == "OPENAI_API_KEY"


def test_require_provider_api_key_reads_only_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")

    assert require_provider_api_key("gemini") == "google-test"
    assert require_provider_api_key("openai") == "openai-test"


def test_configured_provider_accepts_legacy_machine_profile_without_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(AI_PROVIDER_SETTING, raising=False)
    monkeypatch.delenv(LEGACY_REALTIME_PROVIDER_SETTING, raising=False)
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)

    assert (
        configured_ai_provider({LEGACY_REALTIME_PROVIDER_SETTING: "gemini"}) == "gemini"
    )


def test_canonical_provider_wins_over_legacy_alias_inside_machine_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)

    assert (
        configured_ai_provider(
            {
                AI_PROVIDER_SETTING: "openai",
                LEGACY_REALTIME_PROVIDER_SETTING: "gemini",
            }
        )
        == "openai"
    )


def test_jarvis_config_has_exactly_one_active_ai_provider_field() -> None:
    """Protect the one-switch brain contract across all production subsystems."""

    provider_fields = [
        field.name for field in fields(JarvisConfig) if field.name.endswith("provider")
    ]

    assert provider_fields == ["ai_provider"]


@pytest.mark.parametrize(
    ("role", "stale_model", "expected_openai", "expected_gemini"),
    [
        (
            "hands_planner",
            "gemini-3.5-flash",
            "gpt-5.6-terra",
            "gemini-3.5-flash",
        ),
        (
            "memory_candidate_extraction",
            "gemini-3.5-flash-lite",
            "gpt-5.6-terra",
            "gemini-3.5-flash-lite",
        ),
        (
            "memory_semantic_recall",
            "gemini-3.8-flash",
            "gpt-5.6-terra",
            "gemini-3.8-flash",
        ),
    ],
)
def test_switching_to_openai_replaces_stale_gemini_role_models(
    role: str,
    stale_model: str,
    expected_openai: str,
    expected_gemini: str,
) -> None:
    assert (
        resolve_ai_role_model("openai", role, configured_model=stale_model)
        == expected_openai
    )
    assert (
        resolve_ai_role_model("gemini", role, configured_model=stale_model)
        == expected_gemini
    )


@pytest.mark.parametrize(
    ("role", "stale_model", "expected_gemini"),
    [
        ("hands_planner", "gpt-5.6-terra", "gemini-3.5-flash"),
        (
            "memory_candidate_extraction",
            "gpt-5.6-terra",
            "gemini-3.5-flash-lite",
        ),
        ("memory_semantic_recall", "gpt-5.6-terra", "gemini-3.8-flash"),
    ],
)
def test_switching_back_to_gemini_replaces_stale_openai_role_models(
    role: str,
    stale_model: str,
    expected_gemini: str,
) -> None:
    assert (
        resolve_ai_role_model("gemini", role, configured_model=stale_model)
        == expected_gemini
    )


def test_same_provider_custom_role_model_is_preserved() -> None:
    assert (
        resolve_ai_role_model(
            "openai",
            "hands_planner",
            configured_model="gpt-5.6-luna",
        )
        == "gpt-5.6-luna"
    )
    assert (
        resolve_ai_role_model(
            "gemini",
            "hands_planner",
            configured_model="gemini-3.6-flash",
        )
        == "gemini-3.6-flash"
    )


def test_production_source_has_one_provider_selector_and_one_credential_owner() -> None:
    credential_literals = {"OPENAI_API_KEY", "GOOGLE_API_KEY"}
    credential_owners: dict[str, set[Path]] = {
        value: set() for value in credential_literals
    }
    forbidden_secondary_selector = "memory_candidate_extraction_provider"

    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert forbidden_secondary_selector not in source, path
        for literal in credential_literals:
            if literal in source:
                credential_owners[literal].add(path.relative_to(ROOT))

    expected = {Path("src/jarvis/ai_provider.py")}
    assert credential_owners == {
        "OPENAI_API_KEY": expected,
        "GOOGLE_API_KEY": expected,
    }


def test_provider_sdk_imports_stay_inside_approved_adapter_boundaries() -> None:
    allowed = {
        Path("src/jarvis/computer/providers.py"),
        Path("src/jarvis/hands/provider_adapters.py"),
        Path("src/jarvis/memory/extractors.py"),
        Path("src/jarvis/memory/query_interpreters.py"),
        Path("src/jarvis/voice/livekit_session.py"),
        Path("src/jarvis/voice/scripted_speech.py"),
    }
    violations: list[tuple[Path, str]] = []

    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.append(node.module)
                if node.module == "livekit.plugins":
                    modules.extend(
                        f"livekit.plugins.{alias.name}" for alias in node.names
                    )
            for module in modules:
                if (
                    module
                    in {
                        "openai",
                        "google.genai",
                        "livekit.plugins.google",
                        "livekit.plugins.openai",
                    }
                    or module.startswith(("openai.", "google.genai."))
                ) and relative not in allowed:
                    violations.append((relative, module))

    assert violations == []
