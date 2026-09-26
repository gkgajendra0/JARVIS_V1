from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.engineering_substrate.evaluation import (
    SubstrateOutcome,
    SubstrateReplayCase,
    SubstrateReplayError,
    evaluate_substrate_replay,
    load_substrate_replay_fixture,
    substrate_fixture_digest,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "phase5_substrate_replay_v1.json"


def _load():
    fixture_id, fixture_version, source_revision, cases = load_substrate_replay_fixture(
        _FIXTURE
    )
    return fixture_id, fixture_version, source_revision, cases


def test_fixture_covers_approved_phase5_matrix() -> None:
    fixture_id, version, source_revision, cases = _load()

    assert fixture_id == "phase5-substrate-replay-v1"
    assert version == 1
    assert source_revision == "phase5-secure-engineering-substrate-v1"
    assert len(cases) == 20
    assert {case.category for case in cases} == {
        "dependency",
        "provenance",
        "secret",
        "discovery",
        "sandbox",
        "hardware",
        "restart",
    }
    case_ids = {case.case_id for case in cases}
    assert {
        "clean-pypi-wheel",
        "sdist-only",
        "bad-hash",
        "missing-optional-attestation",
        "failed-attestation",
        "unregistered-private-index",
        "secret-missing",
        "secret-revoked",
        "secret-scope-mismatch",
        "discovery-empty",
        "discovery-stale",
        "discovery-out-of-scope",
        "docker-unavailable",
        "hardware-pass",
        "hardware-fail",
        "hardware-inconclusive",
        "restart-waiting-resource",
        "restart-waiting-dependency",
        "restart-waiting-owner",
        "restart-waiting-until",
    } == case_ids


def test_replay_reports_only_factual_counts_and_status() -> None:
    fixture_id, version, source_revision, cases = _load()

    report = evaluate_substrate_replay(
        fixture_id=fixture_id,
        fixture_version=version,
        source_revision=source_revision,
        cases=cases,
    )

    assert report.fixture_id == fixture_id
    assert report.fixture_version == version
    assert len(report.fixture_digest) == 64
    assert report.metrics.cases == 20
    assert report.metrics.matched_cases == 20
    assert report.metrics.mismatched_cases == 0
    assert report.metrics.security_invariant_violations == 0
    assert report.metrics.restart_cases == 4
    assert report.metrics.restart_lineage_preserved == 4
    assert report.metrics.restart_lineage_mismatches == 0
    assert report.metrics.all_cases_match is True
    assert report.metrics.security_invariants_clean is True
    assert report.metrics.restart_lineage_clean is True
    assert not hasattr(report.metrics, "score")
    assert not hasattr(report.metrics, "trust_score")


def test_fixture_digest_is_order_independent() -> None:
    fixture_id, version, source_revision, cases = _load()

    first = substrate_fixture_digest(
        fixture_id=fixture_id,
        fixture_version=version,
        source_revision=source_revision,
        cases=cases,
    )
    second = substrate_fixture_digest(
        fixture_id=fixture_id,
        fixture_version=version,
        source_revision=source_revision,
        cases=tuple(reversed(cases)),
    )

    assert first == second


def test_outcome_mismatch_is_reported_not_normalized_away() -> None:
    fixture_id, version, source_revision, cases = _load()
    changed = replace(
        cases[0],
        observed_outcome=SubstrateOutcome.POLICY_DENIED,
        observed_reason_code="unexpected_policy_denial",
    )

    report = evaluate_substrate_replay(
        fixture_id=fixture_id,
        fixture_version=version,
        source_revision=source_revision,
        cases=(changed, *cases[1:]),
    )

    assert report.metrics.mismatched_cases == 1
    assert report.metrics.mismatched_case_ids == (changed.case_id,)
    assert report.metrics.all_cases_match is False


def test_security_invariant_failure_is_visible_even_when_outcome_matches() -> None:
    fixture_id, version, source_revision, cases = _load()
    changed = replace(cases[2], security_invariant_preserved=False)

    report = evaluate_substrate_replay(
        fixture_id=fixture_id,
        fixture_version=version,
        source_revision=source_revision,
        cases=(cases[0], cases[1], changed, *cases[3:]),
    )

    assert report.metrics.mismatched_cases == 0
    assert report.metrics.security_invariant_violations == 1
    assert report.metrics.security_violation_case_ids == (changed.case_id,)
    assert report.metrics.security_invariants_clean is False


def test_restart_lineage_mismatch_is_reported_separately() -> None:
    fixture_id, version, source_revision, cases = _load()
    index = next(
        index
        for index, case in enumerate(cases)
        if case.case_id == "restart-waiting-resource"
    )
    changed = replace(cases[index], lineage_after="different-lineage")
    modified = (*cases[:index], changed, *cases[index + 1 :])

    report = evaluate_substrate_replay(
        fixture_id=fixture_id,
        fixture_version=version,
        source_revision=source_revision,
        cases=modified,
    )

    assert report.metrics.restart_lineage_mismatches == 1
    assert report.metrics.restart_lineage_mismatch_case_ids == (changed.case_id,)
    assert report.metrics.restart_lineage_clean is False


def test_restart_case_requires_both_lineage_ids() -> None:
    with pytest.raises(SubstrateReplayError, match="lineage_before"):
        SubstrateReplayCase(
            case_id="restart-invalid",
            category="restart",
            expected_outcome=SubstrateOutcome.RESUMED_SAME_LINEAGE,
            expected_reason_code="waiting_resource_restart",
            observed_outcome=SubstrateOutcome.RESUMED_SAME_LINEAGE,
            observed_reason_code="waiting_resource_restart",
            verifier_reference="fixture:restart:invalid",
            security_invariant_preserved=True,
            restart_boundary=True,
            lineage_before=None,
            lineage_after="lineage-a",
        )


def test_loader_rejects_string_boolean_coercion(tmp_path: Path) -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["security_invariant_preserved"] = "true"
    path = tmp_path / "invalid-bool.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TypeError, match="security_invariant_preserved"):
        load_substrate_replay_fixture(path)


def test_duplicate_case_ids_fail_closed() -> None:
    fixture_id, version, source_revision, cases = _load()

    with pytest.raises(SubstrateReplayError, match="case IDs"):
        evaluate_substrate_replay(
            fixture_id=fixture_id,
            fixture_version=version,
            source_revision=source_revision,
            cases=(cases[0], cases[0]),
        )
