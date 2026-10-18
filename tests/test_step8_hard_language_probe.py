"""Step 8 adversarial question-scoping and isolated fake-server tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_step7_engine_comparison import BANK, ROOT, FakeScaleTransport
from tools.research.step4_hindsight_loopback_import_probe import (
    LocalHTTPError,
    ProbeFailure,
)
from tools.research.step7_local_engine_comparison import (
    run_one_local_comparison,
)
from tools.research.step8_local_hard_language_probe import (
    capture_harder_retrieval,
    lexical_offline_score,
    main,
    verify_frozen_corpus,
)

from jarvis.memory.research_challenge_suite import (
    CHALLENGE_CASES,
    score_challenge_rankings,
)
from jarvis.memory.research_compare_fixture import (
    BY_ID,
    ComparisonFailure,
    metadata,
)

QUERY_COUNT = 24


class HardFake(FakeScaleTransport):
    def __init__(
        self,
        *,
        partial_history: bool = False,
        corrupt_provenance: bool = False,
        fail_recall: bool = False,
        fail_cleanup: bool = False,
    ) -> None:
        super().__init__(fail_cleanup=fail_cleanup)
        self.partial_history = partial_history
        self.corrupt_provenance = corrupt_provenance
        self.fail_recall = fail_recall

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if method == "POST" and path == f"{ROOT}/memories/recall":
            self.events.append((method, path))
            if self.fail_recall:
                raise LocalHTTPError(503, stage="semantic_recall")
            assert body is not None and content_type == "application/json"
            payload = json.loads(body)
            assert payload["types"] == ["world"]
            assert payload["prefer_observations"] is False
            assert payload["tags_match"] == "all_strict"
            case = next(
                case for case in CHALLENGE_CASES if case.query == payload["query"]
            )
            if case.subject is None:
                ordered = tuple(BY_ID)[:8]
            else:
                group = [
                    ident
                    for ident, fact in BY_ID.items()
                    if fact.assertion.subject == case.subject
                    and fact.assertion.predicate == case.predicate
                ]
                ordered = tuple(group) + tuple(
                    ident for ident in BY_ID if ident not in group
                )
            if self.partial_history and case.case_id == "current_0002":
                ordered = tuple(
                    ident
                    for ident in ordered
                    if ident != "synthetic-project-0002-schedule-v1"
                )
            rows = []
            for ident in ordered[:8]:
                fact = BY_ID[ident]
                rows.append(
                    {
                        "text": fact.text,
                        "type": "world",
                        "document_id": f"jarvis-dev-only-{ident}",
                        "metadata": metadata(fact),
                    }
                )
            if self.corrupt_provenance:
                rows[0]["metadata"].pop("canonical_source_ref")
            return {"results": rows}
        return super().request(method, path, body, content_type)


def test_harder_questions_are_bounded_and_honest_about_scope():
    assert len(CHALLENGE_CASES) == QUERY_COUNT
    assert len({c.case_id for c in CHALLENGE_CASES}) == QUERY_COUNT
    assert sum(c.expected_answer is not None for c in CHALLENGE_CASES) == 20
    assert sum(c.subject is None for c in CHALLENGE_CASES) == 2
    assert (
        sum(
            c.subject is not None and c.expected_answer is None for c in CHALLENGE_CASES
        )
        == 2
    )


def test_reuses_exact_owner_verified_step7_60_fact_archive():
    evidence = verify_frozen_corpus()
    assert (
        evidence["sha256"]
        == "a177886be60d7fe8a5b7a16e721c20b3977079ced6bc1360c95f8f2b37058df2"
    )
    assert evidence["documents"] == 60


def test_offline_lexical_works_without_remote_server():
    result = lexical_offline_score()
    assert result["supported_retrieval_required"] == 20
    assert 0 <= result["supported_retrieval"] <= 20
    assert result["decisions_required"] == 24
    assert result["unsupported_abstentions"] == 2
    assert result["unresolved_scope_gates"] == 2


def test_empty_retrieval_must_abstain_on_twenty_answerable_questions():
    empty = {c.case_id: () for c in CHALLENGE_CASES}
    report = score_challenge_rankings(
        {"hindsight": empty, "lexical": empty, "hybrid": empty}
    )
    for result in report["engines"].values():
        assert result["supported_retrieval"] == 0
        assert result["decisions_correct"] == 4
        assert result["unsupported_abstentions"] == 2
        assert result["unresolved_scope_gates"] == 2
    assert report["natural_language_fact_extraction_measured"] is False


def test_full_scoped_lineages_are_accepted_without_llm():
    rank = {}
    for case in CHALLENGE_CASES:
        rank[case.case_id] = case.required_ids
    report = score_challenge_rankings(
        {"hindsight": rank, "lexical": rank, "hybrid": rank}
    )
    assert report["engines"]["hindsight"]["supported_retrieval"] == 20
    assert report["engines"]["hindsight"]["decisions_correct"] == 24


def test_rejects_unknown_candidates_or_missing_engine():
    empty = {c.case_id: () for c in CHALLENGE_CASES}
    with pytest.raises(ComparisonFailure):
        score_challenge_rankings({"lexical": empty})
    invalid = {**empty, CHALLENGE_CASES[0].case_id: ("synthetic-not-approved",)}
    with pytest.raises(ComparisonFailure):
        score_challenge_rankings(
            {"hindsight": invalid, "lexical": empty, "hybrid": empty}
        )
    invalid_duplicate = {
        **empty,
        CHALLENGE_CASES[0].case_id: (
            "synthetic-project-0002-schedule-v1",
            "synthetic-project-0002-schedule-v1",
        ),
    }
    with pytest.raises(ComparisonFailure):
        score_challenge_rankings(
            {"hindsight": invalid_duplicate, "lexical": empty, "hybrid": empty}
        )


def test_actual_mock_recall_path_is_24_queries_and_one_clean_bank():
    fake = HardFake()
    report = run_one_local_comparison(
        fake,
        inspected=True,
        bank_id=BANK,
        pause=lambda _: None,
        capture=capture_harder_retrieval,
    )
    assert report["disposable_bank_cleanup_verified"] is True
    result = report["comparison"]
    assert result["hindsight_recall_requests"] == QUERY_COUNT
    assert result["engines"]["hindsight"]["supported_retrieval"] == 20
    assert result["engines"]["hindsight"]["decisions_correct"] == 24
    assert result["engines"]["hybrid"]["decisions_required"] == 24
    assert fake.deleted
    assert (
        sum(
            method == "POST" and path.endswith("/memories/recall")
            for method, path in fake.events
        )
        == 24
    )


def test_missing_source_predecessor_not_counted_as_correct_answer():
    fake = HardFake(partial_history=True)
    report = run_one_local_comparison(
        fake,
        inspected=True,
        bank_id=BANK,
        pause=lambda _: None,
        capture=capture_harder_retrieval,
    )
    result = report["comparison"]["engines"]["hindsight"]
    assert result["supported_retrieval"] == 19
    assert result["decisions_correct"] == 23
    assert fake.deleted


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"corrupt_provenance": True}, "invalid_challenge_provenance"),
        ({"fail_recall": True}, "semantic_recall_http_503"),
    ],
)
def test_recall_failure_is_fail_closed_and_cleanup_happens(options, reason):
    fake = HardFake(**options)
    with pytest.raises(ProbeFailure, match=reason):
        run_one_local_comparison(
            fake,
            inspected=True,
            bank_id=BANK,
            pause=lambda _: None,
            capture=capture_harder_retrieval,
        )
    assert fake.deleted


def test_cleanup_failure_always_blocks_success():
    fake = HardFake(fail_cleanup=True)
    with pytest.raises(ProbeFailure, match="scale_bank_cleanup_unverified"):
        run_one_local_comparison(
            fake,
            inspected=True,
            bank_id=BANK,
            pause=lambda _: None,
            capture=capture_harder_retrieval,
        )
    assert not fake.deleted


def test_invalid_callback_result_triggers_bank_cleanup():
    fake = HardFake()
    with pytest.raises(ProbeFailure, match="invalid_comparison_report"):
        run_one_local_comparison(
            fake,
            inspected=True,
            bank_id=BANK,
            pause=lambda _: None,
            capture=lambda _transport, _root: None,
        )
    assert fake.deleted


def test_default_main_never_inspects_docker(capsys, monkeypatch):
    def explode():
        raise AssertionError("preview must remain offline")

    monkeypatch.setattr(
        "tools.research.step8_local_hard_language_probe.verify_local_container",
        explode,
    )
    main([])
    preview = json.loads(capsys.readouterr().out)
    assert preview["status"] == "dry_run_zero_network_calls"
    assert preview["queries_planned"] == 24
    assert preview["documents_planned"] == 60
    assert preview["local_import_approved"] is False
    assert preview["hindsight_real_measured"] is False


def test_isolated_cli_preview_stays_network_free():
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "research" / "step8_local_hard_language_probe.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "dry_run_zero_network_calls"
    assert output["lexical_offline_only"]["decisions_required"] == 24
