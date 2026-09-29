from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from jarvis.machine_config import load_machine_settings, save_machine_settings

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL = _REPO_ROOT / "tools" / "research" / "c3_global_brain_router_owner_acceptance.py"


def _run_tool(machine_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["JARVIS_MACHINE_CONFIG"] = str(machine_path)
    environment.pop("JARVIS_RUNTIME_ENV_OVERRIDES", None)
    environment.pop("JARVIS_GLOBAL_BRAIN_ROUTER_MODE", None)
    return subprocess.run(
        [sys.executable, str(_TOOL), *args],
        cwd=_REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_c3_owner_acceptance_is_zero_cloud_and_does_not_write_by_default(
    tmp_path: Path,
) -> None:
    machine_path = tmp_path / "machine.json"

    result = _run_tool(machine_path)

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "PASS"
    assert report["cloud_provider_called"] is False
    assert report["production_database_touched"] is False
    assert report["acceptance"]["model_reasoner_calls"] == 0
    assert report["acceptance"]["model_routing_attempts"] == 0
    assert report["acceptance"]["model_calls_avoided"] == 1
    assert report["acceptance"]["route_kind"] == "deterministic"
    assert machine_path.exists() is False


def test_c3_owner_acceptance_apply_preserves_machine_profile(
    tmp_path: Path,
) -> None:
    machine_path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_AI_PROVIDER": "gemini",
            "JARVIS_TTS_PROVIDER": "gemini",
            "JARVIS_GLOBAL_BRAIN_ROUTER_MODE": "shadow",
        },
        machine_path,
    )

    result = _run_tool(machine_path, "--apply")

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "PASS"
    assert report["machine_before"]["persisted"] == "shadow"
    assert report["machine_after"]["persisted"] == "apply"
    assert report["machine_after"]["resolved"] == "apply"

    settings = load_machine_settings(machine_path)
    assert settings["JARVIS_AI_PROVIDER"] == "gemini"
    assert settings["JARVIS_TTS_PROVIDER"] == "gemini"
    assert settings["JARVIS_GLOBAL_BRAIN_ROUTER_MODE"] == "apply"
