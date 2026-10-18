"""Step 9 tests: offline benchmark integrity, evidence, rankings, abstention."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from jarvis.memory.research_semantic_pressure import (
    BY_ID,
    CASES,
    CONCEPTS,
    DISTRACTOR_COUNT,
    DOCUMENT_COUNT,
    FACTS,
    TARGET_COUNT,
    BM25Index,
    PressureFailure,
    build_archive,
    fuse,
    inspect_archive,
    metadata,
    offline_report,
    score_rankings,
    validate_recall,
)

EXPECTED_IDS = {fact.assertion.assertion_id for fact in FACTS}


def _empty() -> dict[str, tuple[str, ...]]:
    return {case.case_id: () for case in CASES}


def _all_empty():
    return {engine: _empty() for engine in ("hindsight", "lexical", "hybrid")}


def test_fixed_corpus_is_240_entirely_fictional_source_linked_assertions():
    assert len(CONCEPTS) == TARGET_COUNT == 16
    assert DISTRACTOR_COUNT == 208
    assert len(FACTS) == len(BY_ID) == len(EXPECTED_IDS) == DOCUMENT_COUNT == 240
    assert all(ident.startswith("synthetic-") for ident in BY_ID)
    assert all(fact.assertion.source_ref.startswith("conversation:synthetic:")
               for fact in FACTS)
    assert not any("owner" in fact.text.casefold() for fact in FACTS)


def test_research_aliases_not_in_original_or_corrected_memory_content():
    for i, concept in enumerate(CONCEPTS):
        subject = f"synthetic-exhibit-{i:03d}"
        fact1 = BY_ID[f"{subject}-site-v1"]
        fact2 = BY_ID[f"{subject}-site-v2"]
        corpus_words = set((fact1.text + " " + fact2.text).lower().split())
        assert concept.alias not in corpus_words
        assert fact1.assertion.supersedes_id is None
        assert fact2.assertion.supersedes_id == fact1.assertion.assertion_id


def test_fixed_cases_have_three_semantic_styles_and_direct_controls():
    assert len(CASES) == 68
    assert len({case.case_id for case in CASES}) == 68
    assert sum(c.category.startswith("semantic_") for c in CASES) == 48
    assert sum(c.category == "exact_descriptor_control" for c in CASES) == 16
    assert sum(c.expected is None and c.subject is None for c in CASES) == 2
    assert sum(c.expected is None and c.subject is not None for c in CASES) == 2
    for case in CASES:
        if case.expected is not None:
            assert len(case.required_ids) == 2
            assert all(i in BY_ID for i in case.required_ids)


def test_archive_deterministic_portable_and_exact_fictional_content():
    data = build_archive()
    assert data == build_archive()
    report = inspect_archive(data)
    assert report["documents"] == DOCUMENT_COUNT
    assert report["upload_authorized"] is False
    assert len(report["sha256"]) == 64
    with zipfile.ZipFile(io.BytesIO(data)) as zip_file:
        assert len(zip_file.infolist()) == DOCUMENT_COUNT + 1
        assert all(item.create_system == 0 for item in zip_file.infolist())
        assert all(item.compress_type == zipfile.ZIP_STORED
                   for item in zip_file.infolist())
    with pytest.raises(PressureFailure, match="unrecognized_fictional_archive"):
        inspect_archive(data + b"appended")


def test_validated_provenance_rejects_modified_sources_and_duplicates():
    example = FACTS[0]
    ident = example.assertion.assertion_id
    good = {
        "type": "world",
        "text": example.text,
        "document_id": f"jarvis-dev-only-{ident}",
        "metadata": metadata(example),
    }
    assert validate_recall({"results": [good]}) == (ident,)
    with pytest.raises(PressureFailure, match="source_mismatch"):
        validate_recall({"results": [{**good, "text": "substituted"}]})
    with pytest.raises(PressureFailure, match="duplicate_evidence"):
        validate_recall({"results": [good, good]})
    with pytest.raises(PressureFailure, match="unknown_assertion"):
        validate_recall({"results": [{**good, "metadata": {"assertion_id": "owner"}}]})
    with pytest.raises(PressureFailure, match="invalid_recall_schema"):
        validate_recall({"results": "invalid"})


def test_bm25_same_query_is_deterministic_and_text_only():
    index = BM25Index()
    query = CASES[0].query
    assert index.retrieve(query) == index.retrieve(query)
    assert all(ident in BY_ID for ident in index.retrieve(query))
    for case in CASES:
        assert index.retrieve(case.query) == index.retrieve(case.query)
    with pytest.raises(PressureFailure, match="invalid_query"):
        index.retrieve("")
    with pytest.raises(PressureFailure, match="invalid_lexical_corpus"):
        BM25Index(())


def test_empty_engine_abstains_on_supported_queries_instead_of_guessing():
    report = score_rankings(_all_empty(), k=8)
    assert report["engines"]["hindsight"]["supported_retrieval"] == 0
    assert report["engines"]["lexical"]["decisions_correct"] == 4
    assert report["engines"]["hybrid"]["decisions_correct"] == 4
    assert report["automatic_entity_resolution_tested"] is False


def test_oracle_evidence_proves_scorer_not_a_mock_engine_result():
    # These are explicit test-only gold assertion IDs, never a retrieval run.
    oracle = {c.case_id: c.required_ids for c in CASES}
    result = score_rankings(
        {"hindsight": oracle, "lexical": oracle, "hybrid": oracle}, k=8
    )
    for engine in result["engines"].values():
        assert engine["supported_retrieval"] == 64
        assert engine["decisions_correct"] == 68


def test_partial_correction_history_cannot_count_as_current_truth():
    oracle = {c.case_id: c.required_ids for c in CASES}
    case = next(c for c in CASES if c.category == "semantic_current")
    oracle = {**oracle, case.case_id: (case.required_ids[-1],)}
    scored = score_rankings(
        {"hindsight": oracle, "lexical": oracle, "hybrid": oracle}, k=8
    )
    for engine in scored["engines"].values():
        assert engine["supported_retrieval"] == 63
        assert engine["decisions_correct"] == 67


@pytest.mark.parametrize("top_k", (0, 2, 9, True))
def test_rank_cutoff_rejects_unsafe_or_unreviewed_values(top_k):
    with pytest.raises(PressureFailure, match="invalid_rank_cutoff"):
        score_rankings(_all_empty(), k=top_k)


def test_invalid_ranks_and_missing_engine_fail_closed():
    with pytest.raises(PressureFailure, match="missing_comparison_engines"):
        score_rankings({"lexical": _empty()}, k=8)
    bad = _all_empty()
    bad["hindsight"][CASES[0].case_id] = ("synthetic-owner-data",)
    with pytest.raises(PressureFailure, match="untrusted_comparison_evidence"):
        score_rankings(bad, k=8)
    bad = _all_empty()
    bad["hindsight"][CASES[0].case_id] = (["not-hashable"],)
    with pytest.raises(PressureFailure, match="untrusted_comparison_evidence"):
        score_rankings(bad, k=8)


def test_hybrid_fusion_rank_only_no_fabricated_source_ids():
    a = tuple(BY_ID)[:8]
    b = tuple(BY_ID)[8:16]
    assert fuse(a, b) == fuse(a, b)
    assert len(fuse(a, b)) == 16
    with pytest.raises(PressureFailure, match="invalid_ranked_results"):
        fuse((a[0], a[0]), b)
    with pytest.raises(PressureFailure, match="invalid_ranked_results"):
        fuse(("unknown-id",), b)
    with pytest.raises(PressureFailure, match="invalid_ranked_results"):
        fuse((["unhashable"],), b)


def test_offline_report_does_not_forge_semantic_accuracy():
    report = offline_report()
    assert report["status"] == "pass"
    assert report["hindsight_measured"] is False
    assert report["provider_results_simulated"] is False
    assert report["archive"]["documents"] == DOCUMENT_COUNT
    assert set(report["results_by_k"]) == {"4", "8", "16"}
    for score in report["results_by_k"].values():
        assert score["decisions_required"] == 68
        assert score["supported_required"] == 64
        assert score["decisions_correct"] >= 4


def test_isolated_cli_runs_without_server_or_sdk():
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "research" / "step9_offline_semantic_pressure.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["kind"] == "STEP9_OFFLINE_ONLY"
    assert report["hindsight_measured"] is False
    assert report["archive"]["upload_authorized"] is False
