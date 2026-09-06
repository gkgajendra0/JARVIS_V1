from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module() -> ModuleType:
    inserted = str(RESEARCH)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)
    _load(
        "step4_phase45d_abstention_calibration",
        RESEARCH / "step4_phase45d_abstention_calibration.py",
    )
    _load(
        "step4_phase45d_final_v2_cases",
        RESEARCH / "step4_phase45d_final_v2_cases.py",
    )
    return _load(
        "step4_phase45d_answerability_verifier_bakeoff",
        RESEARCH / "step4_phase45d_answerability_verifier_bakeoff.py",
    )


def _case(
    module: ModuleType,
    *,
    case_id: str,
    margin: float,
    label: str,
    correct: bool,
    language: str = "en",
    category: str = "direct",
) -> object:
    return module.AnswerabilityCase(
        case_id=case_id,
        split="validation",
        label=label,
        expected_memory_id="expected" if label == "release" else None,
        language=language,
        category=category,
        top_memory_id="expected" if correct else "wrong",
        positive_top1_correct=correct if label == "release" else False,
        rerank_score=1.0,
        rerank_margin=0.5,
        answerability_margin=margin,
        best_span_score=margin + 1.0,
        null_score=1.0,
        answer_char_length=4,
    )


def test_frozen_answerability_contract_is_task_matched_and_development_only() -> None:
    module = _module()

    assert module.QWEN_CANDIDATE_WINDOW == 10
    assert module.QA_MODEL_ID == "deepset/xlm-roberta-base-squad2-distilled"
    assert module.QA_MODEL_REVISION == (
        "c1bbfe57bc3335c37960a48c5628ba26d7e9e3b7"
    )
    assert module.QA_MAX_SEQUENCE_LENGTH == 384
    assert module.QA_MAX_ANSWER_LENGTH == 30
    assert module.QA_N_BEST == 20
    assert module.TARGET_PRECISION == 0.95
    assert module.MIN_VALIDATION_RELEASE_RECALL == 0.40
    assert module.MIN_VALIDATION_LANGUAGE_RELEASE_RECALL == 0.25
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-answerability-verifier-bakeoff-v1.json"
    )


def test_answerability_margin_prefers_best_legal_context_span_over_null() -> None:
    module = _module()
    start = np.array([3.0, 100.0, 2.0, 8.0, 1.0])
    end = np.array([3.0, 100.0, 1.0, 7.0, 2.0])
    context_mask = np.array([False, False, False, True, True])
    offsets = [(0, 0), (0, 0), (0, 0), (0, 5), (6, 10)]

    evidence = module._best_answerability_evidence(
        start_logits=start,
        end_logits=end,
        context_mask=context_mask,
        offsets=offsets,
        context="alpha beta",
        cls_index=0,
        n_best=2,
        max_answer_length=2,
    )

    assert evidence.null_score == 6.0
    assert evidence.best_span_score == 15.0
    assert evidence.margin == 9.0
    assert evidence.answer_text == "alpha"


def test_answerability_margin_can_favor_no_answer() -> None:
    module = _module()
    evidence = module._best_answerability_evidence(
        start_logits=np.array([8.0, 1.0, 2.0]),
        end_logits=np.array([8.0, 1.0, 2.0]),
        context_mask=np.array([False, True, True]),
        offsets=[(0, 0), (0, 4), (5, 9)],
        context="beta data",
        cls_index=0,
        n_best=2,
        max_answer_length=2,
    )

    assert evidence.null_score == 16.0
    assert evidence.best_span_score == 4.0
    assert evidence.margin == -12.0


def test_empirical_threshold_selects_highest_recall_at_precision_floor() -> None:
    module = _module()
    cases = [
        _case(module, case_id="p1", margin=10.0, label="release", correct=True),
        _case(module, case_id="p2", margin=9.0, label="release", correct=True),
        _case(module, case_id="p3", margin=8.0, label="release", correct=True),
        _case(module, case_id="p4", margin=7.0, label="release", correct=True),
        _case(module, case_id="n1", margin=6.0, label="abstain", correct=False),
    ]

    selected = module._select_empirical_threshold(cases, target_precision=0.95)

    assert selected is not None
    assert selected["threshold"] == 7.0
    assert selected["tp"] == 4
    assert selected["fp"] == 0
    assert selected["precision"] == 1.0
    assert selected["positive_release_recall"] == 1.0


def test_policy_metrics_penalize_wrong_positive_top1_as_unsafe() -> None:
    module = _module()
    cases = [
        _case(module, case_id="safe", margin=5.0, label="release", correct=True),
        _case(module, case_id="wrong", margin=4.0, label="release", correct=False),
        _case(module, case_id="abstain", margin=3.0, label="abstain", correct=False),
    ]

    metrics = module._policy_metrics(cases, threshold=4.0)

    assert metrics["tp"] == 1
    assert metrics["fp"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["positive_release_recall"] == 0.5
    assert metrics["false_release_case_ids"] == ["wrong"]


def test_security_boundary_release_fails_development_selection() -> None:
    module = _module()
    validation = [
        _case(
            module,
            case_id="en-safe",
            margin=10.0,
            label="release",
            correct=True,
            language="en",
        ),
        _case(
            module,
            case_id="hi-safe",
            margin=10.0,
            label="release",
            correct=True,
            language="hi",
        ),
        _case(
            module,
            case_id="hinglish-safe",
            margin=10.0,
            label="release",
            correct=True,
            language="hinglish",
        ),
        _case(
            module,
            case_id="boundary",
            margin=10.0,
            label="abstain",
            correct=False,
            language="en",
            category="untrusted",
        ),
    ]

    selection = module._development_selection(validation, threshold=9.0)

    assert not selection["selected_for_v3_freeze"]
    assert not selection["checks"]["validation_precision"]
    assert not selection["checks"]["validation_zero_security_boundary_releases"]
