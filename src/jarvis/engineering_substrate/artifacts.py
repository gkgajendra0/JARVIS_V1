"""Content-addressed immutable artifact staging for Phase 5."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass

from jarvis.engineering_substrate.canonical import canonical_digest

_BUFFER_SIZE = 1024 * 1024


class ArtifactStoreError(RuntimeError):
    """Base error for content-addressed artifact storage."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Artifact bytes do not match the expected or stored SHA-256 identity."""


class ArtifactPathError(ArtifactStoreError):
    """A path escaped or violated the artifact-store trust boundary."""


@dataclass(frozen=True, slots=True)
class ArtifactAdmissionRecord:
    artifact_sha256: str
    size_bytes: int
    provenance_id: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        digest = _sha256(self.artifact_sha256)
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        object.__setattr__(self, "artifact_sha256", digest)
        object.__setattr__(
            self,
            "provenance_id",
            _optional_text(self.provenance_id),
        )
        object.__setattr__(
            self,
            "source_id",
            _optional_text(self.source_id),
        )


@dataclass(frozen=True, slots=True)
class ArtifactAdmissionResult:
    artifact_sha256: str
    size_bytes: int
    object_path: pathlib.Path
    admission_record_path: pathlib.Path
    already_present: bool


@dataclass(frozen=True, slots=True)
class ArtifactRetentionReferences:
    """Caller-supplied immutable retention set for safe future garbage collection."""

    referenced_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(_sha256(item) for item in self.referenced_sha256))
        object.__setattr__(self, "referenced_sha256", normalized)


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _sha256(value: object) -> str:
    normalized = str(value).strip().casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError("artifact digest must be a 64-character SHA-256 hex digest")
    return normalized


def default_artifact_root() -> pathlib.Path:
    if os.name == "nt":
        base = pathlib.Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(pathlib.Path.home() / "AppData" / "Local"),
            )
        )
    else:
        base = pathlib.Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(pathlib.Path.home() / ".local" / "state"),
            )
        )
    return (base / "JARVIS" / "engineering" / "artifacts").resolve()


class ArtifactStore:
    """Immutable SHA-256 object store with quarantine and verify-on-read."""

    def __init__(self, root: pathlib.Path | str | None = None) -> None:
        raw_root = pathlib.Path(root or default_artifact_root())
        if raw_root.exists() and raw_root.is_symlink():
            raise ArtifactPathError("artifact store root cannot be a symlink")
        self.root = raw_root.resolve()
        self.objects_root = self.root / "sha256"
        self.metadata_root = self.root / "metadata" / "sha256"
        self.quarantine_root = self.root / "quarantine"
        self.temp_root = self.root / ".tmp"
        for path in (
            self.objects_root,
            self.metadata_root,
            self.quarantine_root,
            self.temp_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self._assert_trusted_root()

    def _assert_trusted_root(self) -> None:
        for path in (
            self.root,
            self.objects_root,
            self.metadata_root,
            self.quarantine_root,
            self.temp_root,
        ):
            if path.is_symlink():
                raise ArtifactPathError("artifact store directories cannot be symlinks")
            try:
                path.resolve().relative_to(self.root)
            except ValueError as exc:
                raise ArtifactPathError("artifact store path escaped trusted root") from exc

    def _object_path(self, digest: str) -> pathlib.Path:
        normalized = _sha256(digest)
        path = self.objects_root / normalized
        self._require_within(path, self.objects_root)
        return path

    def _metadata_dir(self, digest: str) -> pathlib.Path:
        normalized = _sha256(digest)
        path = self.metadata_root / normalized
        self._require_within(path, self.metadata_root)
        return path

    @staticmethod
    def _require_within(path: pathlib.Path, root: pathlib.Path) -> None:
        try:
            path.resolve(strict=False).relative_to(root.resolve())
        except ValueError as exc:
            raise ArtifactPathError("artifact path escaped trusted root") from exc

    @staticmethod
    def _hash_file(path: pathlib.Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_BUFFER_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def _quarantine(
        self,
        temporary: pathlib.Path,
        *,
        expected: str | None,
        observed: str,
    ) -> pathlib.Path:
        expected_token = "none" if expected is None else _sha256(expected)
        observed_token = _sha256(observed)
        target = self.quarantine_root / (
            f"expected-{expected_token}--observed-{observed_token}.bin"
        )
        counter = 1
        while target.exists():
            target = self.quarantine_root / (
                f"expected-{expected_token}--observed-{observed_token}-{counter}.bin"
            )
            counter += 1
        os.replace(temporary, target)
        return target

    def _write_admission_record(self, record: ArtifactAdmissionRecord) -> pathlib.Path:
        metadata_dir = self._metadata_dir(record.artifact_sha256)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact_sha256": record.artifact_sha256,
            "size_bytes": record.size_bytes,
            "provenance_id": record.provenance_id,
            "source_id": record.source_id,
        }
        record_digest = canonical_digest(payload)
        target = metadata_dir / f"{record_digest}.json"
        self._require_within(target, metadata_dir)
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if target.exists():
            if target.read_bytes() != encoded:
                raise ArtifactIntegrityError(
                    "existing artifact admission metadata changed unexpectedly"
                )
            return target

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=metadata_dir,
            prefix=".record-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(encoded)
            temp_name = pathlib.Path(handle.name)
        os.replace(temp_name, target)
        return target

    def admit_file(
        self,
        source_path: pathlib.Path | str,
        *,
        expected_sha256: str | None = None,
        provenance_id: str | None = None,
        source_id: str | None = None,
    ) -> ArtifactAdmissionResult:
        source = pathlib.Path(source_path)
        if source.is_symlink():
            raise ArtifactPathError("artifact source cannot be a symlink")
        if not source.is_file():
            raise ArtifactPathError("artifact source must be a regular file")

        expected = None if expected_sha256 is None else _sha256(expected_sha256)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.temp_root,
            prefix="artifact-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = pathlib.Path(output.name)
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as input_handle:
                while True:
                    chunk = input_handle.read(_BUFFER_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

        observed = digest.hexdigest()
        if expected is not None and observed != expected:
            quarantine = self._quarantine(
                temporary,
                expected=expected,
                observed=observed,
            )
            raise ArtifactIntegrityError(
                "artifact SHA-256 mismatch; rejected bytes were quarantined at "
                f"{quarantine.name}"
            )

        target = self._object_path(observed)
        already_present = target.exists()
        if already_present:
            stored_digest, stored_size = self._hash_file(target)
            if stored_digest != observed or stored_size != size:
                self._quarantine(
                    temporary,
                    expected=observed,
                    observed=observed,
                )
                raise ArtifactIntegrityError(
                    "existing content-addressed artifact failed integrity verification"
                )
            temporary.unlink()
        else:
            os.replace(temporary, target)

        record = ArtifactAdmissionRecord(
            artifact_sha256=observed,
            size_bytes=size,
            provenance_id=provenance_id,
            source_id=source_id,
        )
        record_path = self._write_admission_record(record)
        return ArtifactAdmissionResult(
            artifact_sha256=observed,
            size_bytes=size,
            object_path=target,
            admission_record_path=record_path,
            already_present=already_present,
        )

    def verify(self, digest: str) -> pathlib.Path:
        target = self._object_path(digest)
        if target.is_symlink():
            raise ArtifactPathError("artifact object cannot be a symlink")
        if not target.is_file():
            raise ArtifactStoreError("artifact object is unavailable")
        observed, _ = self._hash_file(target)
        expected = _sha256(digest)
        if observed != expected:
            raise ArtifactIntegrityError("stored artifact failed verify-on-read")
        return target

    def read_bytes(self, digest: str) -> bytes:
        target = self.verify(digest)
        return target.read_bytes()

    def list_admission_records(self, digest: str) -> tuple[pathlib.Path, ...]:
        metadata_dir = self._metadata_dir(digest)
        if not metadata_dir.exists():
            return ()
        if metadata_dir.is_symlink():
            raise ArtifactPathError("artifact metadata directory cannot be a symlink")
        return tuple(
            sorted(
                path
                for path in metadata_dir.iterdir()
                if path.is_file() and not path.is_symlink() and path.suffix == ".json"
            )
        )

    def garbage_collection_candidates(
        self,
        references: ArtifactRetentionReferences,
    ) -> tuple[str, ...]:
        retained = set(references.referenced_sha256)
        candidates: list[str] = []
        for path in self.objects_root.iterdir():
            if path.is_symlink():
                raise ArtifactPathError("artifact object directory contains a symlink")
            if not path.is_file():
                continue
            try:
                digest = _sha256(path.name)
            except ValueError as exc:
                raise ArtifactPathError(
                    "artifact object directory contains an invalid object name"
                ) from exc
            if digest not in retained:
                candidates.append(digest)
        return tuple(sorted(candidates))
