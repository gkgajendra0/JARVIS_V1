"""Governed Python dependency resolution and locked-wheel acquisition."""

from __future__ import annotations

import hashlib
import os
import pathlib
import tempfile
import urllib.request
from dataclasses import dataclass, replace

from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.contracts import (
    DependencyArtifact,
    DependencyEcosystem,
    DependencyRequirement,
    DependencyResolution,
    DistributionKind,
    SourceBuildPolicy,
)
from jarvis.engineering_substrate.dependency.policy import (
    DependencyPolicyError,
    DependencyResourceUnavailable,
    DependencySourcePolicy,
    DependencySourceRegistry,
    normalize_python_package_name,
)
from jarvis.engineering_substrate.dependency.pylock import (
    LockedWheel,
    ParsedPylock,
    inspect_pylock,
)
from jarvis.engineering_substrate.dependency.uv_adapter import (
    PythonResolutionEnvironment,
    UvAdapter,
)

_MAX_WHEEL_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ResolvedPythonDependency:
    requirement: DependencyRequirement
    resolution: DependencyResolution
    lock_path: pathlib.Path


class _SourceBoundRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, source: DependencySourcePolicy) -> None:
        self._source = source

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self._source.permits_artifact_url(newurl):
            raise DependencyPolicyError(
                "artifact redirect escaped the registered dependency source"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LockedWheelFetcher:
    """HTTPS-only fetcher bound to exact wheel URLs from a reviewed pylock."""

    def fetch(
        self,
        wheel: LockedWheel,
        *,
        source: DependencySourcePolicy,
        destination_dir: pathlib.Path,
    ) -> pathlib.Path:
        if not source.permits_artifact_url(wheel.url):
            raise DependencyPolicyError(
                "locked wheel URL is outside registered source policy"
            )
        destination_dir.mkdir(parents=True, exist_ok=True)
        opener = urllib.request.build_opener(_SourceBoundRedirectHandler(source))
        request = urllib.request.Request(
            wheel.url,
            headers={"User-Agent": "JARVIS-DependencyBroker/1"},
            method="GET",
        )
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination_dir,
            prefix=".wheel-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = pathlib.Path(output.name)
            digest = hashlib.sha256()
            size = 0
            try:
                with opener.open(request, timeout=30.0) as response:
                    final_url = response.geturl()
                    if not source.permits_artifact_url(final_url):
                        raise DependencyPolicyError(
                            "artifact response escaped registered source policy"
                        )
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > _MAX_WHEEL_BYTES:
                            raise DependencyPolicyError(
                                "locked wheel exceeds maximum acquisition size"
                            )
                        output.write(chunk)
                        digest.update(chunk)
            except Exception:
                output.flush()
                temporary.unlink(missing_ok=True)
                raise

        observed = digest.hexdigest()
        if observed != wheel.sha256:
            temporary.unlink(missing_ok=True)
            raise DependencyPolicyError("downloaded wheel SHA-256 mismatch")
        if wheel.size_bytes is not None and size != wheel.size_bytes:
            temporary.unlink(missing_ok=True)
            raise DependencyPolicyError("downloaded wheel size mismatch")
        return temporary


class DependencyBroker:
    """Typed broker; model output never becomes raw package-manager arguments."""

    def __init__(
        self,
        *,
        source_registry: DependencySourceRegistry,
        uv_adapter: UvAdapter,
        artifact_store: ArtifactStore,
        wheel_fetcher: LockedWheelFetcher | None = None,
        protected_main_root: pathlib.Path | str | None = None,
    ) -> None:
        if not isinstance(source_registry, DependencySourceRegistry):
            raise TypeError("source_registry must be a DependencySourceRegistry")
        if not isinstance(uv_adapter, UvAdapter):
            raise TypeError("uv_adapter must be a UvAdapter")
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        self._sources = source_registry
        self._uv = uv_adapter
        self._artifacts = artifact_store
        self._fetcher = wheel_fetcher or LockedWheelFetcher()
        self._protected_main_root = (
            None
            if protected_main_root is None
            else pathlib.Path(protected_main_root).resolve()
        )

    def _workspace(self, value: pathlib.Path | str) -> pathlib.Path:
        path = pathlib.Path(value)
        if path.is_symlink() or not path.is_dir():
            raise DependencyPolicyError(
                "dependency workspace must be a regular isolated directory"
            )
        resolved = path.resolve()
        if self._protected_main_root is not None and (
            resolved == self._protected_main_root
            or self._protected_main_root in resolved.parents
        ):
            raise DependencyPolicyError(
                "dependency broker cannot operate inside protected main"
            )
        return resolved

    def _normalize_requirement(
        self,
        requirement: DependencyRequirement,
    ) -> tuple[DependencyRequirement, DependencySourcePolicy]:
        if not isinstance(requirement, DependencyRequirement):
            raise TypeError("requirement must be a DependencyRequirement")
        if requirement.ecosystem is not DependencyEcosystem.PYTHON:
            raise DependencyPolicyError("Phase-5 v1 supports Python dependencies only")
        if requirement.source_build_policy is not SourceBuildPolicy.DENY:
            raise DependencyPolicyError("source build policy must remain deny")
        if len(requirement.registered_source_ids) != 1:
            raise DependencyPolicyError(
                "Phase-5 v1 requires exactly one registered dependency source"
            )
        source = self._sources.require(requirement.registered_source_ids[0])
        if source.required_secret_scope is not None:
            raise DependencyResourceUnavailable(
                "private dependency sources require Phase-5E SecretBroker"
            )

        constraint = requirement.version_constraint
        lowered = constraint.casefold()
        if (
            "\n" in constraint
            or "\r" in constraint
            or "://" in constraint
            or "git+" in lowered
            or "file:" in lowered
            or "@" in constraint
            or ".." in constraint
            or "\\" in constraint
        ):
            raise DependencyPolicyError(
                "direct URL, VCS, path and multiline dependency inputs are denied"
            )
        normalized_name = normalize_python_package_name(requirement.package_name)
        return replace(requirement, package_name=normalized_name), source

    @staticmethod
    def _write_requirement_file(
        workspace: pathlib.Path,
        requirement: DependencyRequirement,
    ) -> pathlib.Path:
        state_dir = workspace / ".jarvis-dependency"
        state_dir.mkdir(parents=True, exist_ok=True)
        requirement_file = state_dir / "requirements.in"
        text = f"{requirement.package_name}{requirement.version_constraint}\n"
        temporary = state_dir / ".requirements.in.tmp"
        temporary.write_text(text, encoding="utf-8", newline="")
        os.replace(temporary, requirement_file)
        return requirement_file

    def resolve_python(
        self,
        requirement: DependencyRequirement,
        *,
        workspace: pathlib.Path | str,
        environment: PythonResolutionEnvironment,
    ) -> ResolvedPythonDependency:
        normalized, source = self._normalize_requirement(requirement)
        root = self._workspace(workspace)
        requirement_file = self._write_requirement_file(root, normalized)
        output_lock = root / ".jarvis-dependency" / "pylock.toml"
        lock_path = self._uv.compile_lock(
            workspace=root,
            requirement_file=requirement_file,
            output_lock=output_lock,
            source=source,
            environment=environment,
        )
        parsed = inspect_pylock(lock_path, source=source)
        resolution = self._resolution_from_lock(
            normalized,
            parsed,
            environment=environment,
        )
        return ResolvedPythonDependency(
            requirement=normalized,
            resolution=resolution,
            lock_path=lock_path,
        )

    def _resolution_from_lock(
        self,
        requirement: DependencyRequirement,
        parsed: ParsedPylock,
        *,
        environment: PythonResolutionEnvironment,
    ) -> DependencyResolution:
        return DependencyResolution(
            resolution_id=f"uv:{requirement.requirement_id}:{parsed.lock_sha256[:16]}",
            requirement_id=requirement.requirement_id,
            resolver_id=self._uv.adapter_id,
            resolver_version=self._uv.release_policy.version,
            resolver_digest=self._uv.binary_registration.executable_sha256,
            resolved_packages=parsed.resolved_packages,
            artifact_ids=tuple(
                dict.fromkeys(wheel.sha256 for wheel in parsed.wheels)
            ),
            dependency_graph_digest=parsed.graph_digest,
            lock_format="pylock.toml",
            lock_version=parsed.lock_version,
            lock_digest=parsed.lock_sha256,
            platform_constraints=(
                f"python=={environment.python_version}",
                environment.python_platform,
            ),
            change_id=requirement.change_id,
            work_id=requirement.work_id,
        )

    def inspect_lock(
        self,
        resolved: ResolvedPythonDependency,
    ) -> ParsedPylock:
        if not isinstance(resolved, ResolvedPythonDependency):
            raise TypeError("resolved must be a ResolvedPythonDependency")
        _, source = self._normalize_requirement(resolved.requirement)
        parsed = inspect_pylock(resolved.lock_path, source=source)
        if parsed.lock_sha256 != resolved.resolution.lock_digest:
            raise DependencyPolicyError("pylock digest changed after resolution")
        expected_artifacts = tuple(
            dict.fromkeys(wheel.sha256 for wheel in parsed.wheels)
        )
        if expected_artifacts != resolved.resolution.artifact_ids:
            raise DependencyPolicyError("pylock artifact set changed after resolution")
        return parsed

    def acquire_locked_wheels(
        self,
        resolved: ResolvedPythonDependency,
        *,
        staging_dir: pathlib.Path | str,
    ) -> tuple[DependencyArtifact, ...]:
        parsed = self.inspect_lock(resolved)
        _, source = self._normalize_requirement(resolved.requirement)
        staging = pathlib.Path(staging_dir)
        if staging.is_symlink():
            raise DependencyPolicyError("staging directory cannot be a symlink")
        staging.mkdir(parents=True, exist_ok=True)
        staging = staging.resolve()
        artifacts: list[DependencyArtifact] = []

        for wheel in parsed.wheels:
            temporary = self._fetcher.fetch(
                wheel,
                source=source,
                destination_dir=staging,
            )
            try:
                admitted = self._artifacts.admit_file(
                    temporary,
                    expected_sha256=wheel.sha256,
                    source_id=source.source_id,
                )
            finally:
                temporary.unlink(missing_ok=True)
            artifacts.append(
                DependencyArtifact(
                    artifact_id=admitted.artifact_sha256,
                    package_name=wheel.package_name,
                    package_version=wheel.package_version,
                    filename=wheel.filename,
                    distribution_kind=DistributionKind.WHEEL,
                    size_bytes=admitted.size_bytes,
                    sha256=admitted.artifact_sha256,
                    source_id=source.source_id,
                )
            )

        return tuple(artifacts)
