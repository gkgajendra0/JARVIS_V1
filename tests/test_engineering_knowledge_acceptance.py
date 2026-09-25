from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from jarvis.engineering_knowledge.acceptance import (
    _DEFAULT_LIVE_WAIT_SECONDS,
    AcceptanceStatus,
    _accept_security_and_extensibility,
    _repair_attempt_diagnostic,
)
from jarvis.engineering_knowledge.acceptance_fixture import (
    QREL_PATH,
    FixtureQrelRetriever,
    seed_qrel_fixture,
)
from jarvis.engineering_knowledge.evaluation import (
    EngineeringKnowledgeEvaluationHarness,
    load_engineering_knowledge_qrels,
)
from jarvis.engineering_knowledge.retrieval import EngineeringKnowledgeRetrievalIndex
from jarvis.incidents import SqliteIncidentStore
from jarvis.memory.embeddings import QWEN3_EMBEDDING_CONTRACT


class _SameVectorEncoder:
    contract = QWEN3_EMBEDDING_CONTRACT

    def encode_query(self, text: str) -> np.ndarray:
        del text
        vector = np.zeros(self.contract.dimension, dtype=np.float32)
        vector[0] = 1.0
        return vector

    def encode_documents(self, texts: tuple[str, ...]) -> tuple[np.ndarray, ...]:
        vector = np.zeros(self.contract.dimension, dtype=np.float32)
        vector[0] = 1.0
        return tuple(vector.copy() for _ in texts)


def _run_fixture(path: Path, *, encoder=None):
    fixture = seed_qrel_fixture(path)
    corpus = load_engineering_knowledge_qrels(QREL_PATH)
    index = EngineeringKnowledgeRetrievalIndex(path)
    index.rebuild_accepted(
        encoder=encoder,
        now_epoch=1_800_000_000.0,
    )
    retriever = FixtureQrelRetriever(
        index,
        fixture,
        encoder=encoder,
        now_epoch=1_800_000_000.0,
    )
    try:
        return EngineeringKnowledgeEvaluationHarness(retriever).run(corpus, k=5)
    finally:
        index.close()


def test_phase2j_fixture_lexical_path_passes_zero_tolerance_safety(tmp_path) -> None:
    report = _run_fixture(tmp_path / "fixture.sqlite3")
    corpus = load_engineering_knowledge_qrels(QREL_PATH)
    no_answer_ids = {case.query_id for case in corpus.cases if case.expect_no_answer}
    no_answer_hits = {
        observation.query_id: tuple(hit.document_key for hit in observation.ranked_hits)
        for observation in report.observations
        if observation.query_id in no_answer_ids and observation.ranked_hits
    }

    assert report.metrics.safety_gate_passed is True, no_answer_hits
    assert report.metrics.applicability_violation_count == 0
    assert report.metrics.stale_result_count == 0
    assert report.metrics.leakage_count == 0
    assert report.metrics.no_answer_false_positive_count == 0


def test_phase2j_fixture_blocks_dense_only_no_answer_overreach(tmp_path) -> None:
    report = _run_fixture(
        tmp_path / "dense-overreach.sqlite3",
        encoder=_SameVectorEncoder(),
    )

    assert report.metrics.safety_gate_passed is True
    assert report.metrics.no_answer_false_positive_count == 0


def test_phase2j_fixture_contains_terminal_and_private_controls(tmp_path) -> None:
    path = tmp_path / "controls.sqlite3"
    fixture = seed_qrel_fixture(path)
    document_to_revision = {
        item.document_key: item.revision_id for item in fixture.documents
    }

    connection = sqlite3.connect(path)
    try:
        state = dict(
            connection.execute(
                """
                SELECT revision_id, lifecycle_state
                FROM engineering_knowledge_revision_state
                """
            ).fetchall()
        )
        sensitivity = dict(
            connection.execute(
                """
                SELECT revision_id, sensitivity
                FROM engineering_knowledge_revision
                """
            ).fetchall()
        )
    finally:
        connection.close()

    assert state[document_to_revision["repair.runtime_voice.exit.stale"]] == "retired"
    assert (
        state[document_to_revision["repair.runtime_voice.exit.superseded"]]
        == "superseded"
    )
    assert (
        state[document_to_revision["repair.runtime_voice.exit.refuted"]] == "rejected"
    )
    assert (
        sensitivity[document_to_revision["repair.runtime_voice.private_local"]]
        == "private"
    )


def test_phase2j_security_and_open_facet_checks_pass() -> None:
    checks = []

    _accept_security_and_extensibility(checks)

    assert checks
    assert all(check.status is AcceptanceStatus.PASS for check in checks)
    assert {check.check_id for check in checks} == {
        "poisoning-and-secret-gates",
        "open-ended-facet-extensibility",
    }



def test_phase2j_live_observer_spans_full_bounded_recovery_budget() -> None:
    # Production permits three attempts, each of which may consume the 120s
    # startup-readiness timeout before the supervisor can conclude it failed.
    assert _DEFAULT_LIVE_WAIT_SECONDS >= 420.0


def test_phase2j_repair_attempt_diagnostic_reports_terminal_evidence(tmp_path) -> None:
    path = tmp_path / "diagnostic.sqlite3"
    seed_qrel_fixture(path)
    store = SqliteIncidentStore(path)
    try:
        attempts = store.list_repair_attempts_for_component(
            "runtime.voice",
            limit=20,
        )
        assert attempts
        diagnostic = _repair_attempt_diagnostic(attempts[-1])
    finally:
        store.close()

    assert diagnostic["attempt_id"] == attempts[-1].attempt_id
    assert diagnostic["finished_at_epoch"] is not None
    assert diagnostic["verdict"] == "recovered"
    assert diagnostic["verification_status"] == "pass"
    assert diagnostic["verification_summary"] == "acceptance_fixture_verified"
