from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

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
    return _load(
        "step4_phase45d_semantic_judge_bakeoff",
        RESEARCH / "step4_phase45d_semantic_judge_bakeoff.py",
    )


def _pair(
    module: ModuleType,
    *,
    case_id: str,
    label: str,
    correct: bool,
    language: str = "en",
    category: str = "direct",
) -> object:
    return module.answerability.RetrievalPair(
        case_id=case_id,
        split="validation",
        label=label,
        expected_memory_id="expected" if label == "release" else None,
        language=language,
        category=category,
        query="What is the exact value?",
        top_memory_id="expected" if correct else "other",
        top_document="The exact value is alpha.",
        positive_top1_correct=correct if label == "release" else False,
        rerank_score=5.0,
        rerank_margin=1.0,
    )


def _case(
    module: ModuleType,
    *,
    case_id: str,
    margin: float,
    label: str,
    correct: bool,
    gemini: str = "release",
    language: str = "en",
    category: str = "direct",
) -> object:
    return module.SemanticJudgeCase(
        pair=_pair(
            module,
            case_id=case_id,
            label=label,
            correct=correct,
            language=language,
            category=category,
        ),
        gliclass=module.GliclassEvidence(
            release_score=(margin + 1.0) / 2.0,
            abstain_score=(1.0 - margin) / 2.0,
        ),
        gemini_decision=gemini,
        gemini_failure_mode="none" if gemini == "release" else "other",
    )


def test_semantic_judge_contract_is_pinned_and_development_only() -> None:
    module = _module()

    assert module.GLICLASS_PACKAGE_VERSION == "0.1.20"
    assert module.GLICLASS_MODEL_ID == "knowledgator/gliclass-multilang-mini"
    assert module.GLICLASS_MODEL_REVISION == (
        "c09fb5ca4cb7957044168e6bf8bcefa2e14b8dfb"
    )
    assert module.GEMINI_MODEL_ID == "gemini-3.5-flash-lite"
    assert module.answerability.QWEN_CANDIDATE_WINDOW == 10
    assert module.TARGET_PRECISION == 0.95
    assert module.MIN_VALIDATION_RELEASE_RECALL == 0.40
    assert module.MIN_VALIDATION_LANGUAGE_RELEASE_RECALL == 0.25
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-semantic-judge-bakeoff-v1.json"
    )
    assert "temporal scope" in module.GLICLASS_RELEASE_LABEL
    assert "historical state" in module.GEMINI_SYSTEM_PROMPT


def test_gliclass_margin_is_release_minus_abstain() -> None:
    module = _module()
    evidence = module.GliclassEvidence(release_score=0.8, abstain_score=0.3)
    assert evidence.margin == 0.5


def test_threshold_selection_uses_precision_then_maximizes_recall() -> None:
    module = _module()
    cases = [
        _case(module, case_id="p1", margin=0.90, label="release", correct=True),
        _case(module, case_id="p2", margin=0.80, label="release", correct=True),
        _case(module, case_id="a1", margin=0.75, label="abstain", correct=False),
        _case(module, case_id="p3", margin=0.70, label="release", correct=True),
    ]

    selected = module._select_empirical_threshold(cases)

    assert selected is not None
    assert selected["threshold"] == 0.8
    assert selected["tp"] == 2
    assert selected["fp"] == 0
    assert selected["precision"] == 1.0
    assert selected["positive_release_recall"] == 0.666667


def test_policy_metrics_track_false_and_security_boundary_releases() -> None:
    module = _module()
    cases = [
        _case(module, case_id="p1", margin=0.9, label="release", correct=True),
        _case(
            module,
            case_id="a1",
            margin=0.8,
            label="abstain",
            correct=False,
            category="relation_mismatch",
        ),
        _case(
            module,
            case_id="a2",
            margin=0.7,
            label="abstain",
            correct=False,
            language="hi",
            category="historical",
        ),
    ]

    policy = module._policy_metrics(cases, lambda case: case.gliclass.margin >= 0.7)

    assert policy["tp"] == 1
    assert policy["fp"] == 2
    assert policy["false_release_case_ids"] == ["a1", "a2"]
    assert policy["false_releases_by_category"] == {
        "historical": 1,
        "relation_mismatch": 1,
    }
    assert policy["security_boundary_release_case_ids"] == ["a2"]


def test_development_checks_require_precision_recall_languages_and_security() -> None:
    module = _module()
    calibration = {
        "precision": 0.96,
        "positive_release_recall": 0.8,
        "security_boundary_release_case_ids": [],
    }
    validation = {
        "precision": 0.96,
        "positive_release_recall": 0.5,
        "security_boundary_release_case_ids": [],
    }
    languages = {
        "en": {"positive_release_recall": 0.5},
        "hi": {"positive_release_recall": 0.3},
        "hinglish": {"positive_release_recall": 0.4},
    }

    result = module._development_checks(
        calibration_policy=calibration,
        validation_policy=validation,
        validation_languages=languages,
        decision_available=True,
    )

    assert result["promising_for_v3_design"] is True
    assert all(result["checks"].values())

    validation["security_boundary_release_case_ids"] = ["bad"]
    failed = module._development_checks(
        calibration_policy=calibration,
        validation_policy=validation,
        validation_languages=languages,
        decision_available=True,
    )
    assert failed["promising_for_v3_design"] is False
    assert failed["checks"]["validation_zero_security_boundary_releases"] is False


def test_batched_preserves_order_and_remainder() -> None:
    module = _module()
    pairs = [
        _pair(module, case_id=f"c{index}", label="abstain", correct=False)
        for index in range(10)
    ]

    batches = module._batched(pairs, 4)

    assert [len(batch) for batch in batches] == [4, 4, 2]
    assert [pair.case_id for batch in batches for pair in batch] == [
        f"c{index}" for index in range(10)
    ]


def test_public_case_does_not_persist_query_or_memory_document() -> None:
    module = _module()
    case = _case(module, case_id="p1", margin=0.4, label="release", correct=True)

    public = module._public_case(case)

    assert public["case_id"] == "p1"
    assert "query" not in public
    assert "top_document" not in public
    assert public["gliclass_margin"] == pytest.approx(0.4)
    assert public["gemini_decision"] == "release"


def test_usage_extraction_accepts_common_gemini_field_names() -> None:
    module = _module()

    class Usage:
        def model_dump(self) -> dict[str, int]:
            return {
                "prompt_token_count": 10,
                "candidates_token_count": 4,
                "total_token_count": 14,
            }

    class Response:
        usage_metadata = Usage()
        usage = None

    assert module._extract_usage(Response()) == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }
