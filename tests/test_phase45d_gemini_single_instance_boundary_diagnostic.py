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
    _load(
        "step4_phase45d_semantic_judge_bakeoff",
        RESEARCH / "step4_phase45d_semantic_judge_bakeoff.py",
    )
    return _load(
        "step4_phase45d_gemini_single_instance_boundary_diagnostic",
        RESEARCH / "step4_phase45d_gemini_single_instance_boundary_diagnostic.py",
    )


def _source_case(
    *,
    case_id: str,
    category: str,
    language: str,
    decision: str = "release",
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "split": "validation",
        "label": "abstain",
        "category": category,
        "language": language,
        "top_memory_id": "eligible-fallback",
        "gemini_decision": decision,
    }


def _frozen_source(module: ModuleType) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for category_index, category in enumerate(module.TARGET_CATEGORIES):
        for language_index, language in enumerate(module.TARGET_LANGUAGES):
            cases.append(
                _source_case(
                    case_id=f"v2_val_a{category_index}{language_index}9",
                    category=category,
                    language=language,
                )
            )
            cases.append(
                _source_case(
                    case_id=f"v2_val_a{category_index}{language_index}1",
                    category=category,
                    language=language,
                )
            )
    return {"cases": cases}


def test_contract_is_single_instance_development_only() -> None:
    module = _module()

    assert module.TARGET_CATEGORIES == (
        "historical",
        "forgotten",
        "local_only",
        "secret",
        "untrusted",
    )
    assert module.TARGET_LANGUAGES == ("en", "hi", "hinglish")
    assert module.EXPECTED_CASE_COUNT == 15
    assert module.GEMINI_BATCH_SIZE == 1
    assert module.GEMINI_CONCURRENCY == 1
    assert module.DEFAULT_GEMINI_RPM == 12.0
    assert module.answerability.QWEN_CANDIDATE_WINDOW == 10
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-gemini-single-instance-boundary-diagnostic-v1.json"
    )


def test_selection_is_exactly_one_case_per_boundary_language_cell() -> None:
    module = _module()

    selected = module._select_boundary_cases(_frozen_source(module))

    assert len(selected) == 15
    assert len({item["case_id"] for item in selected}) == 15
    assert all(str(item["case_id"]).endswith("1") for item in selected)
    assert {(item["category"], item["language"]) for item in selected} == {
        (category, language)
        for category in module.TARGET_CATEGORIES
        for language in module.TARGET_LANGUAGES
    }


def test_selection_rejects_source_case_not_released_in_batch_120() -> None:
    module = _module()
    source = _frozen_source(module)
    cases = source["cases"]
    assert isinstance(cases, list)
    cases[0]["gemini_decision"] = "abstain"
    cases[1]["gemini_decision"] = "abstain"

    with pytest.raises(RuntimeError, match="prior batch-120 Gemini RELEASE"):
        module._select_boundary_cases(source)


def test_summary_detects_batching_flip_and_remaining_boundary_miss() -> None:
    module = _module()
    rows: list[dict[str, object]] = []
    for category in module.TARGET_CATEGORIES:
        for language in module.TARGET_LANGUAGES:
            rows.append(
                {
                    "category": category,
                    "language": language,
                    "prior_batch_decision": "release",
                    "single_instance_decision": "abstain",
                    "flipped_to_abstain": True,
                }
            )

    clean = module._summary(rows)
    assert clean["prior_batch_release"] == 15
    assert clean["single_instance_release"] == 0
    assert clean["release_to_abstain_flips"] == 15
    assert clean["batching_confound_observed"] is True
    assert clean["all_target_boundaries_abstained_single_instance"] is True

    rows[0]["single_instance_decision"] = "release"
    rows[0]["flipped_to_abstain"] = False
    miss = module._summary(rows)
    assert miss["single_instance_release"] == 1
    assert miss["release_to_abstain_flips"] == 14
    assert miss["batching_confound_observed"] is True
    assert miss["all_target_boundaries_abstained_single_instance"] is False


def test_comparison_rows_do_not_persist_query_or_memory_text() -> None:
    module = _module()
    source = [
        _source_case(
            case_id="v2_val_a0001",
            category="historical",
            language="en",
        )
    ]
    pair = module.answerability.RetrievalPair(
        case_id="v2_val_a0001",
        split="validation",
        label="abstain",
        expected_memory_id=None,
        language="en",
        category="historical",
        query="secret diagnostic query text",
        top_memory_id="eligible-fallback",
        top_document="private eligible memory text",
        positive_top1_correct=False,
        rerank_score=1.0,
        rerank_margin=0.5,
    )
    judgment = module.semantic.GeminiJudgeItem(
        index=0,
        decision="abstain",
        failure_mode="missing_or_unsupported",
    )

    row = module._comparison_rows(source, [pair], [judgment])[0]

    assert row["case_id"] == "v2_val_a0001"
    assert row["flipped_to_abstain"] is True
    assert "query" not in row
    assert "top_document" not in row
