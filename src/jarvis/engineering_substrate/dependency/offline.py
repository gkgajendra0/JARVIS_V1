"""Network-disabled candidate environment recreation from admitted wheel artifacts."""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass

import tomli_w

from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DependencyArtifact
from jarvis.engineering_substrate.dependency.broker import ResolvedPythonDependency
from jarvis.engineering_substrate.dependency.policy import (
    DependencyPolicyError,
    normalize_python_package_name,
)
from jarvis.engineering_substrate.sandbox import (
    SandboxMountBinding,
    SandboxRegistry,
)

UV_VERIFY_IMAGE = (
    "ghcr.io/astral-sh/uv:0.12.19-python3.11-trixie-slim"
    "@sha256:e8375931acd70cca124f409b4b80316f78dd9c6c55e2563795bed61495952ae4"
)


class OfflineVerificationError(RuntimeError):
    """Candidate recreation or inventory verification failed."""


@dataclass(frozen=True, slots=True)
class OfflineVerificationBundle:
    root: pathlib.Path
    canonical_lock_digest: str
    offline_lock_digest: str
    artifact_digests: tuple[str, ...]
    expected_inventory: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfflineCandidateResult:
    profile_id: str
    profile_version: int
    image: str
    canonical_lock_digest: str
    offline_lock_digest: str
    artifact_digests: tuple[str, ...]
    inventory: tuple[str, ...]
    verification_digest: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _wheel_sha256(raw_wheel: dict[str, object]) -> str:
    hashes = raw_wheel.get("hashes")
    if not isinstance(hashes, dict) or "sha256" not in hashes:
        raise OfflineVerificationError("offline pylock wheel lacks SHA-256")
    value = str(hashes["sha256"]).strip().casefold()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OfflineVerificationError("offline pylock wheel SHA-256 is invalid")
    return value


def _inventory_line(value: str) -> str:
    line = str(value).strip()
    if not line:
        raise OfflineVerificationError("candidate inventory contains an empty entry")
    if "==" not in line:
        raise OfflineVerificationError(
            "candidate inventory is not exact name==version evidence"
        )
    name, version = line.split("==", 1)
    normalized_name = normalize_python_package_name(name)
    normalized_version = version.strip()
    if not normalized_version:
        raise OfflineVerificationError("candidate inventory has an empty version")
    return f"{normalized_name}=={normalized_version}"


class OfflineVerificationBundleBuilder:
    """Derive a local-path pylock from the canonical lock without changing identities."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        self._artifact_store = artifact_store

    def build(
        self,
        resolved: ResolvedPythonDependency,
        artifacts: tuple[DependencyArtifact, ...],
        *,
        output_root: pathlib.Path | str,
    ) -> OfflineVerificationBundle:
        if not isinstance(resolved, ResolvedPythonDependency):
            raise TypeError("resolved must be a ResolvedPythonDependency")
        root = pathlib.Path(output_root)
        if root.exists() and root.is_symlink():
            raise OfflineVerificationError("verification bundle root cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        wheelhouse = root / "wheels"
        wheelhouse.mkdir(parents=True, exist_ok=True)

        canonical_bytes = resolved.lock_path.read_bytes()
        canonical_digest_value = _sha256_bytes(canonical_bytes)
        if canonical_digest_value != resolved.resolution.lock_digest:
            raise OfflineVerificationError("canonical pylock digest changed before verification")
        try:
            document = tomllib.loads(canonical_bytes.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise OfflineVerificationError("canonical pylock is invalid TOML") from exc

        artifact_by_digest: dict[str, DependencyArtifact] = {}
        for artifact in artifacts:
            if artifact.sha256 in artifact_by_digest:
                existing = artifact_by_digest[artifact.sha256]
                if existing != artifact:
                    raise OfflineVerificationError(
                        "one artifact digest maps to conflicting metadata"
                    )
            artifact_by_digest[artifact.sha256] = artifact

        packages = document.get("packages")
        if not isinstance(packages, list) or not packages:
            raise OfflineVerificationError("canonical pylock contains no packages")

        used_digests: list[str] = []
        used_names: dict[str, str] = {}
        for raw_package in packages:
            if not isinstance(raw_package, dict):
                raise OfflineVerificationError("canonical pylock package is invalid")
            if any(
                key in raw_package
                for key in ("vcs", "directory", "archive")
            ):
                raise OfflineVerificationError(
                    "offline verification refuses non-wheel package sources"
                )
            raw_package.pop("sdist", None)
            wheels = raw_package.get("wheels")
            if not isinstance(wheels, list) or not wheels:
                raise OfflineVerificationError(
                    "offline verification requires wheel-backed packages"
                )
            for raw_wheel in wheels:
                if not isinstance(raw_wheel, dict):
                    raise OfflineVerificationError("canonical wheel entry is invalid")
                digest = _wheel_sha256(raw_wheel)
                artifact = artifact_by_digest.get(digest)
                if artifact is None:
                    raise OfflineVerificationError(
                        "locked wheel is absent from admitted artifact evidence"
                    )
                filename = str(raw_wheel.get("name") or artifact.filename).strip()
                if filename != artifact.filename:
                    raise OfflineVerificationError(
                        "locked wheel filename disagrees with admitted artifact"
                    )
                previous_digest = used_names.get(filename)
                if previous_digest is not None and previous_digest != digest:
                    raise OfflineVerificationError(
                        "two artifact digests claim the same wheel filename"
                    )

                source = self._artifact_store.verify(digest)
                if source.stat().st_size != artifact.size_bytes:
                    raise OfflineVerificationError(
                        "admitted artifact size changed before offline verification"
                    )
                destination = wheelhouse / filename
                if destination.exists():
                    if destination.is_symlink():
                        raise OfflineVerificationError(
                            "offline wheelhouse contains a symlink"
                        )
                    if _sha256_bytes(destination.read_bytes()) != digest:
                        raise OfflineVerificationError(
                            "existing offline wheelhouse object has wrong digest"
                        )
                else:
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=wheelhouse,
                        prefix=".wheel-",
                        suffix=".tmp",
                        delete=False,
                    ) as output:
                        temporary = pathlib.Path(output.name)
                        with source.open("rb") as input_handle:
                            shutil.copyfileobj(input_handle, output, 1024 * 1024)
                    if _sha256_bytes(temporary.read_bytes()) != digest:
                        temporary.unlink(missing_ok=True)
                        raise OfflineVerificationError(
                            "artifact changed while materializing offline wheelhouse"
                        )
                    os.replace(temporary, destination)

                raw_wheel.pop("url", None)
                raw_wheel["path"] = f"wheels/{filename}"
                raw_wheel["name"] = filename
                used_digests.append(digest)
                used_names[filename] = digest

        expected = set(resolved.resolution.artifact_ids)
        if set(used_digests) != expected:
            raise OfflineVerificationError(
                "offline wheel set does not match canonical resolution artifact IDs"
            )

        offline_payload = tomli_w.dumps(document).encode("utf-8")
        offline_lock = root / "pylock.toml"
        temporary_lock = root / ".pylock.toml.tmp"
        temporary_lock.write_bytes(offline_payload)
        os.replace(temporary_lock, offline_lock)
        offline_digest = _sha256_bytes(offline_payload)

        return OfflineVerificationBundle(
            root=root,
            canonical_lock_digest=canonical_digest_value,
            offline_lock_digest=offline_digest,
            artifact_digests=tuple(sorted(expected)),
            expected_inventory=tuple(sorted(resolved.resolution.resolved_packages)),
        )


class OfflineCandidateVerifier:
    """Recreate and inspect a candidate venv using the network-off sandbox profile."""

    def __init__(
        self,
        *,
        sandbox_registry: SandboxRegistry,
        image: str = UV_VERIFY_IMAGE,
        runner: Runner = subprocess.run,
    ) -> None:
        if not isinstance(sandbox_registry, SandboxRegistry):
            raise TypeError("sandbox_registry must be a SandboxRegistry")
        self._sandbox = sandbox_registry
        self._image = str(image).strip()
        self._runner = runner
        if self._image != UV_VERIFY_IMAGE:
            raise ValueError("Phase-5D verification image must match the reviewed digest")

    def _run(
        self,
        *,
        mounts: tuple[SandboxMountBinding, ...],
        suffix: tuple[str, ...],
        cwd: pathlib.Path,
    ) -> subprocess.CompletedProcess[str]:
        launch = self._sandbox.build_launch(
            profile_id="dependency.verify.v1",
            image=self._image,
            mounts=mounts,
            trusted_suffix=suffix,
        )
        try:
            completed = self._runner(
                list(launch.command),
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=launch.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfflineVerificationError(
                "dependency verification sandbox did not complete"
            ) from exc
        if completed.returncode != 0:
            output = (completed.stdout + "\n" + completed.stderr).strip()
            raise OfflineVerificationError(
                "dependency verification sandbox rejected candidate: "
                + output[-2000:]
            )
        return completed

    def verify(
        self,
        bundle: OfflineVerificationBundle,
        *,
        candidate_dir: pathlib.Path | str,
        worktree: pathlib.Path | str,
    ) -> OfflineCandidateResult:
        if not isinstance(bundle, OfflineVerificationBundle):
            raise TypeError("bundle must be an OfflineVerificationBundle")
        candidate = pathlib.Path(candidate_dir)
        if candidate.exists() and candidate.is_symlink():
            raise OfflineVerificationError("candidate directory cannot be a symlink")
        candidate.mkdir(parents=True, exist_ok=True)
        candidate = candidate.resolve()

        worktree_path = pathlib.Path(worktree)
        if worktree_path.is_symlink() or not worktree_path.is_dir():
            raise OfflineVerificationError(
                "verification worktree must be a regular directory"
            )
        worktree_path = worktree_path.resolve()

        mounts = (
            SandboxMountBinding("artifacts_ro", bundle.root),
            SandboxMountBinding("candidate_rw", candidate),
            SandboxMountBinding("worktree_ro", worktree_path),
        )
        self._run(
            mounts=mounts,
            suffix=(
                "venv",
                "/candidate/.venv",
                "--python",
                "3.11",
                "--no-python-downloads",
                "--no-progress",
            ),
            cwd=candidate,
        )
        self._run(
            mounts=mounts,
            suffix=(
                "pip",
                "sync",
                "/artifacts/pylock.toml",
                "--python",
                "/candidate/.venv/bin/python",
                "--offline",
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--no-build",
                "--no-config",
                "--no-python-downloads",
                "--no-progress",
            ),
            cwd=candidate,
        )
        self._run(
            mounts=mounts,
            suffix=(
                "pip",
                "check",
                "--python",
                "/candidate/.venv/bin/python",
            ),
            cwd=candidate,
        )
        frozen = self._run(
            mounts=mounts,
            suffix=(
                "pip",
                "freeze",
                "--python",
                "/candidate/.venv/bin/python",
            ),
            cwd=candidate,
        )
        inventory = tuple(
            sorted(
                _inventory_line(line)
                for line in frozen.stdout.splitlines()
                if line.strip()
            )
        )
        expected = tuple(
            sorted(_inventory_line(item) for item in bundle.expected_inventory)
        )
        if inventory != expected:
            raise OfflineVerificationError(
                "candidate inventory differs from the canonical dependency resolution"
            )

        verification_digest = canonical_digest(
            {
                "profile_id": "dependency.verify.v1",
                "profile_version": 1,
                "image": self._image,
                "canonical_lock_digest": bundle.canonical_lock_digest,
                "offline_lock_digest": bundle.offline_lock_digest,
                "artifact_digests": list(bundle.artifact_digests),
                "inventory": list(inventory),
                "network": "none",
            }
        )
        return OfflineCandidateResult(
            profile_id="dependency.verify.v1",
            profile_version=1,
            image=self._image,
            canonical_lock_digest=bundle.canonical_lock_digest,
            offline_lock_digest=bundle.offline_lock_digest,
            artifact_digests=bundle.artifact_digests,
            inventory=inventory,
            verification_digest=verification_digest,
        )
