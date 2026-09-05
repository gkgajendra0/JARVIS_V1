from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jarvis.ai_provider import (
    AI_PROVIDER_SETTING,
    LEGACY_REALTIME_PROVIDER_SETTING,
    configured_ai_provider,
    credential_environment_name,
    require_provider_api_key,
)

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
        Path("src/jarvis/memory/extractors.py"),
        Path("src/jarvis/voice/livekit_session.py"),
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
