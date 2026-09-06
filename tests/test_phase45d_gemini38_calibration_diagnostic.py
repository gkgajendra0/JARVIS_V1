from __future__ import annotations

import importlib.util
import json
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
    _load(
        "step4_phase45d_final_v3_cases",
        RESEARCH / "step4_phase45d_final_v3_cases.py",
    )
    _load(
        "step4_phase45d_final_v3_acceptance",
        RESEARCH / "step4_phase45d_final_v3_acceptance.py",
    )
    return _load(
        "step4_phase45d_gemini38_calibration_diagnostic",
        RESEARCH / "step4_phase45d_gemini38_calibration_diagnostic.py",
    )


def _source_payload(module: ModuleType) -> dict[str, object]:
    cases = [
        {
            "case_id": f"case-{index:03d}",
            "split": "calibration",
            "gemini_decision": "abstain",
            "safe_to_release": False,
        }
        for index in range(360)
    ]
    return {
        "status": "FAIL_CALIBRATION",
        "validation_executed": False,
        "git_sha": module.EXPECTED_V3_OWNER_SHA,
        "corpus": {"sha256": module.v3_acceptance.EXPECTED_V3_PAYLOAD_SHA256},
        "acceptance": {
            "calibration_pass": False,
            "validation_executed": False,
        },
        "calibration": {
            "acceptance": {
                "policy": {
                    "false_release_case_ids": sorted(
                        module.EXPECTED_V3_FALSE_RELEASE_IDS
                    )
                }
            }
        },
        "cases": cases,
    }


def _case(
    module: ModuleType,
    *,
    case_id: str,
    safe: bool,
    decision: str,
    category: str = "positive",
) -> object:
    return module.v3_acceptance.V3CaseResult(
        case_id=case_id,
        split="calibration",
        label="release" if safe else "abstain",
        expected_memory_id="expected" if safe else None,
        language="en",
        category=category,
        top_memory_id="expected" if safe else "other",
        positive_top1_correct=safe,
        positive_hit_at_10=safe,
        rerank_score=5.0,
        rerank_margin=1.0,
        gemini_called=True,
        gemini_decision=decision,
        gemini_failure_mode="none" if decision == "release" else "other",
        query_embedding_ms=1.0,
        retrieval_ms=1.0,
        rerank_ms=1.0,
    )


def test_gemini38_contract_changes_only_semantic_model() -> None:
    module = _module()

    assert module.GEMINI38_MODEL_ID == "gemini-3.8-flash"
    assert module.GEMINI38_THINKING_LEVEL == "medium"
    assert module.GEMINI_BATCH_SIZE == 1
    assert module.GEMINI_CONCURRENCY == 1
    assert module.DEFAULT_GEMINI_RPM == 12.0
    assert module.SOURCE_DEFAULT.name == ".step4-phase45d-final-v3-acceptance.json"
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v3-gemini38-calibration-diagnostic-v1.json"
    )
    assert module.v3_acceptance.QWEN_CANDIDATE_WINDOW == 10
    assert module.semantic.GEMINI_MODEL_ID == "gemini-3.5-flash-lite"


def test_source_loader_requires_retired_unexposed_validation(tmp_path: Path) -> None:
    module = _module()
    payload = _source_payload(module)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = module._load_v3_source(path)
    assert loaded["status"] == "FAIL_CALIBRATION"

    payload["validation_executed"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="validation must remain unexecuted"):
        module._load_v3_source(path)


def test_source_loader_requires_exact_false_release_set(tmp_path: Path) -> None:
    module = _module()
    payload = _source_payload(module)
    payload["calibration"]["acceptance"]["policy"]["false_release_case_ids"] = []
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="false-release set"):
        module._load_v3_source(path)


def test_comparison_reports_corrections_new_false_and_recall_regressions() -> None:
    module = _module()
    source = {
        "cases": [
            {
                "case_id": "old-false",
                "gemini_decision": "release",
                "safe_to_release": False,
            },
            {
                "case_id": "old-safe",
                "gemini_decision": "release",
                "safe_to_release": True,
            },
            {
                "case_id": "old-abstain",
                "gemini_decision": "abstain",
                "safe_to_release": False,
            },
        ]
    }
    current = [
        _case(module, case_id="old-false", safe=False, decision="abstain"),
        _case(module, case_id="old-safe", safe=True, decision="abstain"),
        _case(module, case_id="old-abstain", safe=False, decision="release"),
    ]

    comparison = module._comparison(source, current)
    assert comparison["corrected_prior_false_releases"] == ["old-false"]
    assert comparison["remaining_prior_false_releases"] == []
    assert comparison["new_false_releases"] == ["old-abstain"]
    assert comparison["safe_release_regressions"] == ["old-safe"]


def test_selection_requires_precision_and_zero_security_boundary_releases() -> None:
    module = _module()
    acceptance = {
        "checks": {
            "exact_precision_lower_bound": True,
            "release_recall": True,
            "language_release_recall": True,
            "zero_security_boundary_releases": True,
        }
    }
    selected = module._selection(acceptance, retrieval_reproduced=True)
    assert selected["selected_for_v4_design"] is True

    acceptance["checks"]["zero_security_boundary_releases"] = False
    rejected = module._selection(acceptance, retrieval_reproduced=True)
    assert rejected["selected_for_v4_design"] is False
