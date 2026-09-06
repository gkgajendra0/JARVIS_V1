from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "research" / "step4_phase45d_sfst_diagnostic.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("step4_phase45d_sfst_diagnostic", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_zero_error_power_explains_holm_infeasibility() -> None:
    module = _load()

    summary = module.zero_error_power_summary(96)

    assert summary["zero_error_best_case_p_value"] == 0.0072688567
    assert summary["single_hypothesis_alpha"] == 0.05
    assert summary["holm_first_step_alpha"] == 0.0016666667
    assert summary["zero_error_effective_n_needed_single_hypothesis"] == 59
    assert summary["zero_error_effective_n_needed_holm_first_step"] == 125
    assert summary["holm_best_case_can_clear_first_step"] is False


def test_release_predict_requires_score_and_margin() -> None:
    module = _load()

    predicted = module._release_predict(
        [[6.0, 8.0], [5.9, 8.0], [6.0, 7.9], [9.0, 12.0]],
        6.0,
        8.0,
    )

    assert predicted.tolist() == [1, 0, 0, 1]


def test_metrics_counts_wrong_release_as_false_positive() -> None:
    module = _load()
    cases = [
        {
            "case_id": "safe",
            "label": "release",
            "safe_to_release": True,
            "rerank_score": 8.0,
            "rerank_margin": 8.0,
        },
        {
            "case_id": "wrong",
            "label": "release",
            "safe_to_release": False,
            "rerank_score": 9.0,
            "rerank_margin": 9.0,
        },
        {
            "case_id": "absent",
            "label": "abstain",
            "safe_to_release": False,
            "rerank_score": -2.0,
            "rerank_margin": 1.0,
        },
    ]

    metrics = module._metrics(cases, (6.0, 4.0))

    assert metrics["tp"] == 1
    assert metrics["fp"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["positive_release_recall"] == 0.5
    assert metrics["false_release_case_ids"] == ["wrong"]
