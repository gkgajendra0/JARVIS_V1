from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
CASES_SCRIPT = RESEARCH / "step4_phase45d_task_specific_guard_cases.py"
HARNESS_SCRIPT = RESEARCH / "step4_phase45d_task_specific_guard_bakeoff.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cases = _load("phase45d_task_specific_guard_cases_test", CASES_SCRIPT)
harness = _load("phase45d_task_specific_guard_bakeoff_test", HARNESS_SCRIPT)


def test_task_specific_corpus_shape_balance_and_frozen_hash() -> None:
    payload = cases.build_payload()

    assert len(payload["train"]) == 288
    assert len(payload["holdout"]) == 192
    assert cases.payload_sha256(payload) == harness.FROZEN_CORPUS_SHA256
    assert harness.FROZEN_CORPUS_SHA256 == (
        "ae854ed664ef6ee0214f65f5fe4b252099fd1dcaea00c13aaf7789cd84afd3ab"
    )

    for split, expected in (("train", 12), ("holdout", 8)):
        rows = payload[split]
        assert Counter((row["language"], row["label"]) for row in rows) == {
            (language, label): expected
            for language in cases.LANGUAGES
            for label in cases.LABELS
        }


def test_train_holdout_and_retired_v4_have_no_exact_query_overlap() -> None:
    payload = cases.build_payload()
    train = {cases.normalized_query(str(row["query"])) for row in payload["train"]}
    holdout = {cases.normalized_query(str(row["query"])) for row in payload["holdout"]}

    assert not train.intersection(holdout)
    harness._assert_no_v4_exact_query_overlap(payload)


def test_candidate_input_contracts_are_frozen() -> None:
    by_key = {str(row["key"]): row for row in harness.CANDIDATES}

    assert by_key["multilingual_minilm_l12"]["input_prefix"] == ""
    assert by_key["multilingual_e5_small"]["input_prefix"] == "query: "
    assert by_key["multilingual_mpnet_base_v2"]["input_prefix"] == ""

    rows = [{"query": "hello"}, {"query": "नमस्ते"}]
    assert harness._texts(rows, prefix="query: ") == ["query: hello", "query: नमस्ते"]


def _perfect_predictions():
    output = []
    for row in cases.build_payload()["holdout"]:
        label = str(row["label"])
        output.append(
            harness.CandidatePrediction(
                case_id=str(row["case_id"]),
                language=str(row["language"]),
                expected_label=label,
                predicted_label=label,
                expected_allow=bool(row["allow"]),
                predicted_allow=bool(row["allow"]),
            )
        )
    return output


def test_perfect_predictions_pass_frozen_development_gate() -> None:
    summary = harness.summarize_predictions(
        _perfect_predictions(),
        macro_f1=1.0,
        accuracy=1.0,
        train_seconds=1.0,
        holdout_encode_seconds=0.192,
        embedding_dimension=384,
    )

    assert summary["passes_development_gate"] is True
    assert summary["false_allow_cases"] == 0
    assert summary["overall_allow_recall"] == 1.0
    assert summary["comparison_allow_recall"] == 1.0
    assert all(summary["continuation_checks"].values())


def test_one_negation_false_allow_fails_development_gate() -> None:
    rows = _perfect_predictions()
    index = next(
        index
        for index, row in enumerate(rows)
        if row.expected_label == "negated_or_contradicted"
    )
    row = rows[index]
    rows[index] = harness.CandidatePrediction(
        case_id=row.case_id,
        language=row.language,
        expected_label=row.expected_label,
        predicted_label="current_value_comparison",
        expected_allow=False,
        predicted_allow=True,
    )
    summary = harness.summarize_predictions(
        rows,
        macro_f1=0.99,
        accuracy=0.99,
        train_seconds=1.0,
        holdout_encode_seconds=0.192,
        embedding_dimension=384,
    )

    assert summary["passes_development_gate"] is False
    assert summary["false_allow_cases"] == 1
    assert summary["negation_false_allow_case_ids"] == [row.case_id]
    assert summary["continuation_checks"]["zero_negation_false_allows"] is False


def test_comparison_over_veto_fails_even_with_zero_false_allows() -> None:
    rows = _perfect_predictions()
    comparison_indexes = [
        index
        for index, row in enumerate(rows)
        if row.expected_label == "current_value_comparison"
    ][:5]
    for index in comparison_indexes:
        row = rows[index]
        rows[index] = harness.CandidatePrediction(
            case_id=row.case_id,
            language=row.language,
            expected_label=row.expected_label,
            predicted_label="reason_explanation",
            expected_allow=True,
            predicted_allow=False,
        )
    summary = harness.summarize_predictions(
        rows,
        macro_f1=0.95,
        accuracy=0.95,
        train_seconds=1.0,
        holdout_encode_seconds=0.192,
        embedding_dimension=384,
    )

    assert summary["false_allow_cases"] == 0
    assert summary["comparison_allow_recall"] < 0.85
    assert summary["passes_development_gate"] is False


def test_candidate_selection_uses_only_passing_candidates_and_safety_first() -> None:
    def result(
        key: str,
        *,
        passes: bool,
        comparison: float,
        overall: float,
        macro_f1: float,
        latency: float,
        false_allows: int = 0,
        negation_false_allows: int = 0,
    ):
        return {
            "key": key,
            "summary": {
                "passes_development_gate": passes,
                "false_allow_cases": false_allows,
                "negation_false_allow_case_ids": [
                    f"x{i}" for i in range(negation_false_allows)
                ],
                "comparison_allow_recall": comparison,
                "overall_allow_recall": overall,
                "macro_f1": macro_f1,
                "holdout_encode_ms_per_query": latency,
            },
        }

    results = [
        result(
            "failed_but_fast",
            passes=False,
            comparison=1.0,
            overall=1.0,
            macro_f1=1.0,
            latency=0.1,
        ),
        result(
            "safe_lower_comparison",
            passes=True,
            comparison=0.90,
            overall=0.95,
            macro_f1=0.94,
            latency=1.0,
        ),
        result(
            "safe_higher_comparison",
            passes=True,
            comparison=0.95,
            overall=0.94,
            macro_f1=0.93,
            latency=2.0,
        ),
    ]

    assert harness.select_candidate(results) == "safe_higher_comparison"


def test_no_candidate_is_selected_when_all_fail() -> None:
    results = [
        {
            "key": candidate["key"],
            "summary": {
                "passes_development_gate": False,
                "false_allow_cases": 0,
                "negation_false_allow_case_ids": [],
                "comparison_allow_recall": 1.0,
                "overall_allow_recall": 1.0,
                "macro_f1": 1.0,
                "holdout_encode_ms_per_query": 1.0,
            },
        }
        for candidate in harness.CANDIDATES
    ]

    assert harness.select_candidate(results) is None
