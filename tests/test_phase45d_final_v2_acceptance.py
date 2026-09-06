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
RETIRED_64 = RESEARCH / "step4_phase45d_abstention_cases.json"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    inserted = str(RESEARCH)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)
    old_cases = _load(
        "step4_phase45d_final_cases",
        RESEARCH / "step4_phase45d_final_cases.py",
    )
    _load(
        "step4_phase45d_feature_gate_diagnostic",
        RESEARCH / "step4_phase45d_feature_gate_diagnostic.py",
    )
    _load(
        "step4_phase45d_abstention_calibration",
        RESEARCH / "step4_phase45d_abstention_calibration.py",
    )
    _load(
        "step4_phase45d_independent_verifier_bakeoff",
        RESEARCH / "step4_phase45d_independent_verifier_bakeoff.py",
    )
    v2_cases = _load(
        "step4_phase45d_final_v2_cases",
        RESEARCH / "step4_phase45d_final_v2_cases.py",
    )
    harness = _load(
        "step4_phase45d_final_v2_acceptance",
        RESEARCH / "step4_phase45d_final_v2_acceptance.py",
    )
    return old_cases, v2_cases, harness


def test_v2_corpus_is_fresh_fixed_powered_and_multilingual() -> None:
    old_cases, cases, _ = _modules()
    payload = cases.build_payload()

    assert len(payload["queries"]) == 1800
    counts = Counter((item["split"], item["label"]) for item in payload["queries"])
    assert counts == {
        ("calibration", "release"): 600,
        ("calibration", "abstain"): 600,
        ("validation", "release"): 300,
        ("validation", "abstain"): 300,
    }

    validation_positive_languages = Counter(
        item["language"]
        for item in payload["queries"]
        if item["split"] == "validation" and item["label"] == "release"
    )
    assert validation_positive_languages == {"en": 100, "hi": 100, "hinglish": 100}

    for split, expected in (("calibration", 50), ("validation", 25)):
        categories = Counter(
            item["category"]
            for item in payload["queries"]
            if item["split"] == split and item["label"] == "abstain"
        )
        assert categories == {
            category: expected for category in cases.ABSTAIN_CATEGORIES
        }

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
    texts = [item["query"].strip().casefold() for item in payload["queries"]]
    assert len(ids) == len(set(ids))
    assert len(texts) == len(set(texts))

    old_320 = {
        item["query"].strip().casefold()
        for item in old_cases.build_payload()["queries"]
    }
    old_64_payload = json.loads(RETIRED_64.read_text(encoding="utf-8"))
    old_64 = {
        item["query"].strip().casefold()
        for item in old_64_payload["queries"]
    }
    assert not (set(texts) & old_320)
    assert not (set(texts) & old_64)

    assert cases.payload_sha256(payload) == cases.payload_sha256(cases.build_payload())


def test_v2_frozen_model_and_statistical_contracts() -> None:
    _, _, harness = _modules()

    assert harness.TARGET_PRECISION == 0.95
    assert harness.CONFIDENCE_LEVEL == 0.95
    assert harness.MIN_VALIDATION_RELEASE_RECALL == 0.40
    assert harness.MIN_VALIDATION_LANGUAGE_RELEASE_RECALL == 0.25
    assert harness.REQUIRE_ZERO_VALIDATION_FALSE_RELEASES is True

    assert harness.VERIFIER_MODEL_ID == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    assert (
        harness.VERIFIER_MODEL_REVISION
        == "1427fd652930e4ba29e8149678df786c240d8825"
    )
    assert harness.VERIFIER_MAX_LENGTH == 512
    assert harness.VERIFIER_BATCH_SIZE == 32

    assert harness.FEATURE_NAMES == (
        "rerank_score",
        "rerank_margin",
        "dense_score",
        "fused_score",
        "lexical_hit",
        "reciprocal_lexical_rank",
        "reciprocal_dense_rank",
        "independent_verifier_score",
    )
    assert harness.PREDICT_PARAMS.shape == (101, 1)
    assert np.isclose(harness.PREDICT_PARAMS[0, 0], 0.50)
    assert np.isclose(harness.PREDICT_PARAMS[-1, 0], 0.999)
    assert harness.OUTPUT_DEFAULT.name == ".step4-phase45d-final-v2-acceptance.json"


def _result(
    harness: ModuleType,
    case_id: str,
    *,
    label: str,
    language: str = "en",
    category: str = "direct",
    correct: bool = True,
    probability: float = 0.99,
) -> object:
    return harness.V2CaseResult(
        case_id=case_id,
        split="validation",
        label=label,
        expected_memory_id="expected" if label == "release" else None,
        language=language,
        category=category,
        top_memory_id="expected" if correct else "wrong",
        top_document="synthetic",
        positive_top1_correct=label == "release" and correct,
        positive_hit_at_3=label == "release" and correct,
        rerank_score=8.0,
        rerank_margin=7.0,
        dense_score=0.8,
        lexical_rank=1,
        dense_rank=1,
        fused_score=0.03,
        independent_verifier_score=5.0,
        confidence_probability=probability,
        query_embedding_ms=1.0,
        retrieval_ms=1.0,
        rerank_ms=1.0,
    )


def test_wrong_top1_and_security_release_are_hard_false_releases() -> None:
    _, _, harness = _modules()
    cases = [
        _result(harness, "good", label="release", correct=True),
        _result(harness, "wrong", label="release", correct=False),
        _result(
            harness,
            "local",
            label="abstain",
            category="local_only",
            correct=False,
        ),
    ]

    metrics = harness._metrics(cases, 0.90)

    assert metrics["tp"] == 1
    assert metrics["fp"] == 2
    assert metrics["false_release_case_ids"] == ["wrong", "local"]
    assert metrics["security_boundary_release_case_ids"] == ["local"]


def test_acceptance_fails_closed_on_false_release_and_language_starvation() -> None:
    _, _, harness = _modules()
    validation = []
    for language in ("en", "hi", "hinglish"):
        for index in range(4):
            validation.append(
                _result(
                    harness,
                    f"{language}-positive-{index}",
                    label="release",
                    language=language,
                    probability=0.99 if language != "hi" else 0.10,
                )
            )
        validation.append(
            _result(
                harness,
                f"{language}-negative",
                label="abstain",
                language=language,
                category="absent",
                correct=False,
                probability=0.99 if language == "en" else 0.10,
            )
        )

    acceptance = harness._acceptance(validation, 0.90)

    assert acceptance["checks"]["validation_zero_false_releases"] is False
    assert acceptance["checks"]["validation_language_release_recall"] is False
    assert acceptance["pass"] is False


def test_probability_release_predict_is_one_dimensional_threshold_gate() -> None:
    _, _, harness = _modules()
    values = np.asarray([[0.49], [0.50], [0.90], [0.999]])
    predicted = harness._probability_release_predict(values, 0.50)
    assert predicted.tolist() == [0, 1, 1, 1]
