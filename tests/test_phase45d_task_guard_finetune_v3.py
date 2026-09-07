from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
CASES_SCRIPT = RESEARCH / "step4_phase45d_task_guard_finetune_v3_cases.py"
HARNESS_SCRIPT = RESEARCH / "step4_phase45d_task_guard_finetune_v3.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cases = _load("phase45d_task_guard_finetune_v3_cases_test", CASES_SCRIPT)
harness = _load("phase45d_task_guard_finetune_v3_test", HARNESS_SCRIPT)


def test_v3_corpus_shape_balance_and_frozen_source_blob() -> None:
    payload = cases.build_payload()

    assert len(payload["train"]) == 384
    assert len(payload["holdout"]) == 192
    assert harness._git_blob_sha(CASES_SCRIPT) == harness.FROZEN_CASE_SOURCE_GIT_BLOB
    assert harness.FROZEN_CASE_SOURCE_GIT_BLOB == (
        "77f614d34b94e44277f4bf4bdaffa5da22989268"
    )

    for split, expected in (("train", 16), ("holdout", 8)):
        rows = payload[split]
        assert Counter((row["language"], row["label"]) for row in rows) == {
            (language, label): expected
            for language in cases.LANGUAGES
            for label in cases.LABELS
        }


def test_v3_train_holdout_and_retired_queries_are_disjoint() -> None:
    payload = harness._assert_frozen_corpus()
    train = {cases.normalized_query(str(row["query"])) for row in payload["train"]}
    holdout = {cases.normalized_query(str(row["query"])) for row in payload["holdout"]}

    assert not train.intersection(holdout)
    harness._assert_no_retired_query_overlap(payload)


def test_v3_candidate_and_training_contracts_are_frozen() -> None:
    by_key = {str(row["key"]): row for row in harness.CANDIDATES}

    assert set(by_key) == {"mmbert_small", "mmbert_base", "xlm_roberta_base"}
    assert by_key["mmbert_small"] == {
        "key": "mmbert_small",
        "model_id": "jhu-clsp/mmBERT-small",
        "revision": "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a",
        "family": "modernbert",
    }
    assert by_key["mmbert_base"] == {
        "key": "mmbert_base",
        "model_id": "jhu-clsp/mmBERT-base",
        "revision": "eaee9e8f76c40fd045034538248ad9d59f380aac",
        "family": "modernbert",
    }
    assert by_key["xlm_roberta_base"] == {
        "key": "xlm_roberta_base",
        "model_id": "FacebookAI/xlm-roberta-base",
        "revision": "42f548f32366559214515ec137cdd16002968bf6",
        "family": "xlm-roberta",
    }

    assert harness.MAX_LENGTH == 128
    assert harness.NUM_TRAIN_EPOCHS == 5.0
    assert harness.TRAIN_BATCH_SIZE == 8
    assert harness.GRADIENT_ACCUMULATION_STEPS == 2
    assert harness.EVAL_BATCH_SIZE == 64
    assert harness.LEARNING_RATE == 2e-5
    assert harness.WEIGHT_DECAY == 0.01
    assert harness.WARMUP_RATIO == 0.10
    assert harness.RANDOM_STATE == 45


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


def test_perfect_v3_predictions_pass_frozen_gate() -> None:
    summary = harness.summarize_predictions(
        _perfect_predictions(),
        macro_f1=1.0,
        accuracy=1.0,
        train_seconds=10.0,
        inference_seconds=0.192,
    )

    assert summary["passes_development_gate"] is True
    assert summary["false_allow_cases"] == 0
    assert summary["overall_allow_recall"] == 1.0
    assert summary["comparison_allow_recall"] == 1.0
    assert all(summary["continuation_checks"].values())


def test_v3_false_allow_is_hard_failure() -> None:
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
        train_seconds=10.0,
        inference_seconds=0.192,
    )

    assert summary["false_allow_cases"] == 1
    assert summary["negation_false_allow_case_ids"] == [row.case_id]
    assert summary["passes_development_gate"] is False


def test_v3_comparison_over_veto_remains_hard_failure() -> None:
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
        train_seconds=10.0,
        inference_seconds=0.192,
    )

    assert summary["false_allow_cases"] == 0
    assert summary["comparison_allow_recall"] < 0.85
    assert summary["passes_development_gate"] is False


def test_v3_selection_ignores_failures_and_uses_frozen_tie_break() -> None:
    def candidate(
        key: str,
        *,
        passes: bool,
        comparison: float,
        overall: float,
        macro_f1: float,
        latency: float,
        parameter_bytes: int,
    ) -> dict[str, object]:
        return {
            "key": key,
            "summary": {
                "passes_development_gate": passes,
                "false_allow_cases": 0,
                "negation_false_allow_case_ids": [],
                "comparison_allow_recall": comparison,
                "overall_allow_recall": overall,
                "macro_f1": macro_f1,
                "inference_ms_per_query": latency,
            },
            "resources": {"parameter_bytes": parameter_bytes},
        }

    results = [
        candidate(
            "failed",
            passes=False,
            comparison=1.0,
            overall=1.0,
            macro_f1=1.0,
            latency=0.1,
            parameter_bytes=1,
        ),
        candidate(
            "small",
            passes=True,
            comparison=0.90,
            overall=0.95,
            macro_f1=0.91,
            latency=1.0,
            parameter_bytes=100,
        ),
        candidate(
            "base",
            passes=True,
            comparison=0.95,
            overall=0.93,
            macro_f1=0.94,
            latency=2.0,
            parameter_bytes=200,
        ),
    ]

    assert harness.select_candidate(results) == "base"
    assert harness.select_candidate([results[0]]) is None
