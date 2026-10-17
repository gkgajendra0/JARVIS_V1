"""Owner-machine opt-in REAL Hindsight import probe, default ZERO network calls.

This uses a fresh disposable bank on a separately verified, local-only
Docker Hindsight container. NEVER send personal memory, enable a cloud
model, touch canonical SQLCipher, or ask Hindsight to consolidate.

Do not run this until the separately documented Docker image is explicitly
pulled and started with HINDSIGHT_API_LLM_PROVIDER=none and observations off.
The first test may download a ~9 GB container image if the owner pulls it.
This runner itself never downloads images, installs packages or starts Docker.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jarvis.memory.hindsight_transfer_shadow import (
    PINNED_FACTS,
    build_synthetic_external_fact_zip,
    inspect_synthetic_archive,
)

BASE_URL = "http://127.0.0.1:18888"
DOCKER_CONTAINER = "jarvis-hindsight-lab"
IMAGE = "ghcr.io/vectorize-io/hindsight:latest"
_REQUIRED_ENV = {
    "HINDSIGHT_API_LLM_PROVIDER": "none",
    "HINDSIGHT_API_ENABLE_OBSERVATIONS": "false",
    "HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION": "false",
}
_CLOUD_KEY_MARKERS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HINDSIGHT_API_LLM_API_KEY",
    "HINDSIGHT_API_CONSOLIDATION_LLM_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AZURE_OPENAI_API_KEY",
)
_MAX_RESPONSE_BYTES = 131_072
_POLL_COUNT = 45
_POLL_SECONDS = 2
_BANK_ID = re.compile(r"^jarvis-dev-only-[0-9a-f]{32}$")


class ProbeFailure(Exception):
    """Sanitized local-research error, never provider text or memory content."""


class LocalHTTPError(ProbeFailure):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"local_http_{status_code}")


def check_isolated_docker_inspect(data: dict[str, Any]) -> bool:
    """Verify the exact local owner-controlled container before contacting it."""

    if not isinstance(data, dict) or not data:
        raise ProbeFailure("docker_inspection_unavailable")
    item = data
    image = item.get("Config", {}).get("Image")
    state = item.get("State", {}).get("Running")
    name = item.get("Name")
    if image != IMAGE or state is not True or name != f"/{DOCKER_CONTAINER}":
        raise ProbeFailure("unexpected_container_identity")
    raw_env = item.get("Config", {}).get("Env")
    if not isinstance(raw_env, list):
        raise ProbeFailure("missing_container_configuration")
    env: dict[str, str] = {}
    for val in raw_env:
        if not isinstance(val, str) or "=" not in val:
            raise ProbeFailure("invalid_container_configuration")
        key, value = val.split("=", 1)
        if key in env:
            raise ProbeFailure("duplicate_container_environment_key")
        env[key] = value
    if any(env.get(name, "").strip() for name in _CLOUD_KEY_MARKERS):
        raise ProbeFailure("container_has_cloud_credentials")
    if any(
        env.get(key, "").casefold() != required
        for key, required in _REQUIRED_ENV.items()
    ):
        raise ProbeFailure("local_no_llm_safety_flags_missing")
    if env.get("HINDSIGHT_API_DEFAULT_BANK_TEMPLATE", "").strip():
        raise ProbeFailure("bank_template_must_be_disabled")
    if env.get("HINDSIGHT_API_DATABASE_URL", "pg0").lower() != "pg0":
        raise ProbeFailure("embedded_database_required")
    host_config = item.get("HostConfig", {})
    ports = host_config.get("PortBindings", {}).get("8888/tcp")
    if ports != [{"HostIp": "127.0.0.1", "HostPort": "18888"}]:
        raise ProbeFailure("loopback_only_port_required")
    if host_config.get("RestartPolicy", {}).get("Name") not in ("no", None, ""):
        raise ProbeFailure("no_restart_policy_required")
    mounts = item.get("Mounts", [])
    if len(mounts) != 1 or mounts[0].get("Type") != "volume":
        raise ProbeFailure("only_one_disposable_named_volume_allowed")
    if mounts[0].get("Destination") != "/home/hindsight/.pg0" or not str(
        mounts[0].get("Name", "")
    ).startswith("jarvis-hindsight-lab-"):
        raise ProbeFailure("unexpected_database_mount")
    return True


def verify_local_container() -> bool:
    result = subprocess.run(
        ["docker", "inspect", DOCKER_CONTAINER],
        check=False,
        capture_output=True,
        text=True,
        timeout=12,
    )
    if result.returncode != 0:
        raise ProbeFailure("docker_container_not_ready")
    try:
        inspected = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ProbeFailure("docker_inspection_invalid") from exc
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise ProbeFailure("docker_inspection_invalid")
    return check_isolated_docker_inspect(inspected[0])


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, url: str
    ) -> None:
        raise ProbeFailure("redirect_refused")


class LocalHindsightHTTP:
    """Single hardcoded loopback base; no proxy, no redirects, no auth header."""

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if (
            method not in {"GET", "PUT", "PATCH", "POST", "DELETE"}
            or not path.startswith("/")
            or "//" in path
            or ":" in path
            or "#" in path
        ):
            raise ProbeFailure("invalid_local_request")
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        req = Request(
            BASE_URL + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(req, timeout=45) as response:
                contents = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise LocalHTTPError(exc.code) from exc
        if len(contents) > _MAX_RESPONSE_BYTES:
            raise ProbeFailure("local_response_too_large")
        try:
            result = json.loads(contents) if contents else {}
        except ValueError as exc:
            raise ProbeFailure("invalid_local_json") from exc
        if not isinstance(result, dict):
            raise ProbeFailure("invalid_local_response_type")
        return result


def _json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _multipart(archive: bytes) -> tuple[bytes, str]:
    boundary = "jarvis-hindsight-synthetic-boundary"
    data = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="synthetic.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        + archive
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return data, f"multipart/form-data; boundary={boundary}"


def _require_disabled_config(config_response: dict[str, Any]) -> None:
    values = config_response.get("config")
    if not isinstance(values, dict):
        raise ProbeFailure("resolved_config_missing")
    if values.get("enable_auto_consolidation") is not False:
        raise ProbeFailure("auto_consolidation_not_disabled")
    if values.get("enable_observations") is not False:
        raise ProbeFailure("observations_not_disabled")


def run_local_import(
    transport: Any,
    *,
    inspected: bool,
    bank_id: str,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """One import, one disposable bank and enforced cleanup (no retry)."""

    if inspected is not True:
        raise ProbeFailure("docker_provenance_not_verified")
    if not _BANK_ID.fullmatch(bank_id):
        raise ProbeFailure("invalid_disposable_bank_id")
    archive = build_synthetic_external_fact_zip()
    evidence = inspect_synthetic_archive(archive)
    root = f"/v1/default/banks/{bank_id}"
    created_or_uncertain = False
    cleanup_verified = False
    result: dict[str, Any] = {}
    try:
        # The local server is intentionally not reached before its own
        # isolated Docker configuration has been independently verified.
        transport.request("GET", "/version")
        created_or_uncertain = True
        transport.request("PUT", root, _json({}), "application/json")
        transport.request(
            "PATCH",
            f"{root}/config",
            _json(
                {
                    "updates": {
                        "enable_auto_consolidation": False,
                        "enable_observations": False,
                        "retain_extraction_mode": "chunks",
                    }
                }
            ),
            "application/json",
        )
        _require_disabled_config(transport.request("GET", f"{root}/config"))
        # Import is authorized only AFTER effective per-bank settings confirm
        # no auto consolidation. Request URL and payload are both fixed.
        payload, content_type = _multipart(archive)
        response = transport.request(
            "POST",
            f"{root}/transfer/import?mode=merge&document_conflict=skip",
            payload,
            content_type,
        )
        op_id = response.get("operation_id")
        if not isinstance(op_id, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{4,100}", op_id
        ):
            raise ProbeFailure("invalid_operation_reference")
        last = "unknown"
        for i in range(_POLL_COUNT):
            status_response = transport.request("GET", f"{root}/operations/{op_id}")
            last = status_response.get("status")
            if last in {"failed", "cancelled", "not_found"}:
                raise ProbeFailure("import_operation_not_completed")
            if last == "completed":
                break
            if i != _POLL_COUNT - 1:
                pause(_POLL_SECONDS)
        if last != "completed":
            raise ProbeFailure("import_operation_timeout")
        listed = transport.request("GET", f"{root}/documents?limit=100")
        expected = {f"jarvis-dev-only-{fact.assertion_id}" for fact in PINNED_FACTS}
        docs = listed.get("items")
        if (
            listed.get("total") != len(PINNED_FACTS)
            or not isinstance(docs, list)
            or {doc.get("id") for doc in docs} != expected
            or any(doc.get("memory_unit_count") != 1 for doc in docs)
        ):
            raise ProbeFailure("unexpected_imported_documents")
        for fact in PINNED_FACTS:
            doc_id = f"jarvis-dev-only-{fact.assertion_id}"
            detail = transport.request("GET", f"{root}/documents/{doc_id}")
            if (
                detail.get("id") != doc_id
                or detail.get("original_text") != fact.text
                or detail.get("memory_unit_count") != 1
            ):
                raise ProbeFailure("document_readback_mismatch")
        result = {
            "kind": "LOCAL_HINDSIGHT_IMPORT_COMPATIBILITY_ONLY",
            "archive_sha256": evidence["sha256"],
            "import_completed": True,
            "documents_read_back": len(PINNED_FACTS),
            "no_provider_calls_configured": True,
            "no_consolidation_triggered": True,
            "no_production_memory": True,
            "not_semantic_accuracy_acceptance": True,
        }
    finally:
        if created_or_uncertain:
            deletion = transport.request("DELETE", root)
            if deletion.get("success") is not True:
                raise ProbeFailure("disposable_bank_cleanup_failed")
            try:
                transport.request("GET", f"{root}/config")
            except LocalHTTPError as exc:
                if exc.status_code == 404:
                    cleanup_verified = True
                else:
                    raise
            if not cleanup_verified:
                raise ProbeFailure("disposable_bank_still_exists")
    if not cleanup_verified:
        raise ProbeFailure("disposable_bank_cleanup_unverified")
    return {**result, "disposable_bank_cleanup_verified": True}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-one-local-import", action="store_true")
    args = parser.parse_args(argv)
    if not args.allow_one_local_import:
        print(
            json.dumps(
                {
                    "status": "dry_run_zero_network_calls",
                    "expected_documents": len(PINNED_FACTS),
                    "required_container": DOCKER_CONTAINER,
                    "api": BASE_URL,
                    "new_cloud_cost": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    try:
        verify_local_container()
        report = run_local_import(
            LocalHindsightHTTP(),
            inspected=True,
            bank_id=f"jarvis-dev-only-{uuid.uuid4().hex}",
        )
    except Exception as exc:  # noqa: BLE001
        # Never echo provider exceptions, machine paths, credentials or facts.
        print(
            json.dumps(
                {
                    "status": "fail_closed",
                    "error_type": type(exc).__name__,
                    "reason_code": str(exc)
                    if isinstance(exc, ProbeFailure)
                    else "local_probe_failed",
                },
                sort_keys=True,
                indent=2,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
