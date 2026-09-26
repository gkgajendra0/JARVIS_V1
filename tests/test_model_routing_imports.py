"""Clean-interpreter import regressions for the model-routing package."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_clean_import(code: str) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_leaf_model_import_is_clean_interpreter_safe() -> None:
    result = _run_clean_import(
        "from jarvis.model_routing.models import ModelTarget; print(ModelTarget.__name__)"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ModelTarget"


def test_strategy_import_is_clean_interpreter_safe() -> None:
    result = _run_clean_import(
        "from jarvis.model_routing.strategy import derive_work_step_signals; "
        "print(derive_work_step_signals.__name__)"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "derive_work_step_signals"


def test_public_facade_remains_lazy_and_compatible() -> None:
    result = _run_clean_import(
        "from jarvis.model_routing import ModelRouter, EngineeringStageStrategy; "
        "print(ModelRouter.__name__, EngineeringStageStrategy.__name__)"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ModelRouter EngineeringStageStrategy"
