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
        "step4_phase45d_gemini_single_instance_boundary_diagnostic",
        RESEARCH / "step4_phase45d_gemini_single_instance_boundary_diagnostic.py",
    )
    return _load(
        "step4_phase45d_gemini_single_instance_coverage_diagnostic",
        RESEARCH / "step4_phase45d_gemini_single_instance_coverage_diagnostic.py",
    )


def _source(module: ModuleType) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    counter = 0
    for language in module.TARGET_LANGUAGES:
        counter += 1
        cases.append(
            {
                "case_id": f"p{counter:03d}",
                "split": "validation",
                "label": "release",
                "language": language,
                "category": "direct" if language == "en" else "cross_lingual",
                "positive_top1_correct": True,
                "gemini_decision": "release",
                "top_memory_id": f"memory-p-{language}",
            }
        )
    for category in module.ORDINARY_ABSTAIN_CATEGORIES:
        for language in module.TARGET_LANGUAGES:
            counter += 1
            cases.append(
                {
                    "case_id": f"a{counter:03d}",
                    "split": "validation",
                    "label": "abstain",
                    "language": language,
                    "category": category,
                    "positive_top1_correct": False,
                    "gemini_decision": "abstain",
                    "top_memory_id": f"memory-a-{category}-{language}",
                }
            )
    return {"cases": cases}


def _boundary_artifact(module: ModuleType) -> dict[str, object]:
    count = module.boundary.EXPECTED_CASE_COUNT
    return {
        "summary": {
            "cases": count,
            "prior_batch_release": count,
            "single_instance_release": 0,
            "single_instance_abstain": count,
            "release_to_abstain_flips": count,
            "batching_confound_observed": True,
            "all_target_boundaries_abstained_single_instance": True,
        }
    }


def test_contract_is_small_production_shape_and_development_only() -> None:
    module = _module()

    assert module.GEMINI_BATCH_SIZE == 1
    assert module.GEMINI_CONCURRENCY == 1
    assert module.DEFAULT_GEMINI_RPM == 12.0
    assert module.EXPECTED_POSITIVE_CASES == 3
    assert module.EXPECTED_ORDINARY_ABSTAIN_CASES == 21
    assert module.EXPECTED_CASE_COUNT == 24
    assert module.COMBINED_PRODUCTION_SHAPE_CELLS == 39
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-gemini-single-instance-coverage-diagnostic-v1.json"
    )


def test_selection_covers_one_positive_and_every_ordinary_cell() -> None:
    module = _module()

    selected = module._select_coverage_cases(_source(module))

    assert len(selected) == 24
    assert len({str(item["case_id"]) for item in selected}) == 24
    positives = [item for item in selected if item["label"] == "release"]
    assert {item["language"] for item in positives} == set(module.TARGET_LANGUAGES)
    abstains = [item for item in selected if item["label"] == "abstain"]
    assert {(item["category"], item["language"]) for item in abstains} == {
        (category, language)
        for category in module.ORDINARY_ABSTAIN_CATEGORIES
        for language in module.TARGET_LANGUAGES
    }


def test_selection_requires_previously_correct_batch_decisions() -> None:
    module = _module()
    source = _source(module)
    cases = source["cases"]
    assert isinstance(cases, list)
    cases[0]["gemini_decision"] = "abstain"

    try:
        module._select_coverage_cases(source)
    except RuntimeError as exc:
        assert "previously-correct validation positive" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("selection unexpectedly accepted a prior wrong decision")


def test_summary_and_decision_authorize_only_v3_design_when_all_cells_hold() -> None:
    module = _module()
    rows: list[dict[str, object]] = []
    for language in module.TARGET_LANGUAGES:
        rows.append(
            {
                "label": "release",
                "category": "direct",
                "language": language,
                "preserved_correct_decision": True,
            }
        )
    for category in module.ORDINARY_ABSTAIN_CATEGORIES:
        for language in module.TARGET_LANGUAGES:
            rows.append(
                {
                    "label": "abstain",
                    "category": category,
                    "language": language,
                    "preserved_correct_decision": True,
                }
            )

    summary = module._summary(rows)
    decision = module._decision(summary, _boundary_artifact(module))

    assert summary["cases"] == 24
    assert summary["regressions"] == 0
    assert summary["all_coverage_cells_correct_single_instance"] is True
    assert decision["combined_production_shape_cells"] == 39
    assert decision["combined_all_cells_correct"] is True
    assert decision["gemini_selected_for_v3_design"] is True
    assert decision["v3_is_acceptance_complete"] is False
    assert decision["phase45e_authorized"] is False

    rows[-1]["preserved_correct_decision"] = False
    failed_summary = module._summary(rows)
    failed_decision = module._decision(failed_summary, _boundary_artifact(module))
    assert failed_decision["gemini_selected_for_v3_design"] is False


def test_public_comparison_rows_do_not_persist_query_or_memory_text() -> None:
    module = _module()
    pair = module.answerability.RetrievalPair(
        case_id="p001",
        split="validation",
        label="release",
        expected_memory_id="memory-1",
        language="en",
        category="direct",
        query="What is the value?",
        top_memory_id="memory-1",
        top_document="The value is alpha.",
        positive_top1_correct=True,
        rerank_score=5.0,
        rerank_margin=1.0,
    )
    judgment = module.semantic.GeminiJudgeItem(
        index=0,
        decision="release",
        failure_mode="none",
    )
    source_case = {"gemini_decision": "release"}

    rows = module._comparison_rows([source_case], [pair], [judgment])

    assert rows[0]["preserved_correct_decision"] is True
    assert "query" not in rows[0]
    assert "top_document" not in rows[0]
