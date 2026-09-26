"""Owner-machine acceptance for bounded read-only local discovery."""

from __future__ import annotations

import json

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.engineering_substrate.contracts import DiscoveryScope
from jarvis.engineering_substrate.discovery import (
    DiscoveryCapabilitySource,
    default_discovery_broker,
)


def run_acceptance() -> dict[str, object]:
    scope = DiscoveryScope(
        scope_id="phase5g-owner-media-discovery",
        adapter_id="mdns_dns_sd.v1",
        protocol="mdns",
        allowed_service_types=(
            "_airplay._tcp.local.",
            "_googlecast._tcp.local.",
            "_raop._tcp.local.",
        ),
        allowed_device_types=(),
        local_domain="local.",
        timeout_seconds=4,
        max_results=16,
    )
    broker = default_discovery_broker()
    source = DiscoveryCapabilitySource(broker=broker, scope=scope)
    catalog = CapabilityResolver((source,)).refresh()
    snapshot = catalog.sources[0]

    if snapshot.state.value != "available":
        raise RuntimeError(
            "bounded mDNS discovery was unavailable: "
            + str(snapshot.reason or snapshot.state.value)
        )
    if any(item.execution_enabled for item in catalog.capabilities):
        raise RuntimeError("discovery-only capability unexpectedly enabled execution")
    if any(item.operations for item in catalog.capabilities):
        raise RuntimeError("discovery-only capability unexpectedly exposed operations")

    observations = len(catalog.capabilities)
    return {
        "status": "PASS",
        "adapter_id": "mdns_dns_sd.v1",
        "adapter_version": "python-zeroconf-0.151.3",
        "service_types_attempted": 3,
        "observation_count": observations,
        "external_availability": (
            "observed" if observations else "no_matching_service_observed"
        ),
        "execution_enabled_count": 0,
    }


def main() -> int:
    try:
        result = run_acceptance()
    except (RuntimeError, ValueError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
