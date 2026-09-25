from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from jarvis.engineering_knowledge.acceptance import (
    AcceptanceStatus,
    _accept_security_and_extensibility,
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

    assert report.metrics.safety_gate_passed is True
    assert report.metrics.applicability_violation_count == 0
    assert report.metrics.stale_result_count == 0
    assert report.metrics.leakage_count == 0
    assert report.metrics.no_answer_false_positive_count == 0


def test_phase2j_fixture_catches_dense_no_answer_overreach(tmp_path) -> None:
    report = _run_fixture(
        tmp_path / "dense-overreach.sqlite3",
        encoder=_SameVectorEncoder(),
    )

    assert report.metrics.safety_gate_passed is False
    assert report.metrics.no_answer_false_positive_count > 0


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
