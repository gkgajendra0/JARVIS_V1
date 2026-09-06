"""Development-only composite memory-gate diagnostic for Phase 4.5D."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import step4_phase45d_final_v2_cases as v2_cases

PLANNER_DEFAULT = Path(".step4-phase45d-v2-structured-query-planner-diagnostic-v1.json")
ZERO_SHOT_DEFAULT = Path(".step4-phase45d-v2-zero-shot-answer-type-diagnostic-v1.json")
OUTPUT_DEFAULT = Path(".step4-phase45d-v2-composite-memory-gate-diagnostic-v1.json")
PLANNER_STATUS = "DEVELOPMENT_STRUCTURED_QUERY_PLANNER_DIAGNOSTIC_COMPLETE"
ZERO_SHOT_STATUS = "DEVELOPMENT_ZERO_SHOT_ANSWER_TYPE_DIAGNOSTIC_COMPLETE"
RESULT_STATUS = "DEVELOPMENT_COMPOSITE_MEMORY_GATE_DIAGNOSTIC_COMPLETE"
EXPECTED_CASES = 45
EXPECTED_SEMANTIC_CASES = 30
EXPECTED_TARGET_RELEASES = 12
EXPECTED_TARGET_ABSTAINS = 33
SECURITY_CATEGORIES = frozenset(v2_cases.SECURITY_BOUNDARY_CATEGORIES)


@dataclass(frozen=True, slots=True)
class CompositeCase:
    case_id: str
    language: str
    category: str
    target_label: str
    expected_memory_id: str | None
    planner_release: bool
    zero_shot_guard_allow: bool | None
    composite_release: bool
    released_memory_id: str | None
    exact_expected_release: bool


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"required development artifact is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"artifact must contain a JSON object: {path}")
    return payload


def _case_map(payload: dict[str, Any], *, expected_count: int, name: str) -> dict[str, dict[str, Any]]:
    raw = payload.get("cases")
    if not isinstance(raw, list):
        raise TypeError(f"{name} cases must be a list")
    if len(raw) != expected_count:
        raise RuntimeError(f"{name} case count changed: {len(raw)} != {expected_count}")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError(f"{name} case rows must be objects")
        case_id = str(item.get("case_id", "")).strip()
        if not case_id:
            raise RuntimeError(f"{name} case ID is missing")
        if case_id in result:
            raise RuntimeError(f"duplicate {name} case ID: {case_id}")
        result[case_id] = item
    return result


def validate_inputs(
    planner: dict[str, Any],
    zero_shot: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if planner.get("status") != PLANNER_STATUS:
        raise RuntimeError("planner artifact status does not match the frozen diagnostic")
    if zero_shot.get("status") != ZERO_SHOT_STATUS:
        raise RuntimeError("zero-shot artifact status does not match the frozen diagnostic")
    if planner.get("acceptance_evidence") is not False:
        raise RuntimeError("planner artifact must be development-only")
    if zero_shot.get("acceptance_evidence") is not False:
        raise RuntimeError("zero-shot artifact must be development-only")

    planner_cases = _case_map(planner, expected_count=EXPECTED_CASES, name="planner")
    zero_cases = _case_map(
        zero_shot,
        expected_count=EXPECTED_SEMANTIC_CASES,
        name="zero-shot",
    )
    semantic_ids = {
        case_id
        for case_id, item in planner_cases.items()
        if str(item.get("category")) not in SECURITY_CATEGORIES
    }
    if len(semantic_ids) != EXPECTED_SEMANTIC_CASES:
        raise RuntimeError("planner semantic-current case count changed")
    if semantic_ids != set(zero_cases):
        raise RuntimeError("zero-shot case IDs must exactly match planner semantic-current IDs")

    for case_id in semantic_ids:
        planner_row = planner_cases[case_id]
        zero_row = zero_cases[case_id]
        for field in ("language", "category"):
            if str(planner_row.get(field)) != str(zero_row.get(field)):
                raise RuntimeError(f"{field} mismatch across artifacts for {case_id}")
        expected_allow = str(planner_row.get("target_label")) == "release"
        if bool(zero_row.get("expected_allow")) != expected_allow:
            raise RuntimeError(f"target-label mismatch across artifacts for {case_id}")

    return planner_cases, zero_cases


def compose(
    planner_cases: dict[str, dict[str, Any]],
    zero_cases: dict[str, dict[str, Any]],
) -> list[CompositeCase]:
    results: list[CompositeCase] = []
    for case_id in sorted(planner_cases):
        planner_row = planner_cases[case_id]
        category = str(planner_row.get("category"))
        target_label = str(planner_row.get("target_label"))
        if target_label not in {"release", "abstain"}:
            raise RuntimeError(f"invalid target label for {case_id}: {target_label}")
        planner_release = str(planner_row.get("final_disposition")) == "release"
        released_memory_id = (
            str(planner_row.get("released_memory_id"))
            if planner_row.get("released_memory_id") is not None
            else None
        )
        expected_memory_id = (
            str(planner_row.get("expected_memory_id"))
            if planner_row.get("expected_memory_id") is not None
            else None
        )

        if category in SECURITY_CATEGORIES:
            guard_allow: bool | None = None
            composite_release = planner_release
        else:
            zero_row = zero_cases[case_id]
            guard_allow = bool(zero_row.get("guard_allow"))
            composite_release = planner_release and guard_allow

        if composite_release and not planner_release:
            raise RuntimeError("composite gate must never create a new release")
        composite_memory_id = released_memory_id if composite_release else None
        exact_expected_release = (
            target_label == "release"
            and composite_release
            and expected_memory_id is not None
            and composite_memory_id == expected_memory_id
        )
        results.append(
            CompositeCase(
                case_id=case_id,
                language=str(planner_row.get("language")),
                category=category,
                target_label=target_label,
                expected_memory_id=expected_memory_id,
                planner_release=planner_release,
                zero_shot_guard_allow=guard_allow,
                composite_release=composite_release,
                released_memory_id=composite_memory_id,
                exact_expected_release=exact_expected_release,
            )
        )
    return results


def summarize(results: list[CompositeCase]) -> dict[str, Any]:
    if len(results) != EXPECTED_CASES:
        raise RuntimeError("composite result case count changed")
    target_releases = [row for row in results if row.target_label == "release"]
    target_abstains = [row for row in results if row.target_label == "abstain"]
    if len(target_releases) != EXPECTED_TARGET_RELEASES:
        raise RuntimeError("composite target-release count changed")
    if len(target_abstains) != EXPECTED_TARGET_ABSTAINS:
        raise RuntimeError("composite target-abstain count changed")

    exact_releases = [row for row in target_releases if row.exact_expected_release]
    false_releases = [row for row in target_abstains if row.composite_release]
    wrong_target_releases = [
        row
        for row in target_releases
        if row.composite_release and not row.exact_expected_release
    ]
    security_releases = [
        row
        for row in results
        if row.category in SECURITY_CATEGORIES and row.composite_release
    ]
    planner_release_rows = [row for row in results if row.planner_release]
    composite_release_rows = [row for row in results if row.composite_release]
    vetoed_planner_rows = [
        row for row in results if row.planner_release and not row.composite_release
    ]

    direct_targets = [
        row
        for row in target_releases
        if row.category in {"direct", "cross_lingual"}
    ]
    relation_targets = [
        row for row in target_releases if row.category == "relation_mismatch"
    ]
    by_language: dict[str, dict[str, int | float]] = {}
    for language in v2_cases.LANGUAGES:
        rows = [row for row in target_releases if row.language == language]
        exact = sum(row.exact_expected_release for row in rows)
        if len(rows) != 4:
            raise RuntimeError(f"expected four target releases for {language}")
        by_language[language] = {
            "target_release_cases": 4,
            "exact_releases": exact,
            "target_release_recall": round(exact / 4, 6),
        }

    continuation_checks = {
        "zero_false_releases": not false_releases and not wrong_target_releases,
        "zero_security_boundary_releases": not security_releases,
        "retain_at_least_10_of_12_target_releases": len(exact_releases) >= 10,
        "direct_exact_releases_at_least_8_of_9": sum(
            row.exact_expected_release for row in direct_targets
        )
        >= 8,
        "relation_comparison_exact_releases_at_least_2_of_3": sum(
            row.exact_expected_release for row in relation_targets
        )
        >= 2,
        "each_language_at_least_3_of_4": all(
            metrics["exact_releases"] >= 3 for metrics in by_language.values()
        ),
        "every_composite_release_is_exact_expected_memory": all(
            row.exact_expected_release for row in composite_release_rows
        ),
        "composite_is_veto_only": len(composite_release_rows) <= len(planner_release_rows)
        and all(row.planner_release for row in composite_release_rows),
        "zero_new_model_or_api_calls": True,
    }

    return {
        "cases": len(results),
        "target_release_cases": len(target_releases),
        "target_abstain_cases": len(target_abstains),
        "planner_release_cases": len(planner_release_rows),
        "composite_release_cases": len(composite_release_rows),
        "exact_target_releases": len(exact_releases),
        "false_release_cases": len(false_releases) + len(wrong_target_releases),
        "target_release_recall": round(len(exact_releases) / len(target_releases), 6),
        "direct_exact_releases": sum(
            row.exact_expected_release for row in direct_targets
        ),
        "relation_comparison_exact_releases": sum(
            row.exact_expected_release for row in relation_targets
        ),
        "by_language": by_language,
        "false_release_case_ids": [row.case_id for row in false_releases],
        "wrong_target_release_case_ids": [row.case_id for row in wrong_target_releases],
        "security_boundary_release_case_ids": [row.case_id for row in security_releases],
        "vetoed_planner_release_case_ids": [row.case_id for row in vetoed_planner_rows],
        "vetoed_planner_releases_by_category": dict(
            sorted(Counter(row.category for row in vetoed_planner_rows).items())
        ),
        "continuation_checks": continuation_checks,
        "promising_for_fresh_acceptance_design": all(continuation_checks.values()),
    }


def _public_case(row: CompositeCase) -> dict[str, Any]:
    return {
        "case_id": row.case_id,
        "language": row.language,
        "category": row.category,
        "target_label": row.target_label,
        "expected_memory_id": row.expected_memory_id,
        "planner_release": row.planner_release,
        "zero_shot_guard_allow": row.zero_shot_guard_allow,
        "composite_release": row.composite_release,
        "released_memory_id": row.released_memory_id,
        "exact_expected_release": row.exact_expected_release,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planner-artifact", default=str(PLANNER_DEFAULT))
    parser.add_argument("--zero-shot-artifact", default=str(ZERO_SHOT_DEFAULT))
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(f"refusing to overwrite existing diagnostic: {output_path}")

    planner = _load_json(Path(args.planner_artifact))
    zero_shot = _load_json(Path(args.zero_shot_artifact))
    planner_cases, zero_cases = validate_inputs(planner, zero_shot)
    results = compose(planner_cases, zero_cases)
    summary = summarize(results)

    output = {
        "status": RESULT_STATUS,
        "development_only": True,
        "acceptance_evidence": False,
        "phase45e_authorized": False,
        "inputs": {
            "planner_status": planner.get("status"),
            "zero_shot_status": zero_shot.get("status"),
        },
        "architecture": {
            "composition": "planner_release AND local_answer_type_guard_allow",
            "semantic_guard_is_veto_only": True,
            "security_boundary_owned_by_jarvis": True,
            "new_model_calls": 0,
            "new_api_calls": 0,
            "query_text_persisted": False,
            "canonical_memory_value_persisted": False,
        },
        "summary": summary,
        "cases": [_public_case(row) for row in results],
    }
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print("SUMMARY:", json.dumps(summary, ensure_ascii=False))
    print(
        "DECISION:",
        json.dumps(
            {
                "promising_for_fresh_acceptance_design": summary[
                    "promising_for_fresh_acceptance_design"
                ],
                "phase45e_authorized": False,
            }
        ),
    )


if __name__ == "__main__":
    main()
