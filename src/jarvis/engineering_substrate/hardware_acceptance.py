"""Durable, exact hardware acceptance evidence for Phase 5H.

Hardware evidence is deliberately narrower than owner approval. A PASS here proves
only the requested physical observation. It never grants Authority, never advances
EngineeringChange on its own, and cannot override failed automated verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest, canonical_payload
from jarvis.engineering_substrate.contracts import (
    HardwareAcceptanceEvidence,
    HardwareAcceptanceRequest,
    HardwareAcceptanceVerdict,
)
from jarvis.engineering_substrate.manifest import RegisteredCapabilityManifest
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


class HardwareAcceptanceError(RuntimeError):
    """Base error for durable hardware acceptance."""


class HardwareAcceptanceConflict(HardwareAcceptanceError):
    """A request/evidence identity or compare-and-set invariant was violated."""


class HardwareAcceptanceExpired(HardwareAcceptanceError):
    """The exact hardware request is no longer eligible for resolution."""


class HardwareAcceptanceUnavailable(HardwareAcceptanceError):
    """The requested hardware acceptance record does not exist."""


@dataclass(frozen=True, slots=True)
class HardwareAcceptanceAssessment:
    request_id: str
    request_digest: str
    evidence_id: str | None
    verdict: HardwareAcceptanceVerdict | None
    required_automated_evidence_ids: tuple[str, ...]
    missing_automated_evidence_ids: tuple[str, ...]
    failed_automated_evidence_ids: tuple[str, ...]
    satisfied: bool
    reason: str


def _required_text(value: object, *, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _token(value: object, *, field: str) -> str:
    return _required_text(value, field=field).casefold()


def _sha256(value: object, *, field: str) -> str:
    digest = _token(value, field=field)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field} must be a 64-character SHA-256 digest")
    return digest


def _payload_dict(value: object) -> dict[str, object]:
    payload = canonical_payload(value)
    if not isinstance(payload, dict):
        raise TypeError("hardware acceptance contract must canonicalize to an object")
    return payload


def _request_from_payload(payload: Mapping[str, object]) -> HardwareAcceptanceRequest:
    return HardwareAcceptanceRequest(
        request_id=str(payload["request_id"]),
        change_id=str(payload["change_id"]),
        manifest_id=str(payload["manifest_id"]),
        manifest_digest=str(payload["manifest_digest"]),
        device_identity=str(payload["device_identity"]),
        operation=str(payload["operation"]),
        expected_observation=str(payload["expected_observation"]),
        required_automated_evidence_ids=tuple(
            str(item) for item in payload.get("required_automated_evidence_ids", ())
        ),
        created_at_epoch=float(payload["created_at_epoch"]),
        expires_at_epoch=float(payload["expires_at_epoch"]),
        schema_version=int(payload.get("schema_version", 1)),
    )


def _evidence_from_payload(payload: Mapping[str, object]) -> HardwareAcceptanceEvidence:
    return HardwareAcceptanceEvidence(
        evidence_id=str(payload["evidence_id"]),
        request_id=str(payload["request_id"]),
        request_digest=str(payload["request_digest"]),
        verdict=HardwareAcceptanceVerdict(str(payload["verdict"])),
        observed_at_epoch=float(payload["observed_at_epoch"]),
        owner_observation_ref=(
            None
            if payload.get("owner_observation_ref") is None
            else str(payload["owner_observation_ref"])
        ),
        telemetry_refs=tuple(str(item) for item in payload.get("telemetry_refs", ())),
        verifier_refs=tuple(str(item) for item in payload.get("verifier_refs", ())),
        schema_version=int(payload.get("schema_version", 1)),
    )


class HardwareAcceptanceService:
    """Persist exact request/evidence pairs in the canonical EngineeringChange DB."""

    SCHEMA_VERSION = 1

    def __init__(self, store: ChangeStore, *, clock=time.time) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be a ChangeStore")
        self.store = store
        self._clock = clock
        self._ensure_schema()

    @staticmethod
    def _schema_sql() -> str:
        return """
        CREATE TABLE IF NOT EXISTS engineering_hardware_acceptance_requests (
            request_id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES engineering_changes(change_id),
            request_digest TEXT NOT NULL,
            payload BLOB NOT NULL,
            created_at_epoch REAL NOT NULL,
            expires_at_epoch REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hardware_acceptance_request_change
            ON engineering_hardware_acceptance_requests(change_id, created_at_epoch);

        CREATE TABLE IF NOT EXISTS engineering_hardware_acceptance_evidence (
            evidence_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE
                REFERENCES engineering_hardware_acceptance_requests(request_id),
            request_digest TEXT NOT NULL,
            resolution_key TEXT NOT NULL UNIQUE,
            payload BLOB NOT NULL,
            observed_at_epoch REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS engineering_hardware_acceptance_schema (
            version INTEGER PRIMARY KEY,
            checksum TEXT NOT NULL
        );
        """

    def _ensure_schema(self) -> None:
        schema = self._schema_sql()
        checksum = hashlib.sha256(
            (schema + f"|hardware-acceptance-v{self.SCHEMA_VERSION}").encode("utf-8")
        ).hexdigest()
        work = self.store.work
        with work._lock, work._connect() as db:
            with db:
                db.executescript(schema)
                row = db.execute(
                    """SELECT checksum FROM engineering_hardware_acceptance_schema
                    WHERE version=?""",
                    (self.SCHEMA_VERSION,),
                ).fetchone()
                if row is not None and row["checksum"] != checksum:
                    raise HardwareAcceptanceConflict(
                        "hardware acceptance schema checksum mismatch"
                    )
                if row is None:
                    db.execute(
                        """INSERT INTO engineering_hardware_acceptance_schema
                        (version, checksum) VALUES (?, ?)""",
                        (self.SCHEMA_VERSION, checksum),
                    )

    def create_request(
        self,
        *,
        change_id: str,
        manifest: RegisteredCapabilityManifest,
        device_identity: str,
        operation: str,
        expected_observation: str,
        required_automated_evidence_ids: Sequence[str] = (),
        ttl_seconds: float = 900.0,
        request_id: str | None = None,
    ) -> HardwareAcceptanceRequest:
        change = self.store.require(_required_text(change_id, field="change_id"))
        if not isinstance(manifest, RegisteredCapabilityManifest):
            raise TypeError("manifest must be a RegisteredCapabilityManifest")
        if canonical_digest(manifest.manifest) != manifest.manifest_digest:
            raise HardwareAcceptanceConflict(
                "registered manifest digest does not match manifest content"
            )
        operation_token = _token(operation, field="operation")
        if operation_token not in manifest.manifest.operations:
            raise HardwareAcceptanceConflict(
                "hardware operation is not declared by the registered manifest"
            )
        if not manifest.manifest.hardware_acceptance_contract_ids:
            raise HardwareAcceptanceConflict(
                "registered manifest has no hardware acceptance contract"
            )
        ttl = float(ttl_seconds)
        if ttl <= 0 or ttl > 86_400:
            raise ValueError("hardware acceptance ttl_seconds must be within one day")

        created = float(self._clock())
        request = HardwareAcceptanceRequest(
            request_id=request_id or ("hwreq_" + uuid.uuid4().hex[:20]),
            change_id=change.change_id,
            manifest_id=manifest.manifest.manifest_id,
            manifest_digest=manifest.manifest_digest,
            device_identity=_required_text(device_identity, field="device_identity"),
            operation=operation_token,
            expected_observation=_required_text(
                expected_observation,
                field="expected_observation",
            ),
            required_automated_evidence_ids=tuple(
                _required_text(item, field="required_automated_evidence_id")
                for item in required_automated_evidence_ids
            ),
            created_at_epoch=created,
            expires_at_epoch=created + ttl,
        )
        digest = canonical_digest(request)
        payload = _payload_dict(request)

        work = self.store.work
        with work._lock, work._connect() as db:
            existing = db.execute(
                """SELECT request_digest, payload
                FROM engineering_hardware_acceptance_requests WHERE request_id=?""",
                (request.request_id,),
            ).fetchone()
            if existing is not None:
                decoded = work._decode_json(existing["payload"])
                current = _request_from_payload(decoded)
                if existing["request_digest"] == digest and current == request:
                    return current
                raise HardwareAcceptanceConflict(
                    "hardware acceptance request identity already differs"
                )
            with db:
                db.execute(
                    """INSERT INTO engineering_hardware_acceptance_requests
                    (request_id, change_id, request_digest, payload,
                     created_at_epoch, expires_at_epoch)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        request.request_id,
                        request.change_id,
                        digest,
                        work._encode_json(payload),
                        request.created_at_epoch,
                        request.expires_at_epoch,
                    ),
                )
                self.store._event(
                    db,
                    request.change_id,
                    f"hardware-request:{request.request_id}",
                    "hardware_acceptance_request",
                    {
                        "request_id": request.request_id,
                        "request_digest": digest,
                        "manifest_id": request.manifest_id,
                        "manifest_digest": request.manifest_digest,
                        "operation": request.operation,
                    },
                )
        return request

    def get_request(self, request_id: str) -> HardwareAcceptanceRequest:
        request_key = _required_text(request_id, field="request_id")
        work = self.store.work
        with work._lock, work._connect() as db:
            row = db.execute(
                """SELECT request_digest, payload
                FROM engineering_hardware_acceptance_requests WHERE request_id=?""",
                (request_key,),
            ).fetchone()
        if row is None:
            raise HardwareAcceptanceUnavailable("unknown hardware acceptance request")
        payload = work._decode_json(row["payload"])
        request = _request_from_payload(payload)
        if canonical_digest(request) != row["request_digest"]:
            raise HardwareAcceptanceConflict(
                "hardware acceptance request integrity mismatch"
            )
        return request

    def request_digest(self, request_id: str) -> str:
        return canonical_digest(self.get_request(request_id))

    def get_evidence(self, request_id: str) -> HardwareAcceptanceEvidence | None:
        request = self.get_request(request_id)
        work = self.store.work
        with work._lock, work._connect() as db:
            row = db.execute(
                """SELECT payload FROM engineering_hardware_acceptance_evidence
                WHERE request_id=?""",
                (request.request_id,),
            ).fetchone()
        if row is None:
            return None
        payload = work._decode_json(row["payload"])
        evidence = _evidence_from_payload(payload)
        if (
            evidence.request_id != request.request_id
            or evidence.request_digest != canonical_digest(request)
        ):
            raise HardwareAcceptanceConflict(
                "hardware acceptance evidence linkage mismatch"
            )
        return evidence

    def pending_request_ids(self, *, change_id: str | None = None) -> tuple[str, ...]:
        now = float(self._clock())
        work = self.store.work
        params: tuple[object, ...]
        where = """
            evidence.request_id IS NULL
            AND request.expires_at_epoch > ?
        """
        params = (now,)
        if change_id is not None:
            where += " AND request.change_id=?"
            params = (now, _required_text(change_id, field="change_id"))
        with work._lock, work._connect() as db:
            rows = db.execute(
                f"""SELECT request.request_id
                FROM engineering_hardware_acceptance_requests AS request
                LEFT JOIN engineering_hardware_acceptance_evidence AS evidence
                    USING (request_id)
                WHERE {where}
                ORDER BY request.created_at_epoch, request.request_id""",
                params,
            ).fetchall()
        return tuple(row["request_id"] for row in rows)

    def resolve(
        self,
        *,
        request_id: str,
        request_digest: str,
        manifest_digest: str,
        device_identity: str,
        operation: str,
        verdict: HardwareAcceptanceVerdict,
        resolution_key: str,
        owner_observation_ref: str | None = None,
        telemetry_refs: Sequence[str] = (),
        verifier_refs: Sequence[str] = (),
    ) -> HardwareAcceptanceEvidence:
        if not isinstance(verdict, HardwareAcceptanceVerdict):
            raise TypeError("verdict must be a HardwareAcceptanceVerdict")
        request = self.get_request(request_id)
        expected_digest = canonical_digest(request)
        if _sha256(request_digest, field="request_digest") != expected_digest:
            raise HardwareAcceptanceConflict("hardware request digest mismatch")
        if _sha256(manifest_digest, field="manifest_digest") != request.manifest_digest:
            raise HardwareAcceptanceConflict("hardware manifest digest mismatch")
        if (
            _required_text(device_identity, field="device_identity")
            != request.device_identity
        ):
            raise HardwareAcceptanceConflict("hardware device identity mismatch")
        if _token(operation, field="operation") != request.operation:
            raise HardwareAcceptanceConflict("hardware operation mismatch")
        owner_ref = (
            None
            if owner_observation_ref is None
            else _required_text(owner_observation_ref, field="owner_observation_ref")
        )
        telemetry = tuple(
            _required_text(item, field="telemetry_ref") for item in telemetry_refs
        )
        verifiers = tuple(
            _required_text(item, field="verifier_ref") for item in verifier_refs
        )
        if owner_ref is None and not telemetry and not verifiers:
            raise HardwareAcceptanceConflict(
                "hardware resolution requires trusted observation evidence"
            )
        resolution = _required_text(resolution_key, field="resolution_key")
        evidence_id = (
            "hwev_"
            + canonical_digest(
                {"request_id": request.request_id, "resolution_key": resolution}
            )[:20]
        )

        def matches_existing(
            row: sqlite3.Row | None,
        ) -> HardwareAcceptanceEvidence | None:
            if row is None:
                return None
            current = _evidence_from_payload(work._decode_json(row["payload"]))
            if (
                row["resolution_key"] == resolution
                and current.evidence_id == evidence_id
                and current.request_id == request.request_id
                and current.request_digest == expected_digest
                and current.verdict is verdict
                and current.owner_observation_ref == owner_ref
                and current.telemetry_refs == telemetry
                and current.verifier_refs == verifiers
            ):
                return current
            raise HardwareAcceptanceConflict(
                "hardware acceptance request already resolved differently"
            )

        work = self.store.work
        with work._lock, work._connect() as db:
            existing = db.execute(
                """SELECT resolution_key, payload
                FROM engineering_hardware_acceptance_evidence
                WHERE request_id=?""",
                (request.request_id,),
            ).fetchone()
            replay = matches_existing(existing)
            if replay is not None:
                return replay
            if float(self._clock()) >= request.expires_at_epoch:
                raise HardwareAcceptanceExpired("hardware acceptance request expired")

            evidence = HardwareAcceptanceEvidence(
                evidence_id=evidence_id,
                request_id=request.request_id,
                request_digest=expected_digest,
                verdict=verdict,
                observed_at_epoch=float(self._clock()),
                owner_observation_ref=owner_ref,
                telemetry_refs=telemetry,
                verifier_refs=verifiers,
            )
            payload = _payload_dict(evidence)
            try:
                with db:
                    db.execute(
                        """INSERT INTO engineering_hardware_acceptance_evidence
                        (evidence_id, request_id, request_digest, resolution_key,
                         payload, observed_at_epoch)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            evidence.evidence_id,
                            evidence.request_id,
                            evidence.request_digest,
                            resolution,
                            work._encode_json(payload),
                            evidence.observed_at_epoch,
                        ),
                    )
                    self.store._event(
                        db,
                        request.change_id,
                        f"hardware-evidence:{evidence.evidence_id}",
                        "hardware_acceptance_evidence",
                        {
                            "evidence_id": evidence.evidence_id,
                            "request_id": request.request_id,
                            "request_digest": expected_digest,
                            "verdict": evidence.verdict.value,
                        },
                    )
            except sqlite3.IntegrityError as exc:
                row = db.execute(
                    """SELECT resolution_key, payload
                    FROM engineering_hardware_acceptance_evidence
                    WHERE request_id=? OR resolution_key=?""",
                    (request.request_id, resolution),
                ).fetchone()
                try:
                    replay = matches_existing(row)
                except HardwareAcceptanceConflict as mismatch:
                    raise HardwareAcceptanceConflict(
                        "hardware resolution lost compare-and-set race"
                    ) from mismatch
                if replay is not None:
                    return replay
                raise HardwareAcceptanceConflict(
                    "hardware resolution lost compare-and-set race"
                ) from exc
        return evidence

    def assess(
        self,
        request_id: str,
        *,
        automated_evidence: Mapping[str, bool],
    ) -> HardwareAcceptanceAssessment:
        request = self.get_request(request_id)
        request_digest = canonical_digest(request)
        evidence = self.get_evidence(request_id)
        required = request.required_automated_evidence_ids
        missing = tuple(item for item in required if item not in automated_evidence)
        failed = tuple(
            item for item in required if automated_evidence.get(item) is False
        )

        if evidence is None:
            return HardwareAcceptanceAssessment(
                request_id=request.request_id,
                request_digest=request_digest,
                evidence_id=None,
                verdict=None,
                required_automated_evidence_ids=required,
                missing_automated_evidence_ids=missing,
                failed_automated_evidence_ids=failed,
                satisfied=False,
                reason="hardware acceptance is unresolved",
            )
        if evidence.verdict is not HardwareAcceptanceVerdict.PASS:
            return HardwareAcceptanceAssessment(
                request_id=request.request_id,
                request_digest=request_digest,
                evidence_id=evidence.evidence_id,
                verdict=evidence.verdict,
                required_automated_evidence_ids=required,
                missing_automated_evidence_ids=missing,
                failed_automated_evidence_ids=failed,
                satisfied=False,
                reason=f"hardware verdict is {evidence.verdict.value}",
            )
        if missing:
            reason = "required automated evidence is missing"
        elif failed:
            reason = "required automated evidence failed"
        else:
            reason = "hardware and required automated evidence satisfied"
        return HardwareAcceptanceAssessment(
            request_id=request.request_id,
            request_digest=request_digest,
            evidence_id=evidence.evidence_id,
            verdict=evidence.verdict,
            required_automated_evidence_ids=required,
            missing_automated_evidence_ids=missing,
            failed_automated_evidence_ids=failed,
            satisfied=not missing and not failed,
            reason=reason,
        )

    def verification_projection(
        self,
        request_id: str,
        *,
        automated_evidence: Mapping[str, bool],
    ) -> dict[str, object]:
        """Return bounded metadata for later EngineeringChange verification adapters."""

        assessment = self.assess(
            request_id,
            automated_evidence=automated_evidence,
        )
        return {
            "request_id": assessment.request_id,
            "request_digest": assessment.request_digest,
            "evidence_id": assessment.evidence_id,
            "verdict": (
                None if assessment.verdict is None else assessment.verdict.value
            ),
            "required_automated_evidence_ids": list(
                assessment.required_automated_evidence_ids
            ),
            "missing_automated_evidence_ids": list(
                assessment.missing_automated_evidence_ids
            ),
            "failed_automated_evidence_ids": list(
                assessment.failed_automated_evidence_ids
            ),
            "satisfied": assessment.satisfied,
            "reason": assessment.reason,
        }


def _build_cli_service(store_path: Path) -> HardwareAcceptanceService:
    work = SQLiteWorkStore(
        store_path,
        payload_codec=build_default_work_payload_codec(store_path),
    )
    return HardwareAcceptanceService(ChangeStore(work))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve one exact JARVIS hardware acceptance request."
    )
    parser.add_argument(
        "--store-path",
        type=Path,
        default=default_work_store_path(),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("pending")
    pending.add_argument("--change-id")

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--request-id", required=True)
    resolve.add_argument("--request-digest", required=True)
    resolve.add_argument("--manifest-digest", required=True)
    resolve.add_argument("--device-identity", required=True)
    resolve.add_argument("--operation", required=True)
    resolve.add_argument(
        "--verdict",
        required=True,
        choices=tuple(item.value for item in HardwareAcceptanceVerdict),
    )
    resolve.add_argument("--resolution-key", required=True)
    resolve.add_argument("--owner-observation-ref")
    resolve.add_argument("--telemetry-ref", action="append", default=[])
    resolve.add_argument("--verifier-ref", action="append", default=[])

    args = parser.parse_args(argv)
    service = _build_cli_service(args.store_path)

    if args.command == "pending":
        print(
            json.dumps(
                {
                    "pending_request_ids": list(
                        service.pending_request_ids(change_id=args.change_id)
                    )
                },
                sort_keys=True,
            )
        )
        return 0

    evidence = service.resolve(
        request_id=args.request_id,
        request_digest=args.request_digest,
        manifest_digest=args.manifest_digest,
        device_identity=args.device_identity,
        operation=args.operation,
        verdict=HardwareAcceptanceVerdict(args.verdict),
        resolution_key=args.resolution_key,
        owner_observation_ref=args.owner_observation_ref,
        telemetry_refs=tuple(args.telemetry_ref),
        verifier_refs=tuple(args.verifier_ref),
    )
    print(
        json.dumps(
            {
                "status": "RECORDED",
                "evidence_id": evidence.evidence_id,
                "request_id": evidence.request_id,
                "request_digest": evidence.request_digest,
                "verdict": evidence.verdict.value,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
