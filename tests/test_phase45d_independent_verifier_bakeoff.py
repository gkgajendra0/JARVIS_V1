from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"


def _load():
    research = str(RESEARCH)
    if research not in sys.path:
        sys.path.insert(0, research)
    return importlib.import_module("step4_phase45d_independent_verifier_bakeoff")


def test_memory_text_index_contains_current_and_replacement_records() -> None:
    module = _load()
    corpus = module.final_cases.build_payload()
    index = module._memory_text_index(corpus)

    assert index["editor"].endswith("Visual Studio Code.")
    assert index["current_sync_mode"].endswith("automatic.")


def test_model_choice_is_small_standard_cross_encoder() -> None:
    module = _load()

    assert module.MODEL_ID == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    assert module.MIN_DEVELOPMENT_RECALL == 0.40
    assert module.MIN_LANGUAGE_RECALL == 0.25


def test_language_breakdown_applies_selected_probability_threshold() -> None:
    module = _load()
    cases = [
        {"case_id": "en-safe", "language": "en", "safe_to_release": True},
        {"case_id": "en-unsafe", "language": "en", "safe_to_release": False},
        {"case_id": "hi-safe", "language": "hi", "safe_to_release": True},
        {
            "case_id": "hinglish-safe",
            "language": "hinglish",
            "safe_to_release": True,
        },
    ]
    probabilities = np.asarray([0.95, 0.20, 0.91, 0.89], dtype=np.float64)
    operating_point = {"found": True, "best": {"threshold": 0.90}}

    result = module._language_breakdown(cases, probabilities, operating_point)

    assert result["en"]["positive_release_recall"] == 1.0
    assert result["en"]["false_release_case_ids"] == []
    assert result["hi"]["positive_release_recall"] == 1.0
    assert result["hinglish"]["positive_release_recall"] == 0.0


def test_recommendation_requires_recall_and_language_floors() -> None:
    module = _load()
    baseline = {"roc_auc": 0.88, "average_precision": 0.87}
    augmented = {
        "roc_auc": 0.91,
        "average_precision": 0.90,
        "empirical_operating_point": {
            "found": True,
            "best": {"precision": 0.96, "recall": 0.45},
        },
    }
    languages = {
        "en": {"positive_release_recall": 0.50},
        "hi": {"positive_release_recall": 0.30},
        "hinglish": {"positive_release_recall": 0.25},
    }

    promising = module._recommendation(baseline, augmented, languages)
    assert promising["decision"] == "independent_signal_promising"

    languages["hi"]["positive_release_recall"] = 0.20
    insufficient = module._recommendation(baseline, augmented, languages)
    assert insufficient["decision"] == "independent_signal_insufficient"
