from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
CASES_SCRIPT = RESEARCH / "step4_phase45d_final_composite_cases.py"
HARNESS_SCRIPT = RESEARCH / "step4_phase45d_final_composite_acceptance.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cases = _load("phase45d_final_composite_cases_test", CASES_SCRIPT)
harness = _load("phase45d_final_composite_acceptance_test", HARNESS_SCRIPT)


def test_fresh_corpus_shape_and_frozen_hash() -> None:
    payload = cases.build_payload()
    queries = payload["queries"]

    assert payload["schema_version"] == 4
    assert len(payload["documents"]) == 55
    assert len(queries) == 255
    assert sum(row["label"] == "release" for row in queries) == 90
    assert sum(row["label"] == "abstain" for row in queries) == 165
    assert cases.payload_sha256(payload) == harness.FROZEN_CORPUS_SHA256
    assert harness.FROZEN_CORPUS_SHA256 == (
        "69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf"
    )


def test_fresh_corpus_language_and_category_balance() -> None:
    queries = cases.build_payload()["queries"]
    release_rows = [row for row in queries if row["label"] == "release"]
    abstain_rows = [row for row in queries if row["label"] == "abstain"]

    assert Counter(row["language"] for row in release_rows) == {
        "en": 30,
        "hi": 30,
        "hinglish": 30,
    }
    assert Counter(row["category"] for row in release_rows) == {
        "direct_current": 60,
        "current_value_comparison": 30,
    }
    assert Counter((row["category"], row["language"]) for row in abstain_rows) == {
        (category, language): 5
        for category in cases.ABSTAIN_CATEGORIES
        for language in cases.LANGUAGES
    }


def test_exact_precision_bound_requires_at_least_59_all_correct_releases() -> None:
    assert harness._precision_lower_bound_all_successes(58, 0) < 0.95
    assert harness._precision_lower_bound_all_successes(59, 0) >= 0.95
    assert harness._precision_lower_bound_all_successes(90, 1) == 0.0


def _perfect_results():
    results = []
    for row in cases.build_payload()["queries"]:
        label = str(row["label"])
        expected = row["expected_memory_id"]
        release = label == "release"
        results.append(
            harness.AcceptanceCaseResult(
                case_id=str(row["case_id"]),
                label=label,
                language=str(row["language"]),
                category=str(row["category"]),
                expected_memory_id=str(expected) if expected is not None else None,
                guard_answer_type=(
                    "current_value" if release else "reason_explanation"
                ),
                guard_allow=release,
                provider_called=release,
                provider_attempts=1 if release else 0,
                final_disposition="release" if release else "abstain",
                final_reason=(
                    "unique_eligible_current_exact_fact"
                    if release
                    else "answer_type_veto_reason_explanation"
                ),
                released_memory_id=str(expected) if release else None,
                exact_expected_release=release,
            )
        )
    return results


def test_perfect_frozen_outcome_passes_all_acceptance_gates() -> None:
    summary = harness._summarize(_perfect_results(), provider_calls=90)

    assert summary["acceptance_passed"] is True
    assert summary["false_release_cases"] == 0
    assert summary["target_release_recall"] == 1.0
    assert summary["precision_one_sided_95_lower_bound"] >= 0.95
    assert all(summary["continuation_checks"].values())


def test_one_false_release_fails_acceptance() -> None:
    results = _perfect_results()
    first_abstain = next(index for index, row in enumerate(results) if row.label == "abstain")
    row = results[first_abstain]
    results[first_abstain] = harness.AcceptanceCaseResult(
        case_id=row.case_id,
        label=row.label,
        language=row.language,
        category=row.category,
        expected_memory_id=None,
        guard_answer_type="current_value",
        guard_allow=True,
        provider_called=True,
        provider_attempts=1,
        final_disposition="release",
        final_reason="unique_eligible_current_exact_fact",
        released_memory_id="wrong-memory",
        exact_expected_release=False,
    )

    summary = harness._summarize(results, provider_calls=91)

    assert summary["acceptance_passed"] is False
    assert summary["false_release_cases"] == 1
    assert summary["continuation_checks"]["zero_false_releases"] is False
    assert summary["continuation_checks"]["precision_lower_bound_at_least_0_95"] is False
