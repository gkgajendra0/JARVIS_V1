"""Default reviewed EngineeringKnowledge registrations."""

from __future__ import annotations

from jarvis.engineering_knowledge.registry import EngineeringKnowledgeFacetRegistry
from jarvis.engineering_knowledge.repair_facets import RepairFindingV1Handler


def build_default_facet_registry() -> EngineeringKnowledgeFacetRegistry:
    registry = EngineeringKnowledgeFacetRegistry()
    registry.register(RepairFindingV1Handler())
    return registry
