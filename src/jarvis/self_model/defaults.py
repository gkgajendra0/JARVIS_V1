"""Baseline static Self Model for accepted JARVIS runtime components."""

from __future__ import annotations

from jarvis.self_model.models import (
    ComponentDescriptor,
    DependencyCriticality,
    DependencyDescriptor,
)
from jarvis.self_model.registry import SelfModelRegistry


def build_default_self_model() -> SelfModelRegistry:
    components = (
        ComponentDescriptor(
            component_id="runtime.voice",
            purpose="Production voice and session runtime.",
            source_paths=("src/jarvis/voice/production_runtime.py",),
            product_capabilities=("CAP-001", "CAP-002", "CAP-003"),
            health_probes=("startup_preflight", "session_lifecycle"),
        ),
        ComponentDescriptor(
            component_id="runtime.provider",
            purpose="Cloud AI provider boundary and provider resilience.",
            source_paths=(
                "src/jarvis/ai_provider.py",
                "src/jarvis/provider_resilience.py",
            ),
            product_capabilities=("CAP-048", "CAP-049"),
            health_probes=("provider_credential", "provider_session"),
        ),
        ComponentDescriptor(
            component_id="vision.base",
            purpose="Camera perception and tracking foundation.",
            source_paths=("src/jarvis/vision/service.py",),
            health_probes=("vision_capture", "vision_inference"),
        ),
        ComponentDescriptor(
            component_id="vision.pocket3",
            purpose="Pocket 3 native tracking transport and evidence.",
            source_paths=("src/jarvis/vision/native_owner_tracking.py",),
            health_probes=("pocket_ble", "pocket_wifi", "native_lock_evidence"),
        ),
        ComponentDescriptor(
            component_id="authority",
            purpose="Policy, approval, permit and security-audit boundary.",
            source_paths=("src/jarvis/authority",),
            product_capabilities=("CAP-034", "CAP-035", "CAP-036"),
            health_probes=("authority_tool_readiness", "audit_persistence"),
        ),
        ComponentDescriptor(
            component_id="capability_runtime",
            purpose="Capability discovery and governed execution runtime.",
            source_paths=("src/jarvis/capabilities/runtime.py",),
            product_capabilities=("CAP-018", "CAP-021", "CAP-022", "CAP-032"),
            health_probes=("capability_catalog",),
        ),
        ComponentDescriptor(
            component_id="hands",
            purpose="Computer, browser, file and device execution foundation.",
            source_paths=("src/jarvis/hands", "src/jarvis/computer"),
            product_capabilities=("CAP-023", "CAP-024", "CAP-025", "CAP-026"),
            health_probes=("hands_executor_availability",),
        ),
        ComponentDescriptor(
            component_id="observability",
            purpose="Operational correlation, structured events, traces and metrics.",
            source_paths=("src/jarvis/observability",),
            product_capabilities=("CAP-037", "CAP-038"),
            health_probes=("local_log_spool", "telemetry_export"),
        ),
        ComponentDescriptor(
            component_id="incidents",
            purpose="Operational incident records and engineering memory.",
            source_paths=("src/jarvis/incidents",),
            product_capabilities=("CAP-038", "CAP-046"),
            health_probes=("incident_store",),
        ),
    )
    dependencies = (
        DependencyDescriptor(
            "runtime.voice",
            "runtime.provider",
            criticality=DependencyCriticality.BLOCKING,
        ),
        DependencyDescriptor(
            "runtime.voice",
            "capability_runtime",
            criticality=DependencyCriticality.DEGRADING,
        ),
        DependencyDescriptor(
            "vision.pocket3",
            "vision.base",
            criticality=DependencyCriticality.BLOCKING,
        ),
        DependencyDescriptor(
            "capability_runtime",
            "authority",
            criticality=DependencyCriticality.BLOCKING,
        ),
        DependencyDescriptor(
            "hands",
            "capability_runtime",
            criticality=DependencyCriticality.BLOCKING,
        ),
        DependencyDescriptor(
            "incidents",
            "observability",
            criticality=DependencyCriticality.DEGRADING,
        ),
    )
    return SelfModelRegistry(components=components, dependencies=dependencies)
