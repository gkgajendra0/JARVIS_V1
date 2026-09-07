from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"
CASES_SCRIPT = RESEARCH / "step4_phase45d_final_composite_cases.py"
HARNESS_SCRIPT = RESEARCH / "step4_phase45d_provider_independent_core_acceptance.py"

if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cases = _load("phase45d_provider_independent_cases_test", CASES_SCRIPT)
harness = _load("phase45d_provider_independent_core_acceptance_test", HARNESS_SCRIPT)


def test_frozen_proposal_map_covers_every_query() -> None:
    payload = cases.build_payload()
    proposal_map = harness.build_frozen_proposal_map()

    assert cases.payload_sha256(payload) == harness.FROZEN_CORPUS_SHA256
    assert len(proposal_map) == 255
    assert set(proposal_map) == {str(row["query"]) for row in payload["queries"]}


def test_release_targets_point_to_expected_current_facets() -> None:
    payload = cases.build_payload()
    proposal_map = harness.build_frozen_proposal_map()
    fact_by_memory_id = {fact.memory_id: fact for fact in cases.CURRENT_FACTS}

    for row in payload["queries"]:
        if row["label"] != "release":
            continue
        fact = fact_by_memory_id[str(row["expected_memory_id"])]
        proposal = proposal_map[str(row["query"])]
        assert proposal.intent.value == "exact_fact"
        assert proposal.temporal_scope.value == "current"
        assert proposal.subject_scope == "v4_profile"
        assert proposal.subject == fact.subject
        assert proposal.predicate == fact.predicate


def test_ordinary_abstains_receive_hostile_exact_current_proposals() -> None:
    payload = cases.build_payload()
    proposal_map = harness.build_frozen_proposal_map()

    rows = [
        row
        for row in payload["queries"]
        if row["category"] in cases.ORDINARY_ABSTAIN_CATEGORIES
    ]
    assert len(rows) == 90
    for row in rows:
        proposal = proposal_map[str(row["query"])]
        assert proposal.intent.value == "exact_fact"
        assert proposal.temporal_scope.value == "current"
        assert proposal.subject_scope == "v4_profile"
        assert proposal.subject is not None
        assert proposal.predicate is not None
        assert proposal.subject_reference is not None
        assert proposal.requested_relation is not None


def test_security_proposals_preserve_authority_semantics() -> None:
    payload = cases.build_payload()
    proposal_map = harness.build_frozen_proposal_map()

    rows = [row for row in payload["queries"] if row["category"] in cases.SECURITY_CATEGORIES]
    assert len(rows) == 75
    for row in rows:
        proposal = proposal_map[str(row["query"])]
        assert proposal.intent.value == "exact_fact"
        assert proposal.subject_scope == "v4_boundary"
        if row["category"] == "historical":
            assert proposal.temporal_scope.value == "historical"
        else:
            assert proposal.temporal_scope.value == "current"


def _perfect_results():
    results = []
    for row in cases.build_payload()["queries"]:
        release = row["label"] == "release"
        expected = row["expected_memory_id"]
        results.append(
            harness.CoreAcceptanceCaseResult(
                case_id=str(row["case_id"]),
                label=str(row["label"]),
                language=str(row["language"]),
                category=str(row["category"]),
                expected_memory_id=str(expected) if expected is not None else None,
                guard_answer_type=(
                    "current_value" if release else "reason_explanation"
                ),
                guard_allow=release,
                scripted_interpreter_called=release,
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


def test_perfect_local_core_outcome_passes_without_cloud_calls() -> None:
    summary = harness._summarize(
        _perfect_results(),
        interpreter_calls=90,
        security_authority_failures=[],
    )

    assert summary["acceptance_passed"] is True
    assert summary["cloud_provider_calls"] == 0
    assert summary["false_release_cases"] == 0
    assert all(summary["continuation_checks"].values())


def test_security_authority_failure_forces_acceptance_failure() -> None:
    summary = harness._summarize(
        _perfect_results(),
        interpreter_calls=90,
        security_authority_failures=["v4_a0091"],
    )

    assert summary["acceptance_passed"] is False
    assert summary["continuation_checks"]["zero_security_authority_precheck_releases"] is False
