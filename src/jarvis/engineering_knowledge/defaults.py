"""Default reviewed EngineeringKnowledge registrations."""

from __future__ import annotations

from jarvis.engineering_knowledge.registry import EngineeringKnowledgeFacetRegistry
from jarvis.engineering_knowledge.repair_facets import RepairFindingV1Handler
from jarvis.engineering_learning.facets import (
    EngineeringCompatibilityV1Handler,
    EngineeringOutcomeV1Handler,
    EngineeringRegressionV1Handler,
)


def build_default_facet_registry() -> EngineeringKnowledgeFacetRegistry:
    registry = EngineeringKnowledgeFacetRegistry()
    registry.register(RepairFindingV1Handler())
    registry.register(EngineeringOutcomeV1Handler())
    registry.register(EngineeringRegressionV1Handler())
    registry.register(EngineeringCompatibilityV1Handler())
    return registry
