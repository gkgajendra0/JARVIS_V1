from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
CASES_SCRIPT = RESEARCH / "step4_phase45d_answerability_cases.py"
HARNESS_SCRIPT = RESEARCH / "step4_phase45d_answerability_bakeoff.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cases = _load("phase45d_answerability_cases_test", CASES_SCRIPT)
harness = _load("phase45d_answerability_bakeoff_test", HARNESS_SCRIPT)


def test_answerability_corpus_shape_balance_and_frozen_hash() -> None:
    payload = cases.build_payload()
    qa_rows = payload["qa_cases"]
    nli_rows = payload["nli_cases"]

    assert len(qa_rows) == 288
    assert len(nli_rows) == 96
    assert cases.payload_sha256(payload) == harness.FROZEN_PAYLOAD_SHA256
    assert harness.FROZEN_PAYLOAD_SHA256 == (
        "3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3"
    )

    assert Counter((row["language"], row["expected_answerable"]) for row in qa_rows) == {
        ("en", True): 32,
        ("en", False): 64,
        ("hi", True): 32,
        ("hi", False): 64,
        ("hinglish", True): 32,
        ("hinglish", False): 64,
    }
    assert Counter((row["language"], row["expected_label"]) for row in nli_rows) == {
        ("en", "entailment"): 8,
        ("en", "contradiction"): 16,
        ("en", "neutral"): 8,
        ("hi", "entailment"): 8,
        ("hi", "contradiction"): 16,
        ("hi", "neutral"): 8,
        ("hinglish", "entailment"): 8,
        ("hinglish", "contradiction"): 16,
        ("hinglish", "neutral"): 8,
    }


def test_new_questions_do_not_overlap_retired_v4_or_method_v2() -> None:
    payload = cases.build_payload()
    harness._assert_no_retired_query_overlap(payload)


def test_candidate_contracts_are_pinned_safe_and_zero_training() -> None:
    by_key = {row["key"]: row for row in harness.QA_CANDIDATES}
    assert set(by_key) == {
        "xlm_roberta_base_squad2",
        "mdeberta_v3_base_squad2",
    }
    assert by_key["xlm_roberta_base_squad2"]["model_id"] == (
        "deepset/xlm-roberta-base-squad2"
    )
    assert by_key["xlm_roberta_base_squad2"]["revision"] == (
        "a5fab9908c8d856e8c583fd41ba6d92444e46477"
    )
    assert by_key["mdeberta_v3_base_squad2"]["model_id"] == (
        "timpal0l/mdeberta-v3-base-squad2"
    )
    assert by_key["mdeberta_v3_base_squad2"]["revision"] == (
        "08d6e89c7a6557f967db2e1021f7f640483400ed"
    )

    assert harness.NLI_CANDIDATE["model_id"] == (
        "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
    )
    assert harness.NLI_CANDIDATE["revision"] == (
        "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
    )


def _perfect_qa_predictions():
    predictions = []
    for row in cases.build_payload()["qa_cases"]:
        predictions.append(
            harness.QAPrediction(
                case_id=row["case_id"],
                language=row["language"],
                kind=row["kind"],
                expected_answerable=row["expected_answerable"],
                expected_answer=row["expected_answer"],
                answer=row["expected_answer"],
                score=1.0,
            )
        )
    return predictions


def _perfect_nli_predictions():
    predictions = []
    for row in cases.build_payload()["nli_cases"]:
        predictions.append(
            harness.NLIPrediction(
                case_id=row["case_id"],
                language=row["language"],
                kind=row["kind"],
                expected_label=row["expected_label"],
                predicted_label=row["expected_label"],
            )
        )
    return predictions


def test_perfect_qa_predictions_pass() -> None:
    summary = harness.summarize_qa(_perfect_qa_predictions())
    assert summary["passes_development_gate"] is True
    assert summary["unauthorized_release_cases"] == 0
    assert summary["wrong_evidence_release_cases"] == 0
    assert summary["answerable_recall"] == 1.0
    assert summary["null_recall"] == 1.0


def test_one_nonempty_null_answer_fails_qa_gate() -> None:
    rows = _perfect_qa_predictions()
    index = next(index for index, row in enumerate(rows) if not row.expected_answerable)
    row = rows[index]
    rows[index] = harness.QAPrediction(
        case_id=row.case_id,
        language=row.language,
        kind=row.kind,
        expected_answerable=False,
        expected_answer="",
        answer="mosaic-4",
        score=0.99,
    )
    summary = harness.summarize_qa(rows)
    assert summary["passes_development_gate"] is False
    assert summary["unauthorized_release_cases"] == 1
    assert summary["continuation_checks"]["zero_unauthorized_releases"] is False


def test_one_wrong_nonempty_answer_fails_qa_gate() -> None:
    rows = _perfect_qa_predictions()
    index = next(index for index, row in enumerate(rows) if row.expected_answerable)
    row = rows[index]
    rows[index] = harness.QAPrediction(
        case_id=row.case_id,
        language=row.language,
        kind=row.kind,
        expected_answerable=True,
        expected_answer=row.expected_answer,
        answer="wrong-value",
        score=0.99,
    )
    summary = harness.summarize_qa(rows)
    assert summary["passes_development_gate"] is False
    assert summary["wrong_evidence_release_cases"] == 1


def test_answer_normalization_only_ignores_boundary_punctuation() -> None:
    assert harness._normalized_answer("  Mosaic-4. ") == "mosaic-4"
    assert harness._normalized_answer("mosaic-4") == "mosaic-4"
    assert harness._normalized_answer("mosaic 4") != "mosaic-4"


def test_perfect_nli_predictions_pass() -> None:
    summary = harness.summarize_nli(_perfect_nli_predictions())
    assert summary["passes_development_gate"] is True
    assert summary["unauthorized_boolean_release_cases"] == 0
    assert summary["wrong_boolean_verdict_cases"] == 0
    assert summary["comparison_recall"] == 1.0


def test_unknown_nli_case_cannot_release_yes_or_no() -> None:
    rows = _perfect_nli_predictions()
    index = next(
        index for index, row in enumerate(rows) if row.expected_label == "neutral"
    )
    row = rows[index]
    rows[index] = harness.NLIPrediction(
        case_id=row.case_id,
        language=row.language,
        kind=row.kind,
        expected_label="neutral",
        predicted_label="entailment",
    )
    summary = harness.summarize_nli(rows)
    assert summary["passes_development_gate"] is False
    assert summary["unauthorized_boolean_release_cases"] == 1


def test_wrong_boolean_verdict_fails_even_when_not_neutral() -> None:
    rows = _perfect_nli_predictions()
    index = next(
        index for index, row in enumerate(rows) if row.expected_label == "entailment"
    )
    row = rows[index]
    rows[index] = harness.NLIPrediction(
        case_id=row.case_id,
        language=row.language,
        kind=row.kind,
        expected_label="entailment",
        predicted_label="contradiction",
    )
    summary = harness.summarize_nli(rows)
    assert summary["passes_development_gate"] is False
    assert summary["wrong_boolean_verdict_cases"] == 1


def test_qa_selection_uses_only_passing_candidates() -> None:
    result_a = {
        "key": "a",
        "summary": {
            "passes_development_gate": False,
            "unauthorized_release_cases": 0,
            "wrong_evidence_release_cases": 0,
            "answerable_recall": 1.0,
            "by_language": {
                language: {"answerable_recall": 1.0}
                for language in cases.LANGUAGES
            },
        },
        "resources": {
            "inference_ms_per_case": 1.0,
            "cuda_delta_peak_allocated_bytes": 1,
        },
    }
    result_b = {
        "key": "b",
        "summary": {
            "passes_development_gate": True,
            "unauthorized_release_cases": 0,
            "wrong_evidence_release_cases": 0,
            "answerable_recall": 0.95,
            "by_language": {
                language: {"answerable_recall": 0.95}
                for language in cases.LANGUAGES
            },
        },
        "resources": {
            "inference_ms_per_case": 2.0,
            "cuda_delta_peak_allocated_bytes": 2,
        },
    }

    assert harness.select_qa_candidate([result_a, result_b]) == "b"
