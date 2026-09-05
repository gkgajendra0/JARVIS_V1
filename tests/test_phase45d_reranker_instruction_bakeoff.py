from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "tools" / "research"


def load_harness():
    sys.path.insert(0, str(RESEARCH_DIR))
    try:
        sys.modules.pop("step4_phase45d_reranker_instruction_bakeoff", None)
        return importlib.import_module("step4_phase45d_reranker_instruction_bakeoff")
    finally:
        try:
            sys.path.remove(str(RESEARCH_DIR))
        except ValueError:
            pass


def case(
    module,
    case_id: str,
    *,
    safe: bool,
    score: float,
    margin: float,
    language: str = "en",
):
    return module.DevCase(
        case_id=case_id,
        label="release" if safe else "abstain",
        language=language,
        category="test",
        expected_memory_id="memory" if safe else None,
        top_memory_id="memory" if safe else "other",
        positive_top1_correct=safe,
        positive_hit_at_3=safe,
        rerank_score=score,
        rerank_margin=margin,
        rerank_ms=1.0,
    )


def test_binary_auc_and_risk_coverage_reward_safe_score_separation() -> None:
    module = load_harness()
    cases = [
        case(module, "p1", safe=True, score=9.0, margin=5.0),
        case(module, "p2", safe=True, score=8.0, margin=4.0),
        case(module, "n1", safe=False, score=2.0, margin=1.0),
        case(module, "n2", safe=False, score=-1.0, margin=0.5),
    ]

    assert module._binary_auc(cases, "rerank_score") == pytest.approx(1.0)
    risk = module._risk_coverage(cases)
    assert risk["zero_error_prefix_cases"] == 2
    assert risk["zero_error_coverage"] == pytest.approx(0.5)
    assert risk["zero_error_positive_release_recall"] == pytest.approx(1.0)


def test_custom_instruction_cannot_win_with_language_top1_regression() -> None:
    module = load_harness()
    default = {
        "positive_top1_accuracy": 0.8,
        "score_auroc_safe_vs_unsafe": 0.8,
        "risk_coverage": {"aurc": 0.2, "zero_error_positive_release_recall": 0.5},
        "language_breakdown": {
            "en": {"positive_top1_accuracy": 0.8},
            "hi": {"positive_top1_accuracy": 0.8},
            "hinglish": {"positive_top1_accuracy": 0.8},
        },
    }
    custom = {
        "positive_top1_accuracy": 0.9,
        "score_auroc_safe_vs_unsafe": 0.9,
        "risk_coverage": {"aurc": 0.1, "zero_error_positive_release_recall": 0.7},
        "language_breakdown": {
            "en": {"positive_top1_accuracy": 0.9},
            "hi": {"positive_top1_accuracy": 0.7},
            "hinglish": {"positive_top1_accuracy": 0.9},
        },
    }

    recommendation = module._recommend(default, custom)

    assert recommendation["mode"] == "default"
    assert "language" in recommendation["reason"]


def test_custom_instruction_can_win_on_pre_registered_metric_order() -> None:
    module = load_harness()
    default = {
        "positive_top1_accuracy": 0.8,
        "score_auroc_safe_vs_unsafe": 0.8,
        "risk_coverage": {"aurc": 0.2, "zero_error_positive_release_recall": 0.5},
        "language_breakdown": {
            "en": {"positive_top1_accuracy": 0.8},
            "hi": {"positive_top1_accuracy": 0.8},
            "hinglish": {"positive_top1_accuracy": 0.8},
        },
    }
    custom = {
        "positive_top1_accuracy": 0.9,
        "score_auroc_safe_vs_unsafe": 0.85,
        "risk_coverage": {"aurc": 0.15, "zero_error_positive_release_recall": 0.6},
        "language_breakdown": {
            "en": {"positive_top1_accuracy": 0.9},
            "hi": {"positive_top1_accuracy": 0.8},
            "hinglish": {"positive_top1_accuracy": 0.9},
        },
    }

    recommendation = module._recommend(default, custom)

    assert recommendation["mode"] == "jarvis_memory"
