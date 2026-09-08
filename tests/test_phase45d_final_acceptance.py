from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
BASELINE_PATH = RESEARCH / "step4_phase45d_abstention_calibration.py"
FINAL_CASES_PATH = RESEARCH / "step4_phase45d_final_cases.py"
FINAL_HARNESS_PATH = RESEARCH / "step4_phase45d_final_acceptance.py"
RETIRED_CASES_PATH = RESEARCH / "step4_phase45d_abstention_cases.json"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_final_modules() -> tuple[ModuleType, ModuleType]:
    load_module("step4_phase45d_abstention_calibration", BASELINE_PATH)
    cases = load_module("step4_phase45d_final_cases", FINAL_CASES_PATH)
    harness = load_module("step4_phase45d_final_acceptance", FINAL_HARNESS_PATH)
    return cases, harness


def result(
    harness: ModuleType,
    case_id: str,
    *,
    split: str = "validation",
    label: str,
    language: str = "en",
    correct: bool,
    score: float,
    margin: float,
):
    return harness.FinalCaseResult(
        case_id=case_id,
        split=split,
        label=label,
        expected_memory_id="expected" if label == "release" else None,
        language=language,
        category="test",
        top_memory_id="expected" if correct else "wrong",
        positive_top1_correct=label == "release" and correct,
        positive_hit_at_3=label == "release" and correct,
        rerank_score=score,
        rerank_margin=margin,
        dense_score=0.8,
        lexical_rank=1,
        dense_rank=1,
        fused_score=0.03,
        query_embedding_ms=1.0,
        retrieval_ms=1.0,
        rerank_ms=1.0,
    )


def test_fresh_final_corpus_is_fixed_balanced_multilingual_and_v1_disjoint() -> None:
    cases, _ = load_final_modules()
    payload = cases.build_payload()

    assert len(payload["queries"]) == 320
    counts = Counter((item["split"], item["label"]) for item in payload["queries"])
    assert counts == {
        ("calibration", "release"): 96,
        ("calibration", "abstain"): 96,
        ("validation", "release"): 64,
        ("validation", "abstain"): 64,
    }

    for split in ("calibration", "validation"):
        languages = {
            item["language"] for item in payload["queries"] if item["split"] == split
        }
        assert languages == {"en", "hi", "hinglish"}

    modes = {item["mode"] for item in payload["documents"]}
    assert {
        "current",
        "historical_transition",
        "forgotten",
        "local_only",
        "secret",
        "untrusted",
    } <= modes

    ids = [item["case_id"] for item in payload["queries"]]
    assert len(ids) == len(set(ids))
    queries = [item["query"].strip().casefold() for item in payload["queries"]]
    assert len(queries) == len(set(queries))

    retired = json.loads(RETIRED_CASES_PATH.read_text(encoding="utf-8"))
    retired_queries = {item["query"].strip().casefold() for item in retired["queries"]}
    assert not (set(queries) & retired_queries)

    assert cases.payload_sha256(payload) == cases.payload_sha256(cases.build_payload())


def test_final_policy_grid_is_pre_registered_and_small() -> None:
    _, harness = load_final_modules()

    assert harness.TARGET_PRECISION == 0.95
    assert harness.CONFIDENCE_LEVEL == 0.95
    assert harness.PREDICT_PARAMS.shape == (30, 2)
    assert set(harness.PREDICT_PARAMS[:, 0]) == {-2.0, 0.0, 2.0, 4.0, 6.0, 8.0}
    assert set(harness.PREDICT_PARAMS[:, 1]) == {0.0, 4.0, 8.0, 12.0, 16.0}


def test_release_predict_requires_both_score_and_margin() -> None:
    _, harness = load_final_modules()
    values = np.asarray(
        [
            [6.0, 8.0],
            [5.9, 8.0],
            [6.0, 7.9],
            [9.0, 12.0],
        ]
    )

    predicted = harness._release_predict(values, 6.0, 8.0)

    assert predicted.tolist() == [1, 0, 0, 1]


def test_wrong_top1_release_is_counted_as_false_release() -> None:
    _, harness = load_final_modules()
    values = [
        result(harness, "good", label="release", correct=True, score=8.0, margin=8.0),
        result(harness, "wrong", label="release", correct=False, score=9.0, margin=9.0),
        result(
            harness,
            "absent",
            label="abstain",
            correct=False,
            score=-3.0,
            margin=1.0,
        ),
    ]

    metrics = harness._policy_metrics(values, (6.0, 4.0))

    assert metrics["tp"] == 1
    assert metrics["fp"] == 1
    assert metrics["false_release_case_ids"] == ["wrong"]
    assert metrics["positive_release_recall"] == 0.5


def test_acceptance_fails_closed_on_false_release_or_language_starvation() -> None:
    _, harness = load_final_modules()
    validation = []
    for language in ("en", "hi", "hinglish"):
        validation.extend(
            [
                result(
                    harness,
                    f"{language}-good-1",
                    label="release",
                    language=language,
                    correct=True,
                    score=1.0 if language == "hi" else 8.0,
                    margin=1.0 if language == "hi" else 8.0,
                ),
                result(
                    harness,
                    f"{language}-good-2",
                    label="release",
                    language=language,
                    correct=True,
                    score=1.0 if language == "hi" else 8.0,
                    margin=1.0 if language == "hi" else 8.0,
                ),
                result(
                    harness,
                    f"{language}-abstain",
                    label="abstain",
                    language=language,
                    correct=False,
                    score=9.0 if language == "en" else -2.0,
                    margin=9.0 if language == "en" else 1.0,
                ),
            ]
        )

    acceptance = harness._acceptance_checks(validation, (6.0, 4.0))

    assert acceptance["checks"]["validation_zero_false_releases"] is False
    assert acceptance["checks"]["validation_language_release_recall"] is False
    assert acceptance["pass"] is False
