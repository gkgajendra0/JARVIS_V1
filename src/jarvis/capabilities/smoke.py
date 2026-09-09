"""Owner-machine read-only smoke for capability discovery."""

from __future__ import annotations

import json

from .discovery import CapabilityResolver
from .windows_sources import WinAppCliSchemaSource, WindowsOdrSource


def main() -> int:
    resolver = CapabilityResolver(
        (
            WinAppCliSchemaSource(),
            WindowsOdrSource(),
        )
    )
    catalog = resolver.refresh()

    payload = {
        "operation": "capability_discovery_smoke",
        "execution_attempted": False,
        "source_count": len(catalog.sources),
        "capability_count": len(catalog.capabilities),
        "sources": [
            {
                "source_id": source.source_id,
                "state": source.state.value,
                "reason": source.reason,
                "elapsed_ms": round(source.elapsed_ms, 1),
                "capability_count": len(source.capabilities),
            }
            for source in catalog.sources
        ],
        "capabilities": [
            {
                "key": capability.key,
                "kind": capability.kind.value,
                "name": capability.name,
                "operations": list(capability.operations),
                "execution_enabled": capability.execution_enabled,
            }
            for capability in catalog.capabilities
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
