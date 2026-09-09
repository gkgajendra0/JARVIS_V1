"""Owner-machine Step-7 read-only acceptance smoke."""

from __future__ import annotations

import json
import uuid

from jarvis.capabilities.runtime import build_default_capability_runtime


def main() -> int:
    runtime = build_default_capability_runtime()
    session_id = f"step7-smoke-{uuid.uuid4()}"
    try:
        catalog = runtime.refresh_catalog()
        discovery = {
            "sources": [
                {
                    "source_id": item.source_id,
                    "state": item.state.value,
                    "reason": item.reason,
                    "elapsed_ms": round(item.elapsed_ms, 1),
                    "capability_count": len(item.capabilities),
                }
                for item in catalog.sources
            ],
            "capabilities": [
                {
                    "key": item.key,
                    "operations": list(item.operations),
                    "execution_enabled": item.execution_enabled,
                }
                for item in catalog.capabilities
            ],
        }
        print("JARVIS Step-7 owner acceptance smoke")
        print("No file writes, app control, browser control, or arbitrary commands are allowed.")
        print("[discovery]")
        print(json.dumps(discovery, indent=2, ensure_ascii=False))

        print("[routine-system-read]")
        system_result = runtime.execute_operation(
            session_id=session_id,
            operation="system_status",
            parameters={},
        )
        print(
            json.dumps(
                {
                    "status": system_result.status.value,
                    "data": system_result.data,
                    "reason": system_result.reason,
                    "elapsed_ms": round(system_result.elapsed_ms, 1),
                    "provenance": list(system_result.provenance),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        if not system_result.ok:
            return 2

        print("[private-project-read]")
        print(
            "Windows Hello should authorize this exact read of docs/ROADMAP.md. "
            "Canceling must fail closed."
        )
        project_result = runtime.execute_operation(
            session_id=session_id,
            operation="read_file",
            parameters={"root": "project", "path": "docs/ROADMAP.md"},
        )
        roadmap_text = str(project_result.data.get("text", ""))
        roadmap_verified = "Step 7" in roadmap_text and "CAP-032" in roadmap_text
        print(
            json.dumps(
                {
                    "status": project_result.status.value,
                    "reason": project_result.reason,
                    "elapsed_ms": round(project_result.elapsed_ms, 1),
                    "truncated": project_result.truncated,
                    "provenance": list(project_result.provenance),
                    "roadmap_verified": roadmap_verified,
                    "returned_characters": len(roadmap_text),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        if not project_result.ok or not roadmap_verified:
            return 3

        print(
            json.dumps(
                {
                    "ok": True,
                    "operation": "step7_owner_acceptance",
                    "read_only": True,
                    "dynamic_discovery": True,
                    "routine_system_read": True,
                    "private_project_read": True,
                    "canonical_authority": True,
                    "writes_or_control_enabled": False,
                },
                indent=2,
            )
        )
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
