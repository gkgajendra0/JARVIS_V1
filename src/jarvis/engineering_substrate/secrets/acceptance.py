"""Owner-machine Phase-5E acceptance using a disposable generated secret."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from jarvis.authority import ActionOrigin, InteractionContext, TrustTier
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.secrets.broker import (
    SecretAuthorityEvidence,
    SecretBroker,
    SecretLeaseRequest,
    build_secret_lease_proposal,
    default_secret_consumer_registry,
)
from jarvis.engineering_substrate.secrets.store import SecretStore


class SecretAcceptanceError(RuntimeError):
    """The owner-machine disposable-secret acceptance failed."""


@dataclass(frozen=True, slots=True)
class SecretAcceptanceResult:
    status: str
    store_protector_id: str
    consumer_id: str
    scope: str
    child_digest: str
    persistence_files_scanned: int


class _AcceptanceAuthorityGate:
    """Acceptance-only gate; canonical Authority binding is covered by unit tests."""

    def authorize(
        self,
        *,
        request: SecretLeaseRequest,
        proposal,
        context,
        permit_id: str,
    ) -> SecretAuthorityEvidence:
        if permit_id != "phase5e-owner-acceptance":
            raise SecretAcceptanceError("unexpected acceptance permit")
        if proposal.session_id != context.session_id:
            raise SecretAcceptanceError("acceptance proposal session mismatch")
        return SecretAuthorityEvidence(
            decision_id="phase5e-owner-acceptance",
            proposal_fingerprint=proposal.fingerprint,
            policy_version="phase5e-owner-acceptance-v1",
            risk_class="CRITICAL",
            policy_digest=canonical_digest(
                {
                    "purpose": "phase5e-owner-acceptance",
                    "secret_id": request.secret_id,
                    "consumer_id": request.consumer_id,
                    "scopes": list(request.scopes),
                }
            ),
        )


def _scan_for_plaintext(root: pathlib.Path, plaintext: bytes) -> int:
    scanned = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        scanned += 1
        if plaintext in path.read_bytes():
            raise SecretAcceptanceError(
                f"plaintext secret persisted in acceptance file: {path.name}"
            )
    return scanned


def run_acceptance() -> SecretAcceptanceResult:
    if sys.platform != "win32":
        raise SecretAcceptanceError("Phase-5E owner acceptance requires Windows")

    secret_text = "phase5e-" + secrets.token_urlsafe(32)
    secret_value = secret_text.encode("utf-8")
    expected_digest = hashlib.sha256(secret_value).hexdigest()
    consumer_id = "dependency.private-index.v1"
    scope = "repository.read"
    environment_name = "JARVIS_DEPENDENCY_INDEX_TOKEN"
    before_global = os.environ.get(environment_name)

    with tempfile.TemporaryDirectory(prefix="jarvis-phase5e-") as temporary:
        root = pathlib.Path(temporary)
        store = SecretStore(root / "secrets.sqlite")
        descriptor = store.enroll(
            secret_id="phase5e-owner-acceptance-secret",
            kind="disposable-test-token",
            service="phase5e-owner-acceptance",
            allowed_consumers=(consumer_id,),
            allowed_scopes=(scope,),
            value=secret_value,
        )
        if store.materialize(descriptor.secret_id).value != secret_value:
            raise SecretAcceptanceError("DPAPI round trip changed the disposable secret")

        request = SecretLeaseRequest(
            secret_id=descriptor.secret_id,
            consumer_id=consumer_id,
            scopes=(scope,),
            ttl_seconds=60,
            use_budget=1,
            change_id="phase5e-owner-acceptance",
            work_id="phase5e-owner-acceptance",
        )
        proposal = build_secret_lease_proposal(
            request,
            session_id="phase5e-owner-acceptance",
            origin=ActionOrigin.SYSTEM,
        )
        context = InteractionContext(
            session_id="phase5e-owner-acceptance",
            trust_tier=TrustTier.VERIFIED_OWNER,
            actor_unambiguous=True,
        )
        broker = SecretBroker(
            store=store,
            consumers=default_secret_consumer_registry(),
            authority_gate=_AcceptanceAuthorityGate(),
        )
        lease = broker.issue_lease(
            request,
            proposal=proposal,
            context=context,
            permit_id="phase5e-owner-acceptance",
        )

        child_code = (
            "import hashlib,os;"
            f"v=os.environ[{environment_name!r}].encode();"
            "print(hashlib.sha256(v).hexdigest())"
        )
        with broker.child_environment(
            lease.lease_id,
            consumer_id=consumer_id,
        ) as child_environment:
            if child_environment.get(environment_name) != secret_text:
                raise SecretAcceptanceError(
                    "scoped child environment did not receive the disposable secret"
                )
            completed = subprocess.run(
                [sys.executable, "-c", child_code],
                env=child_environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
                shell=False,
            )
        if completed.returncode != 0:
            raise SecretAcceptanceError("scoped child process failed")
        child_digest = completed.stdout.strip()
        if child_digest != expected_digest:
            raise SecretAcceptanceError("scoped child observed unexpected secret bytes")
        if secret_text in completed.stdout or secret_text in completed.stderr:
            raise SecretAcceptanceError("scoped child output exposed plaintext secret")
        if os.environ.get(environment_name) != before_global:
            raise SecretAcceptanceError("global process environment was mutated")

        scanned = _scan_for_plaintext(root, secret_value)
        store.revoke(descriptor.secret_id)

        return SecretAcceptanceResult(
            status="PASS",
            store_protector_id=store.protector_id,
            consumer_id=consumer_id,
            scope=scope,
            child_digest=child_digest,
            persistence_files_scanned=scanned,
        )


def main() -> int:
    try:
        result = run_acceptance()
    except Exception as exc:
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
    print(
        json.dumps(
            {
                "status": result.status,
                "store_protector_id": result.store_protector_id,
                "consumer_id": result.consumer_id,
                "scope": result.scope,
                "child_digest": result.child_digest,
                "persistence_files_scanned": result.persistence_files_scanned,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
