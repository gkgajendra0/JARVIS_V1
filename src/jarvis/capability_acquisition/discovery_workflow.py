"""Phase-9 bounded local discovery actions."""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.capability_acquisition.workflow import AcquisitionWorkContextResolver
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DiscoveryScope
from jarvis.engineering_substrate.discovery import DiscoveryBroker
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkType


class AcquisitionLocalDiscoveryExecutor:
    descriptor = BrainAction(
        name="acq_discover_local",
        description=(
            "Run one bounded registered local-service discovery scope as read-only "
            "Phase-9 evidence. Use explicit service types learned from research; "
            "wildcards, ssdp:all, subnet scans and port ranges are unavailable."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "adapter_id": {
                    "type": "string",
                    "enum": ["mdns_dns_sd.v1", "ssdp_upnp.v1"],
                },
                "protocol": {"type": "string", "enum": ["mdns", "ssdp"]},
                "service_types": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 240},
                    "minItems": 1,
                    "maxItems": 12,
                },
                "target_hints": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 160},
                    "maxItems": 12,
                },
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 0.25,
                    "maximum": 10,
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 32,
                },
            },
            "required": ["adapter_id", "protocol", "service_types"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(
        self,
        resolver: AcquisitionWorkContextResolver,
        broker: DiscoveryBroker,
    ) -> None:
        self._resolver = resolver
        self._broker = broker

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("network", "discovery")

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        adapter_id = str(parameters.get("adapter_id") or "").strip().casefold()
        protocol = str(parameters.get("protocol") or "").strip().casefold()
        service_types = tuple(
            str(item).strip().casefold()
            for item in parameters.get("service_types") or ()
            if str(item).strip()
        )
        target_hints = tuple(
            str(item).strip()
            for item in parameters.get("target_hints") or ()
            if str(item).strip()
        )
        identity = {
            "goal_digest": context.goal.digest,
            "adapter_id": adapter_id,
            "protocol": protocol,
            "service_types": list(service_types),
            "target_hints": list(target_hints),
        }
        scope = DiscoveryScope(
            scope_id="phase9:" + canonical_digest(identity)[:24],
            adapter_id=adapter_id,
            protocol=protocol,
            allowed_service_types=service_types,
            allowed_device_types=(),
            local_domain="local.",
            target_hints=target_hints,
            timeout_seconds=float(parameters.get("timeout_seconds", 5.0)),
            max_results=int(parameters.get("max_results", 16)),
        )
        observations = await asyncio.to_thread(self._broker.discover, scope)
        return {
            "scope_id": scope.scope_id,
            "scope_digest": canonical_digest(scope),
            "adapter_id": adapter_id,
            "protocol": protocol,
            "observation_count": len(observations),
            "observations": [
                {
                    "observation_id": item.observation_id,
                    "stable_identity": item.stable_identity,
                    "endpoints": list(item.endpoints),
                    "expires_at_epoch": item.expires_at_epoch,
                    "evidence_digest": item.evidence_digest,
                }
                for item in observations
            ],
            "execution_authorized": False,
        }


def build_acquisition_discovery_executors(
    resolver: AcquisitionWorkContextResolver,
    *,
    broker: DiscoveryBroker,
) -> tuple[object, ...]:
    return (AcquisitionLocalDiscoveryExecutor(resolver, broker),)
