from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
SCRIPT = RESEARCH / "step4_phase45d_composite_memory_gate_diagnostic.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

spec = importlib.util.spec_from_file_location("phase45d_composite_memory_gate", SCRIPT)
assert spec is not None
assert spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

LANGUAGES = ("en", "hi", "hinglish")
SEMANTIC_ABSTAINS = (
    "absent",
    "near_miss",
    "ambiguous",
    "adversarial_lexical",
    "negation",
    "unsupported_source",
)
SECURITY = ("historical", "forgotten", "local_only", "secret", "untrusted")


def _artifacts():
    planner_cases = []
    zero_cases = []
    counter = 0

    for language in LANGUAGES:
        for index in range(3):
            counter += 1
            case_id = f"release_direct_{counter:02d}"
            memory_id = f"memory_{case_id}"
            row = {
                "case_id": case_id,
                "target_label": "release",
                "language": language,
                "category": "direct" if language == "en" else "cross_lingual",
                "expected_memory_id": memory_id,
                "final_disposition": "release",
                "released_memory_id": memory_id,
            }
            planner_cases.append(row)
            zero_cases.append(
                {
                    "case_id": case_id,
                    "language": language,
                    "category": row["category"],
                    "expected_allow": True,
                    "guard_allow": True,
                }
            )

        counter += 1
        case_id = f"release_relation_{counter:02d}"
        memory_id = f"memory_{case_id}"
        planner_cases.append(
            {
                "case_id": case_id,
                "target_label": "release",
                "language": language,
                "category": "relation_mismatch",
                "expected_memory_id": memory_id,
                "final_disposition": "release",
                "released_memory_id": memory_id,
            }
        )
        zero_cases.append(
            {
                "case_id": case_id,
                "language": language,
                "category": "relation_mismatch",
                "expected_allow": True,
                "guard_allow": True,
            }
        )

    for category in SEMANTIC_ABSTAINS:
        for language in LANGUAGES:
            counter += 1
            case_id = f"abstain_{category}_{language}"
            planner_cases.append(
                {
                    "case_id": case_id,
                    "target_label": "abstain",
                    "language": language,
                    "category": category,
                    "expected_memory_id": None,
                    "final_disposition": "abstain",
                    "released_memory_id": None,
                }
            )
            zero_cases.append(
                {
                    "case_id": case_id,
                    "language": language,
                    "category": category,
                    "expected_allow": False,
                    "guard_allow": False,
                }
            )

    for category in SECURITY:
        for language in LANGUAGES:
            counter += 1
            case_id = f"security_{category}_{language}"
            planner_cases.append(
                {
                    "case_id": case_id,
                    "target_label": "abstain",
                    "language": language,
                    "category": category,
                    "expected_memory_id": None,
                    "final_disposition": "abstain",
                    "released_memory_id": None,
                }
            )

    assert len(planner_cases) == 45
    assert len(zero_cases) == 30
    planner = {
        "status": module.PLANNER_STATUS,
        "acceptance_evidence": False,
        "cases": planner_cases,
    }
    zero = {
        "status": module.ZERO_SHOT_STATUS,
        "acceptance_evidence": False,
        "cases": zero_cases,
    }
    return planner, zero


def test_perfect_composite_passes_all_gates() -> None:
    planner, zero = _artifacts()
    planner_cases, zero_cases = module.validate_inputs(planner, zero)
    results = module.compose(planner_cases, zero_cases)
    summary = module.summarize(results)

    assert summary["cases"] == 45
    assert summary["exact_target_releases"] == 12
    assert summary["false_release_cases"] == 0
    assert summary["direct_exact_releases"] == 9
    assert summary["relation_comparison_exact_releases"] == 3
    assert summary["promising_for_fresh_acceptance_design"] is True
    assert all(summary["continuation_checks"].values())


def test_complementary_errors_fail_closed() -> None:
    planner, zero = _artifacts()
    planner_by_id = {row["case_id"]: row for row in planner["cases"]}
    zero_by_id = {row["case_id"]: row for row in zero["cases"]}

    leaked_categories = {
        "near_miss",
        "adversarial_lexical",
        "negation",
        "unsupported_source",
    }
    leaked = []
    for row in planner["cases"]:
        if row["category"] in leaked_categories and len(leaked) < 6:
            row["final_disposition"] = "release"
            row["released_memory_id"] = f"wrong_{row['case_id']}"
            leaked.append(row["case_id"])
    assert len(leaked) == 6

    absent_rows = [row for row in zero["cases"] if row["category"] == "absent"]
    absent_rows[1]["guard_allow"] = True
    absent_rows[2]["guard_allow"] = True

    planner_cases, zero_cases = module.validate_inputs(planner, zero)
    results = module.compose(planner_cases, zero_cases)
    summary = module.summarize(results)

    assert summary["planner_release_cases"] == 18
    assert summary["composite_release_cases"] == 12
    assert summary["false_release_cases"] == 0
    assert set(summary["vetoed_planner_release_case_ids"]) == set(leaked)
    assert summary["promising_for_fresh_acceptance_design"] is True
    assert planner_by_id[absent_rows[1]["case_id"]]["final_disposition"] == "abstain"
    assert zero_by_id[absent_rows[1]["case_id"]]["guard_allow"] is True


def test_zero_shot_cannot_create_release_from_planner_abstain() -> None:
    planner, zero = _artifacts()
    target = next(row for row in planner["cases"] if row["target_label"] == "release")
    target["final_disposition"] = "abstain"
    target["released_memory_id"] = None

    planner_cases, zero_cases = module.validate_inputs(planner, zero)
    results = module.compose(planner_cases, zero_cases)
    result = next(row for row in results if row.case_id == target["case_id"])

    assert result.zero_shot_guard_allow is True
    assert result.planner_release is False
    assert result.composite_release is False


def test_security_release_fails_composite_gate() -> None:
    planner, zero = _artifacts()
    target = next(row for row in planner["cases"] if row["category"] == "historical")
    target["final_disposition"] = "release"
    target["released_memory_id"] = "forbidden_history"

    planner_cases, zero_cases = module.validate_inputs(planner, zero)
    summary = module.summarize(module.compose(planner_cases, zero_cases))

    assert summary["security_boundary_release_case_ids"] == [target["case_id"]]
    assert summary["continuation_checks"]["zero_security_boundary_releases"] is False
    assert summary["promising_for_fresh_acceptance_design"] is False


def test_mismatched_semantic_case_ids_fail_closed() -> None:
    planner, zero = _artifacts()
    zero["cases"][0]["case_id"] = "unknown_case"

    try:
        module.validate_inputs(planner, zero)
    except RuntimeError as exc:
        assert "exactly match" in str(exc)
    else:
        raise AssertionError("mismatched artifact IDs must fail closed")
