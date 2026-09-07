from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
CASES_SCRIPT = RESEARCH / "step4_phase45d_question_role_cases.py"
HARNESS_SCRIPT = RESEARCH / "step4_phase45d_question_role_bakeoff.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cases = _load("phase45d_question_role_cases_test", CASES_SCRIPT)
harness = _load("phase45d_question_role_bakeoff_test", HARNESS_SCRIPT)


def test_corpus_shape_balance_and_frozen_hash() -> None:
    payload = cases.build_payload()
    rows = payload["cases"]
    assert len(rows) == 480
    assert cases.payload_sha256(payload) == harness.FROZEN_PAYLOAD_SHA256
    assert harness.FROZEN_PAYLOAD_SHA256 == (
        "bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21"
    )
    assert Counter(row["role"] for row in rows) == {role: 48 for role in cases.ROLES}
    assert Counter(row["language"] for row in rows) == {
        "en": 160,
        "hi": 160,
        "hinglish": 160,
    }
    assert sum(bool(row["allow_current_path"]) for row in rows) == 96
    assert sum(not bool(row["allow_current_path"]) for row in rows) == 384


def test_fresh_questions_do_not_overlap_retired_corpora() -> None:
    harness._assert_no_retired_query_overlap(cases.build_payload())


def test_candidate_and_decision_contracts_are_frozen() -> None:
    by_key = {row["key"]: row for row in harness.CANDIDATES}
    assert set(by_key) == {
        "gliclass_multilang_mini",
        "gliclass_multilang_ultra",
    }
    assert by_key["gliclass_multilang_mini"] == {
        "key": "gliclass_multilang_mini",
        "model_id": "knowledgator/gliclass-multilang-mini",
        "revision": "0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b",
    }
    assert by_key["gliclass_multilang_ultra"] == {
        "key": "gliclass_multilang_ultra",
        "model_id": "knowledgator/gliclass-multilang-ultra",
        "revision": "9d6ca10258a3bddcf05b88c89cb8a8390e87e90c",
    }
    assert harness.GLICLASS_PACKAGE_VERSION == "0.1.20"
    assert harness.MAX_LENGTH == 256
    assert harness.BATCH_SIZE == 8
    assert tuple(harness.ROLE_LABELS) == cases.ROLES
    assert set(harness.LABEL_TO_ROLE.values()) == set(cases.ROLES)


def _perfect_predictions():
    return [
        harness.RolePrediction(
            case_id=str(row["case_id"]),
            language=str(row["language"]),
            expected_role=str(row["role"]),
            predicted_role=str(row["role"]),
        )
        for row in cases.build_payload()["cases"]
    ]


def test_perfect_predictions_pass() -> None:
    summary = harness.summarize(_perfect_predictions())
    assert summary["passes_development_gate"] is True
    assert summary["unsafe_false_approval_cases"] == 0
    assert summary["wrong_allow_mode_cases"] == 0
    assert summary["false_veto_cases"] == 0
    assert summary["allow_recall"] == 1.0
    assert summary["exact_role_accuracy"] == 1.0
    assert summary["macro_f1"] == 1.0


def test_one_veto_predicted_as_current_value_fails_gate() -> None:
    rows = _perfect_predictions()
    index = next(
        index
        for index, row in enumerate(rows)
        if row.expected_role == "reason_explanation"
    )
    original = rows[index]
    rows[index] = harness.RolePrediction(
        case_id=original.case_id,
        language=original.language,
        expected_role=original.expected_role,
        predicted_role="current_value",
    )
    summary = harness.summarize(rows)
    assert summary["passes_development_gate"] is False
    assert summary["unsafe_false_approval_cases"] == 1
    assert summary["continuation_checks"]["zero_unsafe_false_approvals"] is False


def test_wrong_allow_mode_fails_gate() -> None:
    rows = _perfect_predictions()
    index = next(
        index
        for index, row in enumerate(rows)
        if row.expected_role == "current_value_comparison"
    )
    original = rows[index]
    rows[index] = harness.RolePrediction(
        case_id=original.case_id,
        language=original.language,
        expected_role=original.expected_role,
        predicted_role="current_value",
    )
    summary = harness.summarize(rows)
    assert summary["passes_development_gate"] is False
    assert summary["wrong_allow_mode_cases"] == 1
    assert summary["continuation_checks"]["zero_wrong_allow_modes"] is False


def test_comparison_false_vetoes_can_fail_recall_gate() -> None:
    rows = _perfect_predictions()
    changed = 0
    for index, row in enumerate(rows):
        if row.expected_role != "current_value_comparison":
            continue
        rows[index] = harness.RolePrediction(
            case_id=row.case_id,
            language=row.language,
            expected_role=row.expected_role,
            predicted_role="reason_explanation",
        )
        changed += 1
        if changed == 5:
            break
    summary = harness.summarize(rows)
    assert summary["passes_development_gate"] is False
    assert summary["by_role"]["current_value_comparison"]["recall"] < 0.90


def _candidate_result(
    key: str,
    *,
    passes: bool,
    unsafe: int = 0,
    wrong_mode: int = 0,
    allow_recall: float = 1.0,
    exact_accuracy: float = 1.0,
    macro_f1: float = 1.0,
    latency: float = 1.0,
    cuda: int = 1,
):
    return {
        "key": key,
        "status": "COMPLETE",
        "summary": {
            "passes_development_gate": passes,
            "unsafe_false_approval_cases": unsafe,
            "wrong_allow_mode_cases": wrong_mode,
            "allow_recall": allow_recall,
            "exact_role_accuracy": exact_accuracy,
            "macro_f1": macro_f1,
            "by_language": {
                language: {"allow_recall": allow_recall} for language in cases.LANGUAGES
            },
        },
        "resources": {
            "inference_ms_per_case": latency,
            "cuda_delta_peak_allocated_bytes": cuda,
        },
    }


def test_selection_uses_only_passing_candidates() -> None:
    failed = _candidate_result("failed", passes=False, latency=0.1)
    passing = _candidate_result("passing", passes=True, latency=5.0)
    assert harness.select_candidate([failed, passing]) == "passing"


def test_resource_rejection_is_never_selected() -> None:
    rejected = {
        "key": "rejected",
        "status": "RESOURCE_REJECTED",
        "summary": {"passes_development_gate": False},
        "resources": {
            "inference_ms_per_case": float("inf"),
            "cuda_delta_peak_allocated_bytes": float("inf"),
        },
    }
    assert harness.select_candidate([rejected]) is None
