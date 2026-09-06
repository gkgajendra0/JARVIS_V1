from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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
    _load(
        "step4_phase45d_answerability_verifier_bakeoff",
        RESEARCH / "step4_phase45d_answerability_verifier_bakeoff.py",
    )
    _load(
        "step4_phase45d_semantic_judge_bakeoff",
        RESEARCH / "step4_phase45d_semantic_judge_bakeoff.py",
    )
    _load(
        "step4_phase45d_final_v3_cases",
        RESEARCH / "step4_phase45d_final_v3_cases.py",
    )
    return _load(
        "step4_phase45d_final_v3_acceptance",
        RESEARCH / "step4_phase45d_final_v3_acceptance.py",
    )


def _case(
    module: ModuleType,
    *,
    case_id: str,
    label: str,
    language: str = "en",
    category: str = "positive",
    top1: bool = True,
    hit10: bool = True,
    decision: str = "release",
) -> object:
    return module.V3CaseResult(
        case_id=case_id,
        split="calibration",
        label=label,
        expected_memory_id="expected" if label == "release" else None,
        language=language,
        category=category,
        top_memory_id="expected" if top1 else "other",
        positive_top1_correct=top1 if label == "release" else False,
        positive_hit_at_10=hit10 if label == "release" else False,
        rerank_score=5.0,
        rerank_margin=1.0,
        gemini_called=True,
        gemini_decision=decision,
        gemini_failure_mode="none" if decision == "release" else "other",
        query_embedding_ms=1.0,
        retrieval_ms=1.0,
        rerank_ms=1.0,
    )


def test_v3_contract_is_fixed_single_instance_and_fail_closed() -> None:
    module = _module()

    assert module.TARGET_PRECISION == 0.95
    assert module.CONFIDENCE_LEVEL == 0.95
    assert module.MIN_CALIBRATION_RELEASED_CASES == 59
    assert module.MIN_POSITIVE_RECALL_AT_10 == 0.90
    assert module.MIN_POSITIVE_TOP1_ACCURACY == 0.85
    assert module.MIN_RELEASE_RECALL == 0.40
    assert module.MIN_LANGUAGE_RELEASE_RECALL == 0.25
    assert module.QWEN_CANDIDATE_WINDOW == 10
    assert module.GEMINI_BATCH_SIZE == 1
    assert module.GEMINI_CONCURRENCY == 1
    assert module.DEFAULT_GEMINI_RPM == 12.0
    assert module.semantic.GEMINI_MODEL_ID == "gemini-3.5-flash-lite"
    assert module.OUTPUT_DEFAULT.name == ".step4-phase45d-final-v3-acceptance.json"


def test_exact_precision_control_needs_59_perfect_releases() -> None:
    module = _module()

    perfect_58 = module._precision_control({"tp": 58, "fp": 0, "released_cases": 58})
    perfect_59 = module._precision_control({"tp": 59, "fp": 0, "released_cases": 59})

    assert perfect_58["minimum_releases_met"] is False
    assert perfect_58["passes"] is False
    assert perfect_59["minimum_releases_met"] is True
    assert perfect_59["lower_bound"] >= 0.95
    assert perfect_59["passes"] is True


def test_exact_precision_control_rejects_insufficient_lower_bound() -> None:
    module = _module()

    result = module._precision_control({"tp": 92, "fp": 1, "released_cases": 93})
    assert result["minimum_releases_met"] is True
    assert result["lower_bound"] >= 0.95
    assert result["passes"] is True

    failing = module._precision_control({"tp": 91, "fp": 1, "released_cases": 92})
    assert failing["lower_bound"] < 0.95
    assert failing["passes"] is False


def test_validation_zero_false_release_gate_is_strict() -> None:
    module = _module()
    cases = []
    languages = ("en", "hi", "hinglish")
    for language in languages:
        for index in range(20):
            cases.append(
                _case(
                    module,
                    case_id=f"p-{language}-{index}",
                    label="release",
                    language=language,
                )
            )
    cases.append(
        _case(
            module,
            case_id="unsafe",
            label="abstain",
            category="relation_mismatch",
            decision="release",
        )
    )

    acceptance = module._validation_acceptance(cases)
    assert acceptance["policy"]["fp"] == 1
    assert acceptance["checks"]["zero_false_releases"] is False
    assert acceptance["pass"] is False


def test_security_boundary_release_fails_calibration_even_with_high_precision() -> None:
    module = _module()
    cases = []
    for language in ("en", "hi", "hinglish"):
        for index in range(50):
            cases.append(
                _case(
                    module,
                    case_id=f"p-{language}-{index}",
                    label="release",
                    language=language,
                )
            )
    cases.append(
        _case(
            module,
            case_id="historical-release",
            label="abstain",
            category="historical",
            decision="release",
        )
    )

    acceptance = module._calibration_acceptance(cases)
    assert acceptance["precision_control"]["passes"] is True
    assert acceptance["checks"]["zero_security_boundary_releases"] is False
    assert acceptance["pass"] is False


def test_no_candidate_is_an_automatic_abstain_without_gemini() -> None:
    module = _module()
    retrieved = module.RetrievedCase(
        case_id="none",
        split="calibration",
        label="abstain",
        expected_memory_id=None,
        language="en",
        category="absent",
        query="No matching fact",
        top_memory_id=None,
        top_document=None,
        positive_top1_correct=False,
        positive_hit_at_10=False,
        rerank_score=None,
        rerank_margin=None,
        query_embedding_ms=1.0,
        retrieval_ms=1.0,
        rerank_ms=0.0,
    )

    assert retrieved.gemini_pair() is None
