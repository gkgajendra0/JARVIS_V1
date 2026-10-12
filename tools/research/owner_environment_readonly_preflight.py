"""Read-only owner-machine environment evidence using existing reviewed adapters.

This command never probes a guessed control port, fetches arbitrary URLs,
authenticates, pairs devices, runs a control command or writes the owner store.
Observations are *not* a protocol/authorization verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

from jarvis.engineering_substrate.contracts import DiscoveryScope
from jarvis.engineering_substrate.discovery import (
    DiscoveryBroker,
    DiscoveryBrokerError,
    default_discovery_broker,
)
from jarvis.work.privacy import (
    build_default_work_payload_codec,
    default_work_payload_key_path,
)
from jarvis.work.store import default_work_store_path


def reviewed_device_scopes(
    *, include_cameras: bool = False
) -> tuple[DiscoveryScope, ...]:
    scopes = [
        DiscoveryScope(
            scope_id="owner.environment.media.mdns.v1",
            adapter_id="mdns_dns_sd.v1",
            protocol="mdns",
            allowed_service_types=(
                "_airplay._tcp.local.",
                "_googlecast._tcp.local.",
            ),
            allowed_device_types=(),
            local_domain="local.",
            timeout_seconds=2.0,
            max_results=16,
        ),
        DiscoveryScope(
            scope_id="owner.environment.media.ssdp.v1",
            adapter_id="ssdp_upnp.v1",
            protocol="ssdp",
            allowed_service_types=(
                "upnp:rootdevice",
                "urn:dial-multiscreen-org:service:dial:1",
                "urn:schemas-upnp-org:device:mediarenderer:1",
            ),
            allowed_device_types=(),
            local_domain="local.",
            timeout_seconds=2.0,
            max_results=16,
        ),
    ]
    if include_cameras:
        scopes.append(
            DiscoveryScope(
                scope_id="owner.environment.video.onvif.v1",
                adapter_id="onvif_ws_discovery.v1",
                protocol="ws_discovery",
                allowed_service_types=(),
                allowed_device_types=("network_video_transmitter",),
                local_domain="local.",
                timeout_seconds=2.0,
                max_results=16,
            )
        )
    return tuple(scopes)


def discover_read_only(
    broker: DiscoveryBroker,
    *,
    include_cameras: bool = False,
) -> list[dict[str, object]]:
    checks = []
    for scope in reviewed_device_scopes(include_cameras=include_cameras):
        try:
            observations = broker.discover(scope)
        except DiscoveryBrokerError as exc:
            checks.append(
                {
                    "adapter_id": scope.adapter_id,
                    "status": "unavailable",
                    "reason_code": type(exc).__name__,
                    "observation_count": 0,
                }
            )
            continue
        checks.append(
            {
                "adapter_id": scope.adapter_id,
                "scope_id": scope.scope_id,
                "status": "observed" if observations else "no_observations",
                "observation_count": len(observations),
                "observations": [
                    {
                        "observation_id": obs.observation_id,
                        "stable_identity": obs.stable_identity,
                        "endpoints": list(obs.endpoints),
                        "expires_at_epoch": obs.expires_at_epoch,
                        "evidence_digest": obs.evidence_digest,
                    }
                    for obs in observations
                ],
            }
        )
    return checks


def known_world_entities() -> dict[str, object]:
    """Read GICC world references without instantiating a writing WorkStore."""
    db = Path(default_work_store_path())
    if not db.is_file():
        return {"status": "not_configured", "entities": []}
    if os.name == "nt" and not default_work_payload_key_path(db).is_file():
        return {"status": "protected_key_unavailable", "entities": []}
    codec = build_default_work_payload_codec(db)
    try:
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute(
                """SELECT payload FROM world_entities_v1
                   ORDER BY entity_type, entity_id LIMIT 100"""
            ).fetchall()
    except sqlite3.OperationalError:
        return {"status": "world_registry_unavailable", "entities": []}
    entities = []
    for (raw,) in rows:
        value = json.loads(codec.decode(raw))
        if value.get("entity_type") not in {
            "media_player",
            "television",
            "camera",
            "display",
            "computer",
        }:
            continue
        entities.append(
            {
                "entity_id": value.get("entity_id"),
                "entity_type": value.get("entity_type"),
                "canonical_name": value.get("canonical_name"),
                "lifecycle_state": value.get("lifecycle_state"),
                "provenance_refs": value.get("provenance_refs", []),
            }
        )
    return {"status": "read_only", "entities": entities}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-cameras",
        action="store_true",
        help="Also perform the registered, read-only ONVIF camera discovery",
    )
    parser.add_argument(
        "--registry-only",
        action="store_true",
        help="Do not perform any network discovery",
    )
    args = parser.parse_args()

    result = {
        "schema": "owner_environment_preflight.v1",
        "collected_at_epoch": time.time(),
        "purpose": "read_only_identity_observation",
        "does_not_prove": [
            "manufacturer_or_platform",
            "protocol_compatibility",
            "authenticated_access",
            "execution_authority",
            "working_control_operation",
        ],
        "world_registry": known_world_entities(),
        "network_discovery": (
            []
            if args.registry_only
            else discover_read_only(
                default_discovery_broker(),
                include_cameras=args.include_cameras,
            )
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
