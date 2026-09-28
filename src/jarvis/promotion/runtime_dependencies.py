"""Release-local dependency overlays for governed Phase-9 capabilities.

The overlay is built entirely from Phase-5 content-addressed artifacts and a canonical
lock that was already bound to the same EngineeringChange. Protected main, the shared
JARVIS virtual environment, and the detached release worktree are never mutated.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pathlib
import shutil
import sys
import tempfile

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import (
    DEPENDENCY_RESOLUTION_KIND,
    MANIFEST_KIND,
)
from jarvis.engineering_substrate.dependency.policy import (
    PYPI_PUBLIC_V1,
    DependencyResourceUnavailable,
)
from jarvis.engineering_substrate.dependency.pylock import inspect_pylock
from jarvis.engineering_substrate.dependency.runtime import build_runtime_uv_adapter
from jarvis.engineering_substrate.dependency.uv_adapter import UvAdapter
from jarvis.promotion.models import PromotionAttempt
from jarvis.promotion.release import ReleaseRecord, default_deployment_root

_MANIFEST_FILE = "runtime-dependencies.json"
_SITE_PACKAGES = "site-packages"


class ReleaseDependencyError(ChangeConflict):
    pass


def default_runtime_dependency_root() -> pathlib.Path:
    root = default_deployment_root().parent / "runtime-dependencies"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_sha(value: str) -> str:
    sha = str(value).strip().casefold()
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        raise ReleaseDependencyError("runtime dependency release SHA is invalid")
    return sha


def _file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: pathlib.Path) -> str:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseDependencyError(
                "runtime dependency overlay contains a symlink"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    return canonical_digest(entries)


def _validate_overlay_names(overlay: pathlib.Path) -> None:
    blocked = {item.casefold() for item in sys.stdlib_module_names}
    blocked.add("jarvis")
    for child in overlay.iterdir():
        if child.is_symlink():
            raise ReleaseDependencyError(
                "runtime dependency overlay contains a symlink"
            )
        name = child.name
        lowered = name.casefold()
        if lowered.endswith(".pth"):
            raise ReleaseDependencyError(
                "runtime dependency overlay contains executable .pth startup logic"
            )
        if lowered.endswith((".dist-info", ".data")):
            continue
        module_name = lowered[:-3] if lowered.endswith(".py") else lowered
        if module_name in blocked:
            raise ReleaseDependencyError(
                "runtime dependency overlay would shadow protected module: "
                + module_name
            )


def _existing_overlay(
    *,
    release_sha: str,
    expected_change_id: str | None = None,
    expected_binding_digest: str | None = None,
) -> pathlib.Path | None:
    target = default_runtime_dependency_root() / _safe_sha(release_sha)
    manifest_path = target / _MANIFEST_FILE
    overlay = target / _SITE_PACKAGES
    if not target.exists():
        return None
    if (
        target.is_symlink()
        or not target.is_dir()
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
        or overlay.is_symlink()
        or not overlay.is_dir()
    ):
        raise ReleaseDependencyError("runtime dependency overlay is malformed")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseDependencyError("runtime dependency manifest is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "release_dependency_overlay.v1"
    ):
        raise ReleaseDependencyError("runtime dependency manifest schema mismatch")
    if payload.get("release_sha") != release_sha:
        raise ReleaseDependencyError("runtime dependency overlay release mismatch")
    if (
        expected_change_id is not None
        and payload.get("change_id") != expected_change_id
    ):
        raise ReleaseDependencyError("runtime dependency overlay change mismatch")
    if (
        expected_binding_digest is not None
        and payload.get("binding_digest") != expected_binding_digest
    ):
        return None
    if payload.get("overlay_digest") != _tree_digest(overlay):
        raise ReleaseDependencyError("runtime dependency overlay integrity mismatch")
    _validate_overlay_names(overlay)
    return overlay


def runtime_dependency_overlay(release_sha: str) -> pathlib.Path | None:
    """Return a verified optional release overlay."""

    return _existing_overlay(release_sha=_safe_sha(release_sha))


def activate_runtime_dependency_overlay(release_sha: str) -> pathlib.Path | None:
    """Append a verified overlay after the normal interpreter/site-packages paths."""

    overlay = runtime_dependency_overlay(release_sha)
    if overlay is None:
        return None
    value = str(overlay)
    if value not in sys.path:
        sys.path.append(value)
    return overlay


class ReleaseDependencyMaterializer:
    def __init__(
        self,
        changes: ChangeStore,
        *,
        artifacts: ArtifactStore | None = None,
        uv: UvAdapter | None = None,
    ) -> None:
        self._changes = changes
        self._artifacts = artifacts or ArtifactStore()
        self._uv = uv

    def _uv_adapter(self) -> UvAdapter:
        if self._uv is None:
            self._uv = build_runtime_uv_adapter()
        return self._uv

    def materialize(
        self,
        *,
        change_id: str,
        release_sha: str,
    ) -> pathlib.Path | None:
        change = self._changes.require(str(change_id).strip())
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        ):
            return None
        manifest = self._changes.latest_artifact(change.change_id, MANIFEST_KIND)
        if manifest is None:
            return None
        resolution_ids = tuple(
            str(item).strip()
            for item in manifest.payload.get("dependency_resolution_ids", ())
            if str(item).strip()
        )
        resolution_digests = tuple(
            str(item).strip().casefold()
            for item in manifest.payload.get("dependency_resolution_digests", ())
            if str(item).strip()
        )
        if not resolution_ids:
            return None
        if len(resolution_ids) != len(resolution_digests):
            raise ReleaseDependencyError("manifest dependency bindings are malformed")
        binding_digest = canonical_digest(
            {
                "manifest_artifact_id": manifest.artifact_id,
                "manifest_artifact_digest": manifest.digest,
                "resolution_ids": list(resolution_ids),
                "resolution_digests": list(resolution_digests),
            }
        )
        sha = _safe_sha(release_sha)
        existing = _existing_overlay(
            release_sha=sha,
            expected_change_id=change.change_id,
            expected_binding_digest=binding_digest,
        )
        if existing is not None:
            return existing

        all_resolution_artifacts = self._changes.list_artifacts(
            change.change_id,
            kind=DEPENDENCY_RESOLUTION_KIND,
        )
        by_id: dict[str, ChangeArtifact] = {}
        for artifact in all_resolution_artifacts:
            resolution_id = str(artifact.payload.get("resolution_id") or "").strip()
            if resolution_id:
                by_id[resolution_id] = artifact

        base = default_runtime_dependency_root()
        staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{sha}-", dir=base)).resolve()
        wheelhouse = staging / "wheels"
        overlay = staging / _SITE_PACKAGES
        wheelhouse.mkdir()
        overlay.mkdir()
        package_hashes: dict[tuple[str, str], set[str]] = {}
        runtime_bindings: list[dict[str, object]] = []
        used_filenames: dict[str, str] = {}
        try:
            for resolution_id, expected_digest in zip(
                resolution_ids,
                resolution_digests,
                strict=True,
            ):
                artifact = by_id.get(resolution_id)
                if artifact is None:
                    raise ReleaseDependencyError(
                        f"runtime dependency resolution is missing: {resolution_id}"
                    )
                if artifact.payload.get("resolution_digest") != expected_digest:
                    raise ReleaseDependencyError(
                        f"runtime dependency resolution is stale: {resolution_id}"
                    )
                lock_digest = (
                    str(artifact.payload.get("lock_digest") or "").strip().casefold()
                )
                lock_artifact_id = (
                    str(artifact.payload.get("lock_artifact_id") or "")
                    .strip()
                    .casefold()
                )
                if not lock_artifact_id or lock_artifact_id != lock_digest:
                    raise ReleaseDependencyError(
                        "runtime dependency resolution has no canonical lock artifact"
                    )
                lock_source = self._artifacts.verify(lock_artifact_id)
                lock_path = staging / f"{resolution_id.replace(':', '_')}.pylock.toml"
                shutil.copyfile(lock_source, lock_path)
                parsed = inspect_pylock(lock_path, source=PYPI_PUBLIC_V1)
                if parsed.lock_sha256 != lock_digest:
                    raise ReleaseDependencyError(
                        "runtime dependency lock digest changed"
                    )
                expected_artifacts = tuple(
                    str(item).strip().casefold()
                    for item in artifact.payload.get("artifact_ids", ())
                    if str(item).strip()
                )
                parsed_artifacts = tuple(
                    dict.fromkeys(item.sha256 for item in parsed.wheels)
                )
                if set(expected_artifacts) != set(parsed_artifacts):
                    raise ReleaseDependencyError(
                        "runtime dependency wheel set differs from bound resolution"
                    )
                for wheel in parsed.wheels:
                    source = self._artifacts.verify(wheel.sha256)
                    previous = used_filenames.get(wheel.filename)
                    if previous is not None and previous != wheel.sha256:
                        raise ReleaseDependencyError(
                            "two runtime wheels claim one filename"
                        )
                    destination = wheelhouse / wheel.filename
                    if not destination.exists():
                        shutil.copyfile(source, destination)
                    if _file_sha256(destination) != wheel.sha256:
                        raise ReleaseDependencyError(
                            "runtime wheel changed while materializing"
                        )
                    used_filenames[wheel.filename] = wheel.sha256
                    package_hashes.setdefault(
                        (wheel.package_name, wheel.package_version),
                        set(),
                    ).add(wheel.sha256)
                runtime_bindings.append(
                    {
                        "resolution_id": resolution_id,
                        "resolution_digest": expected_digest,
                        "lock_digest": lock_digest,
                        "artifact_ids": sorted(expected_artifacts),
                    }
                )

            requirements = staging / "requirements.txt"
            lines: list[str] = []
            for (name, version), hashes in sorted(package_hashes.items()):
                try:
                    installed_version = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    installed_version = None
                if installed_version is not None and installed_version != version:
                    raise ReleaseDependencyError(
                        "runtime dependency conflicts with an existing JARVIS "
                        f"distribution: {name} installed={installed_version} "
                        f"requested={version}"
                    )
                suffix = " ".join(
                    f"--hash=sha256:{digest}" for digest in sorted(hashes)
                )
                lines.append(f"{name}=={version} {suffix}".rstrip())
            if not lines:
                raise ReleaseDependencyError(
                    "runtime dependency requirements are empty"
                )
            requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")

            try:
                self._uv_adapter().sync_target(
                    workspace=staging,
                    requirements_file=requirements,
                    wheelhouse=wheelhouse,
                    target=overlay,
                )
            except DependencyResourceUnavailable as exc:
                raise ReleaseDependencyError(str(exc)) from exc

            _validate_overlay_names(overlay)
            overlay_digest = _tree_digest(overlay)
            payload = {
                "schema": "release_dependency_overlay.v1",
                "release_sha": sha,
                "change_id": change.change_id,
                "manifest_artifact_id": manifest.artifact_id,
                "manifest_artifact_digest": manifest.digest,
                "binding_digest": binding_digest,
                "runtime_bindings": runtime_bindings,
                "overlay_digest": overlay_digest,
            }
            (staging / _MANIFEST_FILE).write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            target = base / sha
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
            staging = target
            verified = _existing_overlay(
                release_sha=sha,
                expected_change_id=change.change_id,
                expected_binding_digest=binding_digest,
            )
            if verified is None:
                raise ReleaseDependencyError(
                    "runtime dependency overlay failed post-write verification"
                )
            return verified
        finally:
            if (
                staging.exists()
                and staging.parent == base
                and staging.name.startswith(".")
            ):
                shutil.rmtree(staging, ignore_errors=True)


def prepare_phase9_release_dependencies(
    changes: ChangeStore,
    attempt: PromotionAttempt,
    release: ReleaseRecord,
) -> pathlib.Path | None:
    if attempt.change_id != changes.require(attempt.change_id).change_id:
        raise ReleaseDependencyError("promotion attempt change identity is invalid")
    if release.promotion_attempt_id != attempt.attempt_id:
        raise ReleaseDependencyError("release dependency promotion identity mismatch")
    return ReleaseDependencyMaterializer(changes).materialize(
        change_id=attempt.change_id,
        release_sha=release.release_sha,
    )
