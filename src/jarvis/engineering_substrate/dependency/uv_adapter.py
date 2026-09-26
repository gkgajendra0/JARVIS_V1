"""Pinned uv adapter with exact binary identity and fixed argv construction."""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.engineering_substrate.dependency.policy import (
    DependencyPolicyError,
    DependencyResourceUnavailable,
    DependencySourcePolicy,
    UvReleasePolicy,
)

_UV_VERSION_OUTPUT = re.compile(r"^uv\s+([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)")
_ALLOWED_PYTHON_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
_ALLOWED_PLATFORM = frozenset(
    {
        "x86_64-pc-windows-msvc",
        "x86_64-unknown-linux-gnu",
    }
)


@dataclass(frozen=True, slots=True)
class PythonResolutionEnvironment:
    python_version: str
    python_platform: str

    def __post_init__(self) -> None:
        version = str(self.python_version).strip()
        platform = str(self.python_platform).strip().casefold()
        if not _ALLOWED_PYTHON_VERSION.fullmatch(version):
            raise DependencyPolicyError("python_version must be major.minor")
        if platform not in _ALLOWED_PLATFORM:
            raise DependencyPolicyError("python_platform is not registered")
        object.__setattr__(self, "python_version", version)
        object.__setattr__(self, "python_platform", platform)


@dataclass(frozen=True, slots=True)
class UvBinaryRegistration:
    executable_path: pathlib.Path
    version: str
    executable_sha256: str
    release_commit_sha: str
    release_asset_sha256: str
    release_policy_digest: str

    def __post_init__(self) -> None:
        path = pathlib.Path(self.executable_path)
        version = str(self.version).strip()
        object.__setattr__(self, "executable_path", path)
        object.__setattr__(self, "version", version)
        for field_name in (
            "executable_sha256",
            "release_asset_sha256",
            "release_policy_digest",
        ):
            value = str(getattr(self, field_name)).strip().casefold()
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"{field_name} must be a SHA-256 hex digest")
            object.__setattr__(self, field_name, value)
        commit = str(self.release_commit_sha).strip().casefold()
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            raise ValueError("release_commit_sha must be a 40-character Git SHA")
        object.__setattr__(self, "release_commit_sha", commit)


Runner = Callable[..., subprocess.CompletedProcess[str]]


class UvAdapter:
    """Trusted uv invocation boundary; callers cannot supply arbitrary uv flags."""

    adapter_id = "uv"

    def __init__(
        self,
        *,
        release_policy: UvReleasePolicy,
        binary_registration: UvBinaryRegistration,
        runner: Runner = subprocess.run,
    ) -> None:
        if not isinstance(release_policy, UvReleasePolicy):
            raise TypeError("release_policy must be a UvReleasePolicy")
        if not isinstance(binary_registration, UvBinaryRegistration):
            raise TypeError("binary_registration must be a UvBinaryRegistration")
        self.release_policy = release_policy
        self.binary_registration = binary_registration
        self._runner = runner

    @staticmethod
    def _hash_file(path: pathlib.Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def verify_trust(self) -> None:
        registration = self.binary_registration
        policy = self.release_policy
        path = registration.executable_path
        if path.is_symlink() or not path.is_file():
            raise DependencyResourceUnavailable(
                "registered uv executable is missing or is a symlink"
            )
        if registration.version != policy.version:
            raise DependencyResourceUnavailable("registered uv version is not pinned")
        if registration.release_commit_sha != policy.release_commit_sha:
            raise DependencyResourceUnavailable(
                "registered uv release commit does not match reviewed policy"
            )
        if registration.release_asset_sha256 != policy.release_asset_sha256:
            raise DependencyResourceUnavailable(
                "registered uv release artifact does not match reviewed policy"
            )
        if registration.release_policy_digest != policy.policy_digest:
            raise DependencyResourceUnavailable(
                "registered uv policy digest does not match reviewed policy"
            )
        observed_digest = self._hash_file(path)
        if observed_digest != registration.executable_sha256:
            raise DependencyResourceUnavailable(
                "registered uv executable SHA-256 does not match"
            )

        try:
            completed = self._runner(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15.0,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DependencyResourceUnavailable(
                "registered uv executable cannot be verified"
            ) from exc
        if completed.returncode != 0:
            raise DependencyResourceUnavailable("uv --version verification failed")
        match = _UV_VERSION_OUTPUT.match(completed.stdout.strip())
        if match is None or match.group(1) != policy.version:
            raise DependencyResourceUnavailable(
                "uv runtime version does not match reviewed release"
            )

    @staticmethod
    def _trusted_path(
        workspace: pathlib.Path,
        path: pathlib.Path | str,
        *,
        field: str,
    ) -> pathlib.Path:
        root = workspace.resolve()
        candidate = pathlib.Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise DependencyPolicyError(
                f"{field} must remain inside workspace"
            ) from exc
        if candidate.exists() and candidate.is_symlink():
            raise DependencyPolicyError(f"{field} cannot be a symlink")
        return resolved

    def build_compile_command(
        self,
        *,
        workspace: pathlib.Path,
        requirement_file: pathlib.Path | str,
        output_lock: pathlib.Path | str,
        source: DependencySourcePolicy,
        environment: PythonResolutionEnvironment,
    ) -> tuple[str, ...]:
        requirement = self._trusted_path(
            workspace,
            requirement_file,
            field="requirement_file",
        )
        output = self._trusted_path(workspace, output_lock, field="output_lock")
        return (
            str(self.binary_registration.executable_path),
            "pip",
            "compile",
            str(requirement),
            "--output-file",
            str(output),
            "--format",
            "pylock.toml",
            "--generate-hashes",
            "--only-binary",
            ":all:",
            "--no-config",
            "--no-python-downloads",
            "--no-progress",
            "--default-index",
            source.index_url,
            "--index-strategy",
            "first-index",
            "--python-version",
            environment.python_version,
            "--python-platform",
            environment.python_platform,
        )

    def compile_lock(
        self,
        *,
        workspace: pathlib.Path,
        requirement_file: pathlib.Path | str,
        output_lock: pathlib.Path | str,
        source: DependencySourcePolicy,
        environment: PythonResolutionEnvironment,
        timeout_seconds: float = 180.0,
    ) -> pathlib.Path:
        self.verify_trust()
        command = self.build_compile_command(
            workspace=workspace,
            requirement_file=requirement_file,
            output_lock=output_lock,
            source=source,
            environment=environment,
        )
        root = pathlib.Path(workspace).resolve()
        output = self._trusted_path(root, output_lock, field="output_lock")
        try:
            completed = self._runner(
                list(command),
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(float(timeout_seconds), 300.0),
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DependencyResourceUnavailable("uv lock resolution failed") from exc
        if completed.returncode != 0:
            diagnostic = (completed.stdout + "\n" + completed.stderr).strip()
            raise DependencyResourceUnavailable(
                "uv lock resolution failed: " + diagnostic[-2000:]
            )
        if output.is_symlink() or not output.is_file():
            raise DependencyResourceUnavailable(
                "uv reported success without a pylock.toml output"
            )
        return output
