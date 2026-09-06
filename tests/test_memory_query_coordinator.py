from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.evidence_gate import MemoryEvidenceDisposition
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.query_plan import (
    MemoryFacetCatalog,
    MemoryFacetKey,
    MemoryQueryIntent,
    MemoryQueryProposal,
    MemoryTemporalScope,
)
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 6, 16, 0, tzinfo=UTC)


class StaticInterpreter:
    provider_name = "test"
    model_name = "static"

    def __init__(self, proposal: MemoryQueryProposal) -> None:
        self.proposal = proposal
        self.catalogs: list[MemoryFacetCatalog] = []
        self.texts: list[str] = []

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal:
        self.texts.append(text)
        self.catalogs.append(catalog)
        return self.proposal


def _worker(path: Path) -> SerialConnectionWorker:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(factory, thread_name="memory-query-coordinator-test")


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _source(
    source_id: str,
    *,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"query-coordinator:{source_id}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _draft(
    *,
    subject: str,
    predicate: str,
    value: str,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="profile",
        subject=subject,
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=value,
        normalized_text=f"{subject} {predicate.replace('_', ' ')} is {value}.",
        freshness_class=FreshnessClass.STABLE,
        sensitivity=sensitivity,
    )


def _exact(
    *,
    subject: str = "Aquila",
    predicate: str = "archive_destination",
    subject_reference: str = "Aquila",
    relation_reference: str = "archive destination",
) -> MemoryQueryProposal:
    return MemoryQueryProposal(
        intent=MemoryQueryIntent.EXACT_FACT,
        subject_scope="profile",
        subject=subject,
        predicate=predicate,
        subject_reference=subject_reference,
        requested_relation=relation_reference,
        temporal_scope=MemoryTemporalScope.CURRENT,
    )


@pytest.mark.asyncio
async def test_grounded_exact_query_releases_unique_current_fact(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "release.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(_exact())
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        assertion = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                value="vault-A",
            ),
            _source("owner-source"),
        )

        decision = await coordinator.resolve(
            "Aquila ka archive destination kya hai?",
            eligibility=RetrievalEligibility.cloud_context(),
        )

        assert decision.disposition is MemoryEvidenceDisposition.RELEASE
        assert decision.evidence is not None
        assert decision.evidence.assertion.assertion_id == assertion.assertion_id
        assert decision.evidence.assertion.value == "vault-A"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_existing_wrong_predicate_conflicts_with_grounded_relation(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "wrong-predicate.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(
        _exact(
            predicate="signin_method",
            relation_reference="archive destination",
        )
    )
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                value="vault-A",
            ),
            _source("archive-source"),
        )
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="signin_method",
                value="passkey",
            ),
            _source("signin-source"),
        )

        decision = await coordinator.resolve("Aquila archive destination kya hai?")

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert (
            decision.reason_code
            == "relation_reference_conflicts_with_selected_predicate"
        )
        assert decision.evidence is None
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_existing_wrong_subject_conflicts_with_grounded_subject(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "wrong-subject.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(
        _exact(
            subject="Borealis",
            subject_reference="Aquila",
        )
    )
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        for subject, value in (("Aquila", "vault-A"), ("Borealis", "vault-B")):
            await lifecycle.create(
                _draft(
                    subject=subject,
                    predicate="archive_destination",
                    value=value,
                ),
                _source(f"{subject}-source"),
            )

        decision = await coordinator.resolve("Aquila archive destination kya hai?")

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == "subject_reference_conflicts_with_selected_subject"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_ungrounded_relation_reference_abstains_before_release(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "ungrounded.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(
        _exact(relation_reference="signin method")
    )
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                value="vault-A",
            ),
            _source("owner-source"),
        )

        decision = await coordinator.resolve("Aquila archive destination kya hai?")

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == "relation_reference_not_grounded"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_cross_lingual_grounded_relation_can_map_to_canonical_predicate(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "cross-lingual.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(
        _exact(relation_reference="संग्रह स्थान")
    )
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                value="vault-A",
            ),
            _source("owner-source"),
        )

        decision = await coordinator.resolve("Aquila का संग्रह स्थान क्या है?")

        assert decision.disposition is MemoryEvidenceDisposition.RELEASE
        assert decision.evidence is not None
        assert decision.evidence.assertion.value == "vault-A"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_cloud_interpreter_only_receives_cloud_eligible_facets(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "catalog.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(_exact())
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                value="vault-A",
            ),
            _source("standard-source"),
        )
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="local_operator_note",
                value="local-note",
                sensitivity=Sensitivity.LOCAL_ONLY,
            ),
            _source("local-source", sensitivity=Sensitivity.LOCAL_ONLY),
        )

        await coordinator.resolve(
            "Aquila archive destination kya hai?",
            eligibility=RetrievalEligibility.cloud_context(),
        )

        assert len(interpreter.catalogs) == 1
        catalog = interpreter.catalogs[0]
        assert MemoryFacetKey(
            "profile", "Aquila", "archive_destination"
        ) in catalog.facets
        assert MemoryFacetKey(
            "profile", "Aquila", "local_operator_note"
        ) not in catalog.facets
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_qualified_query_keeps_fail_closed_query_policy_reason(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "qualified.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    interpreter = StaticInterpreter(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.QUALIFIED_FACT,
            subject_scope="profile",
            subject="Aquila",
            predicate="archive_destination",
            temporal_scope=MemoryTemporalScope.CURRENT,
        )
    )
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    try:
        await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                value="vault-A",
            ),
            _source("owner-source"),
        )

        decision = await coordinator.resolve("Aquila secondary archive destination?")

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == "qualified_relation_requires_separate_path"
    finally:
        await worker.close()
