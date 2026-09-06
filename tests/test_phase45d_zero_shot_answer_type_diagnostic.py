from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
SCRIPT = RESEARCH / "step4_phase45d_zero_shot_answer_type_diagnostic.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

spec = importlib.util.spec_from_file_location("phase45d_zero_shot_answer_type", SCRIPT)
assert spec is not None
assert spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _perfect_scores(cases):
    scores = {}
    for item in cases:
        expected = module._expected_answer_type(item)
        probabilities = {key: 0.01 for key in module.ANSWER_TYPE_KEYS}
        probabilities[expected] = 0.94
        scores[str(item["case_id"])] = probabilities
    return scores


def _counts(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def test_frozen_answer_type_taxonomy() -> None:
    assert module.ANSWER_TYPE_KEYS == (
        "current_value",
        "current_value_comparison",
        "reason_explanation",
        "provenance_actor",
        "replacement_successor",
        "related_record",
        "other_or_advice",
    )
    assert module.ALLOW_TYPES == frozenset(
        {"current_value", "current_value_comparison"}
    )
    assert module.HYPOTHESIS_TEMPLATE == "This question asks for {description}."


def test_select_cases_is_frozen_30_case_semantic_current_set() -> None:
    cases = module.select_cases()
    assert len(cases) == 30
    assert len({str(item["case_id"]) for item in cases}) == 30
    assert not any(
        str(item["category"]) in module.SECURITY_CATEGORIES for item in cases
    )

    expected_types = _counts(module._expected_answer_type(item) for item in cases)
    assert expected_types == {
        "current_value": 9,
        "current_value_comparison": 3,
        "reason_explanation": 3,
        "provenance_actor": 3,
        "replacement_successor": 3,
        "related_record": 6,
        "other_or_advice": 3,
    }
    assert sum(module._expected_allow(item) for item in cases) == 12


def test_build_pairs_creates_seven_hypotheses_per_query() -> None:
    cases = module.select_cases()
    pairs = module.build_pairs(cases)
    assert len(pairs) == 30 * 7
    counts = _counts(case_id for case_id, _, _ in pairs)
    assert set(counts.values()) == {7}
    assert all(
        hypothesis.startswith("This question asks for ") for _, _, hypothesis in pairs
    )


def test_perfect_answer_type_scores_pass_all_continuation_gates() -> None:
    cases = module.select_cases()
    results = module.evaluate(cases, _perfect_scores(cases))
    summary = module.summarize(results)

    assert summary["cases"] == 30
    assert summary["allow_targets"] == 12
    assert summary["veto_targets"] == 18
    assert summary["allowed_target_cases"] == 12
    assert summary["false_allow_cases"] == 0
    assert summary["false_veto_cases"] == 0
    assert summary["exact_answer_type_matches"] == 30
    assert summary["exact_answer_type_accuracy"] == 1.0
    assert summary["direct_allowed"] == 9
    assert summary["relation_comparison_allowed"] == 3
    assert summary["promising_for_architecture_review"] is True
    assert all(summary["continuation_checks"].values())


def test_one_false_allow_fails_architecture_review_gate() -> None:
    cases = module.select_cases()
    scores = _perfect_scores(cases)
    target = next(item for item in cases if item["category"] == "near_miss")
    case_id = str(target["case_id"])
    scores[case_id] = {key: 0.01 for key in module.ANSWER_TYPE_KEYS}
    scores[case_id]["current_value"] = 0.94

    results = module.evaluate(cases, scores)
    summary = module.summarize(results)

    assert summary["false_allow_cases"] == 1
    assert summary["false_allow_case_ids"] == [case_id]
    assert summary["continuation_checks"]["zero_false_allows"] is False
    assert summary["promising_for_architecture_review"] is False


def test_one_false_veto_reduces_allow_recall_without_creating_false_allow() -> None:
    cases = module.select_cases()
    scores = _perfect_scores(cases)
    target = next(item for item in cases if module._expected_allow(item))
    case_id = str(target["case_id"])
    scores[case_id] = {key: 0.01 for key in module.ANSWER_TYPE_KEYS}
    scores[case_id]["other_or_advice"] = 0.94

    results = module.evaluate(cases, scores)
    summary = module.summarize(results)

    assert summary["false_allow_cases"] == 0
    assert summary["false_veto_cases"] == 1
    assert summary["allowed_target_cases"] == 11
