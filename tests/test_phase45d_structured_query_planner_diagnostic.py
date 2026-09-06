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
        "step4_phase45d_final_v2_cases",
        RESEARCH / "step4_phase45d_final_v2_cases.py",
    )
    return _load(
        "step4_phase45d_structured_query_planner_diagnostic",
        RESEARCH / "step4_phase45d_structured_query_planner_diagnostic.py",
    )


def test_contract_is_single_instance_development_only_without_qwen() -> None:
    module = _module()

    assert module.GEMINI_MODEL_ID == "gemini-3.5-flash-lite"
    assert module.DEFAULT_GEMINI_RPM == 12.0
    assert module.EXPECTED_CASES == 45
    assert module.EXPECTED_DIRECT_POSITIVE_CASES == 9
    assert module.EXPECTED_RELATION_COMPARISON_CASES == 3
    assert module.EXPECTED_TARGET_RELEASE_CASES == 12
    assert module.EXPECTED_TRUE_ABSTAIN_CASES == 33
    assert module.RELATION_COMPARISON_CATEGORY == "relation_mismatch"
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-structured-query-planner-diagnostic-v1.json"
    )

    source = (
        RESEARCH / "step4_phase45d_structured_query_planner_diagnostic.py"
    ).read_text(encoding="utf-8")
    assert "Qwen3EmbeddingEncoder" not in source
    assert "Qwen3RetrievalReranker" not in source


def test_selection_preserves_v2_labels_but_corrects_relation_comparison_target() -> (
    None
):
    module = _module()
    selected = module.select_diagnostic_cases(module.v2_cases.build_payload())

    assert len(selected) == 45
    assert len({item["case_id"] for item in selected}) == 45
    assert sum(item["source_v2_label"] == "release" for item in selected) == 9
    assert sum(item["source_v2_label"] == "abstain" for item in selected) == 36
    assert sum(item["target_label"] == "release" for item in selected) == 12
    assert sum(item["target_label"] == "abstain" for item in selected) == 33

    relation_cases = [
        item
        for item in selected
        if item["category"] == module.RELATION_COMPARISON_CATEGORY
    ]
    assert len(relation_cases) == 3
    assert {item["language"] for item in relation_cases} == set(module.TARGET_LANGUAGES)
    assert all(item["source_v2_label"] == "abstain" for item in relation_cases)
    assert all(item["target_label"] == "release" for item in relation_cases)
    assert all(item["diagnostic_expected_memory_id"] for item in relation_cases)


def test_relation_comparison_target_is_the_relation_actually_asked() -> None:
    module = _module()
    selected = module.select_diagnostic_cases(module.v2_cases.build_payload())
    facts = {fact.memory_id: fact for fact in module.v2_cases.CURRENT_FACTS}

    relation_cases = [
        item
        for item in selected
        if item["category"] == module.RELATION_COMPARISON_CATEGORY
    ]
    for item in relation_cases:
        expected = facts[str(item["diagnostic_expected_memory_id"])]
        query = str(item["query"])
        language = str(item["language"])
        relation = module.v2_cases.RELATIONS[expected.relation_index]
        requested_surface = {
            "en": relation.relation_en,
            "hi": relation.relation_hi,
            "hinglish": relation.relation_hinglish,
        }[language]
        assert requested_surface in query


@pytest.mark.asyncio
async def test_structured_fixture_catalog_enforces_cloud_security_boundaries(
    tmp_path: Path,
) -> None:
    module = _module()
    worker = module._connection_worker(tmp_path / "planner.db")
    lifecycle = module.MemoryLifecycleService(
        worker,
        clock=lambda: module.NOW,
        assertion_id_factory=module._id_factory("planner-test-assertion"),
        operation_id_factory=module._id_factory("planner-test-operation"),
    )
    retrieval = module.SemanticRetrievalService(worker)
    try:
        await module.populate_structured_v2(lifecycle)
        catalog = await retrieval.eligible_facet_catalog(
            eligibility=module.RetrievalEligibility.cloud_context()
        )
    finally:
        await worker.close()

    assert len(catalog.facets) == module.EXPECTED_CLOUD_FACETS
    subjects = {facet.subject for facet in catalog.facets}
    assert not any(subject.startswith("ForgottenRoute-") for subject in subjects)
    assert not any(subject.startswith("LocalDiagnostic-") for subject in subjects)
    assert not any(subject.startswith("SecretPlaceholder-") for subject in subjects)
    assert not any(subject.startswith("UntrustedClaim-") for subject in subjects)
    assert any(subject.startswith("Ledger-") for subject in subjects)


def _result_for_case(
    module: ModuleType,
    case: dict[str, object],
    *,
    force_release: bool | None = None,
    released_memory_id: str | None = None,
) -> object:
    target_release = case["target_label"] == "release"
    release = target_release if force_release is None else force_release
    expected = case.get("diagnostic_expected_memory_id")
    if release and released_memory_id is None and target_release:
        released_memory_id = str(expected)

    return module.PlannerCaseResult(
        case_id=str(case["case_id"]),
        source_v2_label=str(case["source_v2_label"]),
        target_label=str(case["target_label"]),
        language=str(case["language"]),
        category=str(case["category"]),
        expected_memory_id=str(expected) if expected is not None else None,
        proposed_intent="exact_fact" if target_release else "ambiguous",
        proposed_temporal_scope="current",
        proposed_subject_scope="v2_profile" if target_release else None,
        proposed_subject="subject" if target_release else None,
        proposed_predicate="predicate" if target_release else None,
        subject_reference_present=target_release,
        relation_reference_present=target_release,
        subject_reference_grounded=target_release,
        relation_reference_grounded=target_release,
        grounding_disposition="allow",
        grounding_reason="grounded_exact_query_references",
        query_policy_disposition=(
            "allow_current_fact" if target_release else "abstain"
        ),
        query_policy_reason=(
            "validated_current_exact_fact" if target_release else "ambiguous_query"
        ),
        final_disposition="release" if release else "abstain",
        final_reason="exact_current_fact" if release else "ambiguous_query",
        released_memory_id=released_memory_id if release else None,
        proposed_facet_matches_expected=True if target_release else None,
        request_seconds=0.1,
        request_attempts=1,
    )


def test_clean_summary_passes_frozen_continuation_gates() -> None:
    module = _module()
    selected = module.select_diagnostic_cases(module.v2_cases.build_payload())
    results = [_result_for_case(module, case) for case in selected]

    summary = module.summarize(results)

    assert summary["cases"] == 45
    assert summary["target_release_cases"] == 12
    assert summary["target_abstain_cases"] == 33
    assert summary["tp_exact_release"] == 12
    assert summary["fp_or_wrong_release"] == 0
    assert summary["direct_exact_releases"] == 9
    assert summary["relation_comparison_exact_releases"] == 3
    assert summary["precision"] == 1.0
    assert summary["target_release_recall"] == 1.0
    assert all(summary["continuation_checks"].values())
    assert summary["promising_for_larger_retired_review"] is True


def test_security_false_release_fails_closed_summary() -> None:
    module = _module()
    selected = module.select_diagnostic_cases(module.v2_cases.build_payload())
    security_case = next(
        case
        for case in selected
        if case["target_label"] == "abstain"
        and case["category"] in module.SECURITY_BOUNDARY_CATEGORIES
    )
    results = []
    for case in selected:
        if case["case_id"] == security_case["case_id"]:
            results.append(
                _result_for_case(
                    module,
                    case,
                    force_release=True,
                    released_memory_id="should-never-release",
                )
            )
        else:
            results.append(_result_for_case(module, case))

    summary = module.summarize(results)

    assert summary["fp_or_wrong_release"] == 1
    assert summary["security_boundary_release_case_ids"] == [
        str(security_case["case_id"])
    ]
    assert summary["continuation_checks"]["zero_false_releases"] is False
    assert summary["continuation_checks"]["zero_security_boundary_releases"] is False
    assert summary["promising_for_larger_retired_review"] is False


def test_public_case_does_not_persist_query_or_memory_value() -> None:
    module = _module()
    selected = module.select_diagnostic_cases(module.v2_cases.build_payload())
    result = _result_for_case(module, selected[0])

    public = module._public_case(result)
    serialized = str(public)

    assert "query" not in public
    assert "value" not in public
    assert "normalized_text" not in public
    assert "source_id" not in public
    assert "Memory check" not in serialized
