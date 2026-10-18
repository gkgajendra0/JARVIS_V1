"""Fail-closed, zero-network tests for Step 4 semantic retrieval rubric."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from jarvis.memory.hindsight_transfer_shadow import PINNED_FACTS
from tools.research.step4_hindsight_semantic_eval import (
    CASES,
    EvaluationFailure,
    main,
    protocol,
    recall_request,
    score_candidates,
)

_FACTS = {fact.assertion_id: fact for fact in PINNED_FACTS}


def _result(assertion_id: str) -> dict[str, Any]:
    fact = _FACTS[assertion_id]
    metadata = {
        "assertion_id": fact.assertion_id,
        "assertion_version": str(fact.version),
        "source_turn_id": fact.source_turn_id,
        "canonical_source_ref": f"conversation:synthetic:{fact.source_turn_id}",
        "predicate": fact.predicate,
        "revision_kind": fact.revision_kind,
        "source_class": "synthetic_owner_direct",
        "admission_policy": "shadow_only_no_write",
    }
    if fact.supersedes_id:
        metadata["supersedes_id"] = fact.supersedes_id
    return {
        "id": f"mock-id-{assertion_id}",
        "type": "world",
        "text": fact.text,
        "document_id": f"jarvis-dev-only-{assertion_id}",
        "metadata": metadata,
    }


def _payload(*, answers: bool = True) -> dict[str, Any]:
    rows = []
    for case in CASES:
        targets = list(case.required_ids)
        extras = [fact.assertion_id for fact in PINNED_FACTS if fact.assertion_id not in targets]
        row: dict[str, Any] = {
            "case_id": case.case_id,
            "recall": {"results": [_result(i) for i in targets + extras]},
        }
        if answers:
            row["decision"] = {
                "status": "answer" if case.answer_code is not None else "abstain",
                "answer_code": case.answer_code,
                "evidence_assertion_ids": targets,
            }
        rows.append(row)
    return {"cases": rows}


def _case(payload: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(row for row in payload["cases"] if row["case_id"] == case_id)


def test_protocol_is_nine_pinned_synthetic_cases_with_no_measured_results():
    p = protocol()
    assert p["status"] == "not_measured"
    assert p["case_count"] == 9
    assert p["answer_cases"] == 7
    assert p["abstention_cases"] == 2
    assert p["real_hindsight_results_present"] is False
    assert p["production_promotion_allowed"] is False
    assert len(set(item["case_id"] for item in p["cases"])) == 9
    for case in CASES:
        request = recall_request(case)
        assert request["types"] == ["world"]
        assert request["prefer_observations"] is False
        assert request["tags_match"] == "all_strict"
        assert request["query_timestamp"] == "2026-02-02T00:00:00Z"
        assert "http" not in json.dumps(request)


def test_perfect_mock_fixture_does_not_claim_real_server_accuracy():
    report = score_candidates(_payload())
    assert report["retrieval_gate"] == "pass"
    assert report["retrieval_pass_cases"] == 7
    assert report["decision_gate"] == "pass"
    assert report["decision_pass_cases"] == 9
    assert report["abstention_pass_cases"] == 2
    assert report["provenance_gate"] == "pass"
    assert report["real_server_accuracy_verified"] is False
    assert report["origin"] == "caller_supplied_unverified"
    assert report["production_promotion_allowed"] is False


def test_retrieval_only_cannot_pass_answer_gate():
    report = score_candidates(_payload(answers=False))
    assert report["retrieval_gate"] == "pass"
    assert report["decision_gate"] == "not_evaluated"
    assert report["decision_evaluated_cases"] == 0


def test_current_answer_must_cite_corrected_assertion_only():
    payload = _payload()
    _case(payload, "atlas_current_day")["decision"] = {
        "status": "answer",
        "answer_code": "saturday",
        "evidence_assertion_ids": ["synthetic-workshop-day-v1"],
    }
    assert score_candidates(payload)["decision_gate"] == "fail"
    payload = _payload()
    _case(payload, "atlas_current_day")["decision"]["evidence_assertion_ids"].append(
        "synthetic-workshop-day-v1"
    )
    assert score_candidates(payload)["decision_gate"] == "fail"


def test_historical_change_requires_both_provenance_lines():
    payload = _payload()
    _case(payload, "nile_historical_change")["decision"]["evidence_assertion_ids"] = [
        "synthetic-report-day-v2"
    ]
    report = score_candidates(payload)
    assert report["decision_gate"] == "fail"
    assert report["retrieval_gate"] == "pass"


def test_abstention_is_required_even_when_recall_returns_related_facts():
    payload = _payload()
    _case(payload, "unknown_start_time")["decision"] = {
        "status": "answer",
        "answer_code": "10am",
        "evidence_assertion_ids": [],
    }
    report = score_candidates(payload)
    assert report["decision_gate"] == "fail"
    assert report["abstention_pass_cases"] == 1
    assert report["retrieval_gate"] == "pass"


def test_not_all_answers_supplied_is_not_a_pass():
    payload = _payload()
    del _case(payload, "nile_previous_report_day")["decision"]
    report = score_candidates(payload)
    assert report["decision_gate"] == "fail"
    assert report["decision_evaluated_cases"] == 8


def test_retrieval_failure_is_independent_from_correct_answer_decision():
    payload = _payload()
    _case(payload, "atlas_current_day")["recall"]["results"] = [
        _result("synthetic-workshop-day-v1")
    ]
    report = score_candidates(payload)
    assert report["retrieval_gate"] == "fail"
    assert report["decision_gate"] == "fail"


def test_retrieval_target_outside_top_three_fails_ranking_gate():
    payload = _payload()
    row = _case(payload, "atlas_current_day")
    results = row["recall"]["results"]
    row["recall"]["results"] = results[1:4] + results[:1] + results[4:]
    assert score_candidates(payload)["retrieval_gate"] == "fail"


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda x: x["metadata"].pop("canonical_source_ref"), "fact_provenance_mismatch"),
        (lambda x: x["metadata"].update(assertion_version=2), "fact_provenance_mismatch"),
        (lambda x: x.update(text="Altered synthetic claim"), "fact_identity_mismatch"),
        (lambda x: x["metadata"].update(assertion_id="owner-private"), "unrecognized_assertion"),
        (lambda x: x.update(document_id="owner-document"), "fact_identity_mismatch"),
        (lambda x: x.update(type="observation"), "fact_identity_mismatch"),
    ],
)
def test_tampering_fails_closed(mutator: Any, code: str):
    payload = _payload()
    item = _case(payload, "atlas_current_day")["recall"]["results"][0]
    mutator(item)
    with pytest.raises(EvaluationFailure, match=code):
        score_candidates(payload)


def test_duplicates_and_unexpected_case_ids_fail_closed():
    payload = _payload()
    row = _case(payload, "atlas_current_day")
    row["recall"]["results"].append(deepcopy(row["recall"]["results"][0]))
    with pytest.raises(EvaluationFailure, match="unexpected_recall_volume"):
        score_candidates(payload)
    payload = _payload()
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
    with pytest.raises(EvaluationFailure, match="invalid_case_set"):
        score_candidates(payload)


def test_invalid_decision_evidence_shape_is_rejected():
    payload = _payload()
    _case(payload, "atlas_current_day")["decision"]["evidence_assertion_ids"] = [
        "synthetic-workshop-day-v2",
        "synthetic-workshop-day-v2",
    ]
    with pytest.raises(EvaluationFailure, match="invalid_decision_evidence"):
        score_candidates(payload)


def test_unexpected_input_is_never_accepted():
    for payload in (
        {},
        {"cases": [], "source": "real_server"},
        {"cases": []},
        {"cases": "owner data"},
    ):
        with pytest.raises(EvaluationFailure):
            score_candidates(payload)


def test_default_cli_prints_protocol_only(capsys: Any):
    main([])
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "not_measured"
    assert output["real_hindsight_results_present"] is False
