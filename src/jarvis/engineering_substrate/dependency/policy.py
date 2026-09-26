"""Trusted dependency-source and uv release policy for Phase 5C."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from jarvis.engineering_substrate.canonical import canonical_digest

_PEP503_NORMALIZE = re.compile(r"[-_.]+")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class DependencyPolicyError(ValueError):
    """A dependency/source request violates the reviewed Phase-5 policy."""


class DependencyResourceUnavailable(RuntimeError):
    """A required trusted dependency resource is absent or mismatched."""


def normalize_python_package_name(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise DependencyPolicyError("package name must not be empty")
    normalized = _PEP503_NORMALIZE.sub("-", text).casefold()
    if not normalized or normalized.startswith("-") or normalized.endswith("-"):
        raise DependencyPolicyError("package name cannot be normalized safely")
    return normalized


def _sha256(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not _SHA256_HEX.fullmatch(normalized):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def _https_url(value: str, *, field: str) -> str:
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise DependencyPolicyError(f"{field} must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise DependencyPolicyError(f"{field} must not contain embedded credentials")
    return text


@dataclass(frozen=True, slots=True)
class DependencySourcePolicy:
    source_id: str
    index_url: str
    allowed_artifact_hosts: tuple[str, ...]
    required_secret_scope: str | None = None

    def __post_init__(self) -> None:
        source_id = str(self.source_id).strip().casefold()
        if not source_id:
            raise ValueError("source_id must not be empty")
        index_url = _https_url(self.index_url, field="index_url")
        hosts = tuple(
            dict.fromkeys(str(item).strip().casefold() for item in self.allowed_artifact_hosts)
        )
        if not hosts or any(not item or "/" in item or ":" in item for item in hosts):
            raise ValueError("allowed_artifact_hosts must contain bare hostnames")
        secret_scope = (
            None
            if self.required_secret_scope is None
            else str(self.required_secret_scope).strip().casefold() or None
        )
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "index_url", index_url)
        object.__setattr__(self, "allowed_artifact_hosts", hosts)
        object.__setattr__(self, "required_secret_scope", secret_scope)

    def permits_artifact_url(self, url: str) -> bool:
        parsed = urlparse(_https_url(url, field="artifact_url"))
        return parsed.hostname is not None and parsed.hostname.casefold() in set(
            self.allowed_artifact_hosts
        )


class DependencySourceRegistry:
    """Exact source registry; a Phase-5 v1 resolution uses one source policy."""

    def __init__(self, sources: tuple[DependencySourcePolicy, ...] = ()) -> None:
        self._sources: dict[str, DependencySourcePolicy] = {}
        for source in sources:
            self.register(source)

    def register(self, source: DependencySourcePolicy) -> None:
        if not isinstance(source, DependencySourcePolicy):
            raise TypeError("source must be a DependencySourcePolicy")
        if source.source_id in self._sources:
            raise DependencyPolicyError(
                f"dependency source already registered: {source.source_id}"
            )
        self._sources[source.source_id] = source

    def require(self, source_id: str) -> DependencySourcePolicy:
        key = str(source_id).strip().casefold()
        try:
            return self._sources[key]
        except KeyError as exc:
            raise DependencyPolicyError(
                f"unregistered dependency source: {key}"
            ) from exc

    def all(self) -> tuple[DependencySourcePolicy, ...]:
        return tuple(self._sources[key] for key in sorted(self._sources))


PYPI_PUBLIC_V1 = DependencySourcePolicy(
    source_id="pypi.public.v1",
    index_url="https://pypi.org/simple",
    allowed_artifact_hosts=("files.pythonhosted.org",),
)


def default_dependency_source_registry() -> DependencySourceRegistry:
    return DependencySourceRegistry((PYPI_PUBLIC_V1,))


@dataclass(frozen=True, slots=True)
class UvReleasePolicy:
    version: str
    release_commit_sha: str
    release_asset_name: str
    release_asset_sha256: str
    repository: str = "astral-sh/uv"
    release_immutable: bool = True
    release_commit_verified: bool = True
    github_artifact_attestations: bool = True
    windows_authenticode_expected: bool = True

    def __post_init__(self) -> None:
        version = str(self.version).strip()
        commit = str(self.release_commit_sha).strip().casefold()
        asset = str(self.release_asset_name).strip()
        repository = str(self.repository).strip().casefold()
        if not version:
            raise ValueError("uv release version must not be empty")
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            raise ValueError("release_commit_sha must be a 40-character Git SHA")
        if not asset or "/" in asset or "\\" in asset:
            raise ValueError("release_asset_name must be one file name")
        if repository != "astral-sh/uv":
            raise ValueError("Phase-5 uv source repository must remain astral-sh/uv")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "release_commit_sha", commit)
        object.__setattr__(
            self,
            "release_asset_sha256",
            _sha256(self.release_asset_sha256, field="release_asset_sha256"),
        )
        object.__setattr__(self, "release_asset_name", asset)
        object.__setattr__(self, "repository", repository)
        if not (
            self.release_immutable
            and self.release_commit_verified
            and self.github_artifact_attestations
            and self.windows_authenticode_expected
        ):
            raise ValueError("reviewed uv release trust signals must all be present")

    @property
    def policy_digest(self) -> str:
        return canonical_digest(
            {
                "version": self.version,
                "release_commit_sha": self.release_commit_sha,
                "release_asset_name": self.release_asset_name,
                "release_asset_sha256": self.release_asset_sha256,
                "repository": self.repository,
                "release_immutable": self.release_immutable,
                "release_commit_verified": self.release_commit_verified,
                "github_artifact_attestations": self.github_artifact_attestations,
                "windows_authenticode_expected": self.windows_authenticode_expected,
            }
        )


UV_WINDOWS_X64_0_12_19 = UvReleasePolicy(
    version="0.12.19",
    release_commit_sha="bea138450f0e620a4ce5765b0e38cff7b9f0799f",
    release_asset_name="uv-x86_64-pc-windows-msvc.zip",
    release_asset_sha256=(
        "6dbb02d79e419522f1c500f0adb1cddcff0cda7d59b0d66ea7f5e3b4a1b2f5f0"
    ),
)
