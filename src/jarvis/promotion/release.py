"""Exact-SHA release slots and crash-safe local deployment metadata."""

from __future__ import annotations

import json
import math
import os
import pathlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Any

from jarvis.dev_control import RuntimeReleaseIdentity
from jarvis.engineering_substrate.canonical import canonical_digest

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_DEPLOYMENT_ROOT_ENV = "JARVIS_DEPLOYMENT_ROOT"
_RELEASES_ROOT_ENV = "JARVIS_RELEASES_ROOT"


def _jarvis_state_root() -> pathlib.Path:
    if os.name == "nt":
        local = os.getenv("LOCALAPPDATA", "").strip()
        if local:
            return pathlib.Path(local).expanduser().resolve() / "JARVIS"
    return pathlib.Path.home().expanduser().resolve() / ".jarvis"


def default_deployment_root() -> pathlib.Path:
    configured = os.getenv(_DEPLOYMENT_ROOT_ENV, "").strip()
    if configured:
        return pathlib.Path(configured).expanduser().resolve()
    return _jarvis_state_root() / "deployment"


def default_releases_root() -> pathlib.Path:
    configured = os.getenv(_RELEASES_ROOT_ENV, "").strip()
    if configured:
        return pathlib.Path(configured).expanduser().resolve()
    return _jarvis_state_root() / "releases"


class ReleaseError(RuntimeError):
    pass


def _sha(value: object, *, field: str) -> str:
    text = str(value or "").strip().casefold()
    if _GIT_SHA.fullmatch(text) is None:
        raise ValueError(f"{field} must be an exact lowercase Git SHA")
    return text


def _digest(value: object, *, field: str) -> str:
    text = str(value or "").strip().casefold()
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    release_sha: str
    release_root: str
    promotion_attempt_id: str
    promotion_evidence_digest: str
    config_digest: str
    schema_versions: tuple[tuple[str, int], ...]
    accepted_at_epoch: float

    def __post_init__(self) -> None:
        _sha(self.release_sha, field="release_sha")
        if not self.release_root.strip():
            raise ValueError("release_root must not be empty")
        if not self.promotion_attempt_id.startswith("promotion_"):
            raise ValueError("promotion_attempt_id must use promotion_ prefix")
        _digest(
            self.promotion_evidence_digest,
            field="promotion_evidence_digest",
        )
        _digest(self.config_digest, field="config_digest")
        if not math.isfinite(self.accepted_at_epoch) or self.accepted_at_epoch <= 0:
            raise ValueError("accepted_at_epoch must be finite and positive")
        names: set[str] = set()
        for name, version in self.schema_versions:
            if not name.strip() or name in names:
                raise ValueError("schema version names must be unique and non-empty")
            if type(version) is not int or version < 0:
                raise ValueError("schema versions must be non-negative integers")
            names.add(name)

    def runtime_identity(self) -> RuntimeReleaseIdentity:
        return RuntimeReleaseIdentity(
            release_sha=self.release_sha,
            release_root=self.release_root,
            promotion_attempt_id=self.promotion_attempt_id,
            config_digest=self.config_digest,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "release_sha": self.release_sha,
            "release_root": self.release_root,
            "promotion_attempt_id": self.promotion_attempt_id,
            "promotion_evidence_digest": self.promotion_evidence_digest,
            "config_digest": self.config_digest,
            "schema_versions": {
                name: version for name, version in self.schema_versions
            },
            "accepted_at_epoch": self.accepted_at_epoch,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReleaseRecord":
        raw_schema = payload.get("schema_versions")
        if not isinstance(raw_schema, dict):
            raise ReleaseError("release record schema_versions is malformed")
        return cls(
            release_sha=str(payload.get("release_sha", "")),
            release_root=str(payload.get("release_root", "")),
            promotion_attempt_id=str(payload.get("promotion_attempt_id", "")),
            promotion_evidence_digest=str(payload.get("promotion_evidence_digest", "")),
            config_digest=str(payload.get("config_digest", "")),
            schema_versions=tuple(
                sorted(
                    (str(name), int(version)) for name, version in raw_schema.items()
                )
            ),
            accepted_at_epoch=float(payload.get("accepted_at_epoch", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class DeploymentRequest:
    request_id: str
    change_id: str
    attempt_id: str
    merge_sha: str
    evidence_digest: str
    config_digest: str
    expected_lkg_sha: str
    schema_versions: tuple[tuple[str, int], ...]
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        change_id: str,
        attempt_id: str,
        merge_sha: str,
        evidence_digest: str,
        config_digest: str,
        expected_lkg_sha: str,
        schema_versions: tuple[tuple[str, int], ...] = (),
        now_epoch: float,
    ) -> "DeploymentRequest":
        normalized_change = str(change_id).strip()
        normalized_attempt = str(attempt_id).strip()
        if not normalized_change:
            raise ValueError("change_id must not be empty")
        if not normalized_attempt.startswith("promotion_"):
            raise ValueError("attempt_id must use promotion_ prefix")
        if not math.isfinite(float(now_epoch)) or float(now_epoch) <= 0:
            raise ValueError("created_at_epoch must be finite and positive")
        normalized_schema = tuple(sorted(schema_versions))
        payload: dict[str, object] = {
            "schema_version": 1,
            "change_id": normalized_change,
            "attempt_id": normalized_attempt,
            "merge_sha": _sha(merge_sha, field="merge_sha"),
            "evidence_digest": _digest(
                evidence_digest,
                field="evidence_digest",
            ),
            "config_digest": _digest(config_digest, field="config_digest"),
            "expected_lkg_sha": _sha(
                expected_lkg_sha,
                field="expected_lkg_sha",
            ),
            "schema_versions": {
                name: version for name, version in normalized_schema
            },
            "created_at_epoch": float(now_epoch),
        }
        digest = canonical_digest(payload)
        return cls(
            request_id=f"deployment_request_{digest[:16]}",
            change_id=normalized_change,
            attempt_id=normalized_attempt,
            merge_sha=str(payload["merge_sha"]),
            evidence_digest=str(payload["evidence_digest"]),
            config_digest=str(payload["config_digest"]),
            expected_lkg_sha=str(payload["expected_lkg_sha"]),
            schema_versions=normalized_schema,
            created_at_epoch=float(now_epoch),
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "change_id": self.change_id,
            "attempt_id": self.attempt_id,
            "merge_sha": self.merge_sha,
            "evidence_digest": self.evidence_digest,
            "config_digest": self.config_digest,
            "expected_lkg_sha": self.expected_lkg_sha,
            "schema_versions": {
                name: version for name, version in self.schema_versions
            },
            "created_at_epoch": self.created_at_epoch,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            **self.canonical_payload(),
            "digest": self.digest,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DeploymentRequest":
        raw_schema = payload.get("schema_versions")
        if not isinstance(raw_schema, dict):
            raise ReleaseError("deployment request schema_versions is malformed")
        request = cls(
            request_id=str(payload.get("request_id", "")),
            change_id=str(payload.get("change_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            merge_sha=str(payload.get("merge_sha", "")),
            evidence_digest=str(payload.get("evidence_digest", "")),
            config_digest=str(payload.get("config_digest", "")),
            expected_lkg_sha=str(payload.get("expected_lkg_sha", "")),
            schema_versions=tuple(
                sorted((str(name), int(version)) for name, version in raw_schema.items())
            ),
            created_at_epoch=float(payload.get("created_at_epoch", 0.0)),
            digest=str(payload.get("digest", "")),
        )
        if request.request_id != f"deployment_request_{request.digest[:16]}":
            raise ReleaseError("deployment request id is not digest-derived")
        if canonical_digest(request.canonical_payload()) != request.digest:
            raise ReleaseError("deployment request digest mismatch")
        return request

    def __post_init__(self) -> None:
        if not self.change_id.strip():
            raise ValueError("change_id must not be empty")
        if not self.attempt_id.startswith("promotion_"):
            raise ValueError("attempt_id must use promotion_ prefix")
        _sha(self.merge_sha, field="merge_sha")
        _digest(self.evidence_digest, field="evidence_digest")
        _digest(self.config_digest, field="config_digest")
        _sha(self.expected_lkg_sha, field="expected_lkg_sha")
        if not math.isfinite(self.created_at_epoch) or self.created_at_epoch <= 0:
            raise ValueError("created_at_epoch must be finite and positive")
        names: set[str] = set()
        for name, version in self.schema_versions:
            if not name.strip() or name in names:
                raise ValueError("schema version names must be unique and non-empty")
            if type(version) is not int or version < 0:
                raise ValueError("schema versions must be non-negative integers")
            names.add(name)



class RecoveryPhase(str, Enum):
    STAGED = "staged"
    OLD_RUNTIME_STOPPED = "old_runtime_stopped"
    NEW_RUNTIME_STARTED = "new_runtime_started"
    NEW_RUNTIME_VERIFIED = "new_runtime_verified"
    STARTUP_FAILED = "startup_failed"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_VERIFIED = "rollback_verified"


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    deployment_id: str
    attempt_id: str
    phase: RecoveryPhase
    candidate: ReleaseRecord
    lkg: ReleaseRecord

    def __post_init__(self) -> None:
        if not self.deployment_id.startswith("deployment_"):
            raise ValueError("deployment_id must use deployment_ prefix")
        if self.attempt_id != self.candidate.promotion_attempt_id:
            raise ValueError("recovery attempt must match candidate release")

    def to_payload(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "attempt_id": self.attempt_id,
            "phase": self.phase.value,
            "candidate": self.candidate.to_payload(),
            "lkg": self.lkg.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RecoveryRecord":
        candidate = payload.get("candidate")
        lkg = payload.get("lkg")
        if not isinstance(candidate, dict) or not isinstance(lkg, dict):
            raise ReleaseError("recovery record release payload is malformed")
        return cls(
            deployment_id=str(payload.get("deployment_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            phase=RecoveryPhase(str(payload.get("phase", ""))),
            candidate=ReleaseRecord.from_payload(candidate),
            lkg=ReleaseRecord.from_payload(lkg),
        )


class DeploymentMetadataStore:
    """Atomic local deployment truth under one managed directory."""

    def __init__(self, root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> pathlib.Path:
        return self.root / f"{name}.json"

    @staticmethod
    def _read(path: pathlib.Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ReleaseError(f"deployment metadata is not a regular file: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseError(f"deployment metadata is unreadable: {path}") from exc
        if not isinstance(payload, dict):
            raise ReleaseError(f"deployment metadata is malformed: {path}")
        return payload

    @staticmethod
    def _write_atomic(path: pathlib.Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = pathlib.Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def active(self) -> ReleaseRecord | None:
        payload = self._read(self._path("active"))
        return None if payload is None else ReleaseRecord.from_payload(payload)

    def lkg(self) -> ReleaseRecord | None:
        payload = self._read(self._path("lkg"))
        return None if payload is None else ReleaseRecord.from_payload(payload)

    def recovery(self) -> RecoveryRecord | None:
        payload = self._read(self._path("recovery"))
        return None if payload is None else RecoveryRecord.from_payload(payload)

    def request(self) -> DeploymentRequest | None:
        payload = self._read(self._path("request"))
        return None if payload is None else DeploymentRequest.from_payload(payload)

    def set_active(self, record: ReleaseRecord) -> None:
        self._write_atomic(self._path("active"), record.to_payload())

    def set_lkg(self, record: ReleaseRecord) -> None:
        self._write_atomic(self._path("lkg"), record.to_payload())

    def set_recovery(self, record: RecoveryRecord) -> None:
        self._write_atomic(self._path("recovery"), record.to_payload())

    def set_request(self, request: DeploymentRequest) -> None:
        self._write_atomic(self._path("request"), request.to_payload())

    def clear_request(self) -> None:
        self._path("request").unlink(missing_ok=True)

    def clear_recovery(self) -> None:
        self._path("recovery").unlink(missing_ok=True)


class GitReleaseStager:
    """Create/reuse a detached exact-commit Git worktree under a managed release root."""

    def __init__(
        self,
        repository_root: pathlib.Path | str,
        releases_root: pathlib.Path | str,
    ) -> None:
        self.repository_root = pathlib.Path(repository_root).resolve()
        self.releases_root = pathlib.Path(releases_root).expanduser().resolve()
        if self.repository_root == self.releases_root:
            raise ValueError("release root must be separate from repository root")
        self.releases_root.mkdir(parents=True, exist_ok=True)

    def _run(
        self,
        *args: str,
        cwd: pathlib.Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repository_root,
            check=check,
            capture_output=True,
            text=True,
            timeout=30.0,
        )

    def _validate_existing(self, target: pathlib.Path, sha: str) -> None:
        if target.is_symlink() or not target.is_dir():
            raise ReleaseError("release slot is not a regular directory")
        observed = self._run("-C", str(target), "rev-parse", "HEAD").stdout.strip()
        if observed.casefold() != sha:
            raise ReleaseError("existing release slot has the wrong Git SHA")
        tracked = self._run(
            "-C",
            str(target),
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
        ).stdout
        if tracked.strip():
            raise ReleaseError("existing release slot has tracked source mutations")

    def stage(self, release_sha: str) -> pathlib.Path:
        sha = _sha(release_sha, field="release_sha")
        target = (self.releases_root / sha).resolve()
        if target.parent != self.releases_root:
            raise ReleaseError("release slot escaped managed root")
        if target.exists():
            self._validate_existing(target, sha)
            return target

        try:
            self._run("cat-file", "-e", f"{sha}^{{commit}}")
            self._run("worktree", "add", "--detach", str(target), sha)
            self._validate_existing(target, sha)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError(f"failed to stage exact release {sha}") from exc
        return target


def load_active_release_for_startup() -> ReleaseRecord | None:
    """Load and verify the exact active release used by production supervisor startup."""
    metadata = DeploymentMetadataStore(default_deployment_root())
    active = metadata.active()
    if active is None:
        return None

    release_root = pathlib.Path(active.release_root).expanduser().resolve()
    releases_root = default_releases_root().resolve()
    if release_root.parent != releases_root:
        raise ReleaseError(
            "active release root is outside the managed releases directory"
        )
    if release_root.is_symlink() or not release_root.is_dir():
        raise ReleaseError("active release root is unavailable or unsafe")
    try:
        observed = (
            subprocess.run(
                ["git", "-C", str(release_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            .stdout.strip()
            .casefold()
        )
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(release_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15.0,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError("active release Git identity is unavailable") from exc
    if observed != active.release_sha:
        raise ReleaseError("active release root does not match recorded release SHA")
    if tracked.strip():
        raise ReleaseError("active release root contains tracked source mutations")
    return active


def deployment_id(
    *,
    attempt_id: str,
    merge_sha: str,
    evidence_digest: str,
) -> str:
    digest = canonical_digest(
        {
            "attempt_id": attempt_id,
            "merge_sha": _sha(merge_sha, field="merge_sha"),
            "evidence_digest": _digest(
                evidence_digest,
                field="evidence_digest",
            ),
        }
    )
    return f"deployment_{digest[:16]}"
