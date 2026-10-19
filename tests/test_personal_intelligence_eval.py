"""PI-1A: tests are offline, fictional, and intentionally do not call a model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.memory.personal_eval import (
    EXPECTED_CASE_IDS,
    PersonalEvalContractError,
    corpus_manifest,
    load_corpus,
    validate_paired_annotations,
)

FIXTURES = Path(__file__).parent / "fixtures" / "personal_intelligence"
CASES = FIXTURES / "pi1a_cases.json"
GOLD = FIXTURES / "pi1a_gold.json"


def test_frozen_fictional_suite_has_20_independent_multi_session_cases() -> None:
    cases, gold = load_corpus(CASES, GOLD)
    assert {c["case_id"] for c in cases} == EXPECTED_CASE_IDS
    assert {g["case_id"] for g in gold} == EXPECTED_CASE_IDS
    assert all(len({e["session_id"] for e in c["events"]}) >= 1 for c in cases)
    assert sum(len(c["events"]) > 1 for c in cases) >= 17
    assert all("expected_decision" not in c for c in cases)


def test_manifest_records_integrity_but_does_not_claim_model_pass() -> None:
    manifest = corpus_manifest(CASES, GOLD)
    assert manifest["cases"] == 20
    assert len(manifest["cases_sha256"]) == 64
    assert manifest["model_answer_evaluation"] == "NOT_RUN"
    assert manifest["automatic_durable_memory_capture"] == "DISABLED"


@pytest.mark.parametrize(
    ("case_id", "expected"),
    [
        ("C1", "personalize"),
        ("V2", "clarify"),
        ("H1", "abstain"),
        ("H2", "personalize"),
        ("G1", "refuse"),
        ("P2", "require_authority"),
        ("R2", "generic"),
        ("Q1", "abstain"),
    ],
)
def test_protected_scenarios_have_explicit_behavior_gold(
    case_id: str, expected: str
) -> None:
    _, gold = load_corpus(CASES, GOLD)
    target = next(item for item in gold if item["case_id"] == case_id)
    assert target["expected_decision"] == expected


def test_gold_leak_in_case_input_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_decision"] = "personalize"
    poisoned = tmp_path / "cases.json"
    poisoned.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PersonalEvalContractError, match="leaked gold"):
        load_corpus(poisoned, GOLD)


def test_invalid_evidence_reference_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    payload["gold"][0]["must_use_event_ids"] = ["nonexistent"]
    poisoned = tmp_path / "gold.json"
    poisoned.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PersonalEvalContractError, match="gold evidence"):
        load_corpus(CASES, poisoned)


def _response_rows() -> list[dict[str, object]]:
    cases, _ = load_corpus(CASES, GOLD)
    return [
        {
            "case_id": c["case_id"],
            "arm": arm,
            "answer": "Synthetic ungraded response.",
            "cited_event_ids": [],
            "review": "unreviewed",
        }
        for c in cases
        for arm in ("control", "candidate")
    ]


def test_paired_annotations_report_no_unmeasured_success(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps({"suite": "pi1a.v1", "responses": _response_rows()}),
        encoding="utf-8",
    )
    report = validate_paired_annotations(CASES, GOLD, results)
    assert report["pairs"] == 20
    assert report["annotations"] == 40
    assert report["semantic_accuracy"] == "NOT_MEASURED"
    assert report["security_approval"] == "NOT_GRANTED"


def test_incomplete_pair_cannot_be_declared_complete(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps({"suite": "pi1a.v1", "responses": _response_rows()[:-1]}),
        encoding="utf-8",
    )
    with pytest.raises(PersonalEvalContractError, match="paired response"):
        validate_paired_annotations(CASES, GOLD, results)


def test_self_reported_citations_cannot_reference_nonexistent_sources(
    tmp_path: Path,
) -> None:
    rows = _response_rows()
    rows[0]["cited_event_ids"] = ["nonexistent"]
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"suite": "pi1a.v1", "responses": rows}))
    with pytest.raises(PersonalEvalContractError, match="source"):
        validate_paired_annotations(CASES, GOLD, results)
