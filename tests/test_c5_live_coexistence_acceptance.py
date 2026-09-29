from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c5_live_coexistence_acceptance.py"


def _load_module():
    name = "jarvis_c5_live_coexistence_acceptance_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_phase_summary_reports_gpu_and_process_metrics() -> None:
    module = _load_module()
    phase = module._PhaseResult(
        name="test",
        samples=(
            {
                "process_cpu_task_manager_percent": 2.0,
                "system_cpu_percent": 10.0,
                "rss_mb": 100.0,
                "gpu_util_percent": 20.0,
                "gpu_memory_used_mb": 4000.0,
                "gpu_memory_total_mb": 8151.0,
            },
            {
                "process_cpu_task_manager_percent": 4.0,
                "system_cpu_percent": 20.0,
                "rss_mb": 120.0,
                "gpu_util_percent": 40.0,
                "gpu_memory_used_mb": 5000.0,
                "gpu_memory_total_mb": 8151.0,
            },
        ),
    )

    summary = module._phase_summary(phase)

    assert summary["name"] == "test"
    assert summary["sample_count"] == 2
    assert summary["metrics"]["gpu_memory_used_mb"]["median"] == 4500.0
    assert summary["metrics"]["gpu_memory_used_mb"]["max"] == 5000.0
    assert summary["metrics"]["gpu_util_percent"]["p95"] == 39.0


def test_process_alive_rejects_zombie(monkeypatch) -> None:
    module = _load_module()

    class FakeProcess:
        def is_running(self):
            return True

        def status(self):
            return module.psutil.STATUS_ZOMBIE

    assert module._process_alive(FakeProcess()) is False


def test_process_alive_accepts_running_process(monkeypatch) -> None:
    module = _load_module()

    class FakeProcess:
        def is_running(self):
            return True

        def status(self):
            return "running"

    assert module._process_alive(FakeProcess()) is True
