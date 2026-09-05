from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "tools" / "research" / "step4_phase45d_abstention_calibration.py"
CASES_PATH = ROOT / "tools" / "research" / "step4_phase45d_abstention_cases.json"


def load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "step4_phase45d_abstention_calibration", HARNESS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def case(
    module: ModuleType,
    case_id: str,
    *,
    label: str,
    top1_correct: bool,
    score: float,
    margin: float,
    dense: float,
):
    return module.CalibrationCaseResult(
        case_id=case_id,
        split="calibration",
        label=label,
        expected_memory_id="expected" if label == "release" else None,
        language="en",
        category="test",
        top_memory_id="expected" if top1_correct else "wrong",
        positive_top1_correct=top1_correct,
        positive_hit_at_3=top1_correct,
        rerank_score=score,
        rerank_margin=margin,
        dense_score=dense,
        lexical_rank=1,
        dense_rank=1,
        fused_score=0.03,
        query_embedding_ms=1.0,
        retrieval_ms=1.0,
        rerank_ms=1.0,
    )


def test_fixed_corpus_is_balanced_and_contains_safety_boundaries() -> None:
    module = load_harness()
    payload = module._load_fixture(CASES_PATH)

    assert len(payload["queries"]) == 64
    counts = Counter((item["split"], item["label"]) for item in payload["queries"])
    assert counts == {
        ("calibration", "release"): 16,
        ("calibration", "abstain"): 16,
        ("validation", "release"): 16,
        ("validation", "abstain"): 16,
    }

    languages = {item["language"] for item in payload["queries"]}
    assert languages == {"en", "hi", "hinglish"}

    modes = {item["mode"] for item in payload["documents"]}
    assert {
        "current",
        "historical_transition",
        "forgotten",
        "local_only",
        "secret",
        "untrusted",
    }.issubset(modes)

    abstain_categories = {
        item["category"] for item in payload["queries"] if item["label"] == "abstain"
    }
    assert {
        "absent",
        "near_miss",
        "ambiguous",
        "historical_excluded",
        "forgotten",
        "local_only",
        "secret",
        "untrusted",
        "adversarial_lexical",
        "negation",
        "relation_mismatch",
    }.issubset(abstain_categories)


def test_thresholds_come_from_observed_boundaries_not_magic_constants() -> None:
    module = load_harness()

    thresholds = module._thresholds([1.0, 3.0, 5.0])

    assert thresholds[1:-1] == pytest.approx((2.0, 4.0))
    assert thresholds[0] < 1.0
    assert thresholds[-1] > 5.0


def test_policy_selection_prioritizes_zero_false_release_then_recall() -> None:
    module = load_harness()
    cases = [
        case(
            module,
            "p1",
            label="release",
            top1_correct=True,
            score=8,
            margin=5,
            dense=0.8,
        ),
        case(
            module,
            "p2",
            label="release",
            top1_correct=True,
            score=7,
            margin=4,
            dense=0.7,
        ),
        case(
            module,
            "a1",
            label="abstain",
            top1_correct=False,
            score=2,
            margin=1,
            dense=0.5,
        ),
        case(
            module,
            "a2",
            label="abstain",
            top1_correct=False,
            score=-3,
            margin=2,
            dense=0.4,
        ),
    ]

    selected, metrics, _ = module._select_policy(cases)

    assert metrics["fp"] == 0
    assert metrics["tp"] == 2
    assert metrics["positive_release_recall"] == pytest.approx(1.0)
    assert all(selected.releases(item) for item in cases[:2])
    assert not any(selected.releases(item) for item in cases[2:])


def test_wrong_positive_top1_is_unsafe_to_release() -> None:
    module = load_harness()
    wrong_positive = case(
        module,
        "wrong-positive",
        label="release",
        top1_correct=False,
        score=9,
        margin=7,
        dense=0.9,
    )
    safe_positive = case(
        module,
        "safe-positive",
        label="release",
        top1_correct=True,
        score=8,
        margin=6,
        dense=0.8,
    )
    abstain = case(
        module,
        "abstain",
        label="abstain",
        top1_correct=False,
        score=1,
        margin=1,
        dense=0.3,
    )

    policy = module.ReleasePolicy("score", score_threshold=7.0)
    metrics = module._evaluate_policy(policy, [wrong_positive, safe_positive, abstain])

    assert wrong_positive.should_release is False
    assert metrics["tp"] == 1
    assert metrics["fp"] == 1
    assert metrics["false_release_case_ids"] == ["wrong-positive"]
