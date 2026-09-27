from __future__ import annotations

from types import SimpleNamespace

from jarvis.engineering_knowledge.retrieval import (
    EngineeringKnowledgeRetrievalIndex,
    EngineeringKnowledgeRetrievalPolicy,
)
from jarvis.incident_repair import (
    IncidentEvidencePackager,
    IncidentKnowledgeRetriever,
)
from jarvis.incidents.models import IncidentRecord


class RecordingIndex(EngineeringKnowledgeRetrievalIndex):
    def __init__(self) -> None:
        self.calls = []

    def retrieve(self, query_text, **kwargs):
        self.calls.append((query_text, kwargs))
        return (
            SimpleNamespace(revision=SimpleNamespace(revision_id="knowledge-r1")),
            SimpleNamespace(revision=SimpleNamespace(revision_id="knowledge-r2")),
        )


def test_incident_knowledge_retrieval_uses_sanitized_package_and_component_context() -> (
    None
):
    incident = IncidentRecord.create(
        title="routing failure",
        symptom="provider cooldown state became stale",
        affected_components=("model_routing",),
        now_epoch=100.0,
    )
    package = IncidentEvidencePackager().build(
        incident=incident,
        source_revision="a" * 40,
        trigger_digest="b" * 64,
        now_epoch=101.0,
    )
    index = RecordingIndex()
    retriever = IncidentKnowledgeRetriever(index, limit=2)

    revision_ids = retriever.retrieve_revision_ids(package, now_epoch=102.0)

    assert revision_ids == ("knowledge-r1", "knowledge-r2")
    assert len(index.calls) == 1
    query, kwargs = index.calls[0]
    assert "routing failure" in query
    context = kwargs["context"]
    assert len(context.facts) == 1
    assert context.facts[0].target_namespace == "jarvis.component"
    assert context.facts[0].target_identity == "model_routing"
    assert kwargs["encoder"] is None
    assert isinstance(kwargs["policy"], EngineeringKnowledgeRetrievalPolicy)
    assert kwargs["limit"] == 2


def test_incident_knowledge_retrieval_requires_component_context() -> None:
    incident = IncidentRecord.create(
        title="unknown issue",
        symptom="no component attribution",
        affected_components=(),
        now_epoch=100.0,
    )
    package = IncidentEvidencePackager().build(
        incident=incident,
        source_revision="a" * 40,
        trigger_digest="b" * 64,
        now_epoch=101.0,
    )
    index = RecordingIndex()
    retriever = IncidentKnowledgeRetriever(index)

    assert retriever.retrieve_revision_ids(package, now_epoch=102.0) == ()
    assert index.calls == []
