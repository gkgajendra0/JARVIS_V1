from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from jarvis.machine_config import save_machine_settings

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL = _REPO_ROOT / "tools" / "research" / "jev_phase9_runtime_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "jarvis_test_jev_phase9_runtime_smoke",
        _TOOL,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load JEV Phase-9 runtime smoke module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_report(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "suite": "jarvis-jev-phase9-candidate-selection-v1",
                "runner": "jev",
                "requested_model": "jev-latest",
                "case_count": 8,
                "repeat": 3,
                "summaries": [
                    {
                        "confidence_threshold": 0.95,
                        "covered": 24,
                        "coverage": 1.0,
                        "accuracy_over_covered": 1.0,
                        "structured_output_failures": 0,
                        "unsafe_downgrades": 0,
                    }
                ],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    work_enabled: bool,
) -> None:
    report = _write_report(tmp_path / "jev-report.json")
    machine = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_WORK_ORCHESTRATION_ENABLED": "true" if work_enabled else "false",
            "JARVIS_JEV_BOUNDED_DECISIONS_ENABLED": "true",
            "JARVIS_JEV_BENCHMARK_ADMITTED": "true",
            "JARVIS_JEV_BENCHMARK_REPORT_PATH": str(report),
            "JARVIS_JEV_MODEL": "jev-latest",
            "JARVIS_JEV_ENDPOINT": "https://api.typesafe.ai/v1/systemone",
            "JARVIS_JEV_MIN_CONFIDENCE": "0.95",
        },
        machine,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(machine))
    monkeypatch.setenv(
        "JARVIS_WORK_DBOS_DATABASE_URL",
        "postgresql://localhost/jarvis_work",
    )
    monkeypatch.setenv("JEV_API_KEY", "test-secret")
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)


def test_runtime_smoke_constructs_admitted_production_advisor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, work_enabled=True)
    module = _load_module()

    result = module.probe_jev_runtime_admission()

    assert result["status"] == "PASS"
    assert result["work_orchestration_enabled"] is True
    assert result["jev_bounded_decisions_enabled"] is True
    assert result["jev_benchmark_admitted"] is True
    assert result["jev_min_confidence"] == pytest.approx(0.95)
    assert result["credential_configured"] is True
    assert result["advisor_constructed"] is True
    assert result["api_calls_made"] == 0


def test_runtime_smoke_rejects_disabled_work_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, work_enabled=False)
    module = _load_module()

    with pytest.raises(RuntimeError, match="work orchestration is disabled"):
        module.probe_jev_runtime_admission()
