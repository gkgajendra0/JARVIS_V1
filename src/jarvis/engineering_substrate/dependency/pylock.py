"""Strict PEP-751 pylock.toml inspection for wheel-only Phase-5 acquisition."""

from __future__ import annotations

import hashlib
import pathlib
import tomllib
from dataclasses import dataclass
from typing import Any

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.dependency.policy import (
    DependencyPolicyError,
    DependencySourcePolicy,
    normalize_python_package_name,
)


@dataclass(frozen=True, slots=True)
class LockedWheel:
    package_name: str
    package_version: str
    filename: str
    url: str
    sha256: str
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class ParsedPylock:
    lock_version: str
    created_by: str
    lock_sha256: str
    resolved_packages: tuple[str, ...]
    graph_digest: str
    wheels: tuple[LockedWheel, ...]


def _sha256(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise DependencyPolicyError(f"{field} must contain a SHA-256 hex digest")
    return normalized


def _package_dependencies(package: dict[str, Any]) -> tuple[str, ...]:
    raw = package.get("dependencies") or []
    if not isinstance(raw, list):
        raise DependencyPolicyError("pylock package dependencies must be a list")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or "name" not in item:
            raise DependencyPolicyError("pylock dependency entries require a name")
        names.append(normalize_python_package_name(str(item["name"])))
    return tuple(sorted(dict.fromkeys(names)))


def inspect_pylock(
    path: pathlib.Path | str,
    *,
    source: DependencySourcePolicy,
) -> ParsedPylock:
    lock_path = pathlib.Path(path)
    if lock_path.is_symlink() or not lock_path.is_file():
        raise DependencyPolicyError("pylock must be a regular non-symlink file")
    payload = lock_path.read_bytes()
    try:
        document = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DependencyPolicyError("pylock contains invalid TOML") from exc

    lock_version = str(document.get("lock-version") or "").strip()
    if lock_version != "1.0":
        raise DependencyPolicyError("pylock lock-version must be 1.0")
    created_by = str(document.get("created-by") or "").strip()
    if not created_by.casefold().startswith("uv"):
        raise DependencyPolicyError("pylock must be produced by the trusted uv adapter")

    raw_packages = document.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise DependencyPolicyError("pylock must contain packages")

    resolved: list[str] = []
    wheels: list[LockedWheel] = []
    graph: list[dict[str, object]] = []

    for package in raw_packages:
        if not isinstance(package, dict):
            raise DependencyPolicyError("pylock package entries must be tables")
        if any(key in package for key in ("vcs", "directory", "archive")):
            raise DependencyPolicyError(
                "VCS, directory and direct archive dependencies are denied"
            )

        name = normalize_python_package_name(str(package.get("name") or ""))
        version = str(package.get("version") or "").strip()
        if not version:
            raise DependencyPolicyError("wheel-backed pylock package requires version")
        package_index = package.get("index")
        if package_index is not None:
            normalized_index = str(package_index).rstrip("/")
            if normalized_index != source.index_url.rstrip("/"):
                raise DependencyPolicyError(
                    "pylock package index does not match registered source policy"
                )

        raw_wheels = package.get("wheels")
        if not isinstance(raw_wheels, list) or not raw_wheels:
            raise DependencyPolicyError(
                f"package {name} has no locked wheel; source build is denied"
            )

        dependencies = _package_dependencies(package)
        graph.append(
            {
                "name": name,
                "version": version,
                "dependencies": list(dependencies),
            }
        )
        resolved.append(f"{name}=={version}")

        for raw_wheel in raw_wheels:
            if not isinstance(raw_wheel, dict):
                raise DependencyPolicyError("pylock wheel entry must be a table")
            filename = str(raw_wheel.get("name") or "").strip()
            url = str(raw_wheel.get("url") or "").strip()
            if not filename or not filename.casefold().endswith(".whl"):
                raise DependencyPolicyError("locked artifact must be a wheel file")
            if not url or not source.permits_artifact_url(url):
                raise DependencyPolicyError(
                    "locked wheel URL is outside the registered source policy"
                )
            hashes = raw_wheel.get("hashes")
            if not isinstance(hashes, dict) or "sha256" not in hashes:
                raise DependencyPolicyError("locked wheel requires SHA-256")
            digest = _sha256(hashes["sha256"], field="wheel hash")
            raw_size = raw_wheel.get("size")
            size: int | None
            if raw_size is None:
                size = None
            elif isinstance(raw_size, bool) or not isinstance(raw_size, int):
                raise DependencyPolicyError("locked wheel size must be an integer")
            elif raw_size < 0:
                raise DependencyPolicyError("locked wheel size cannot be negative")
            else:
                size = raw_size
            wheels.append(
                LockedWheel(
                    package_name=name,
                    package_version=version,
                    filename=filename,
                    url=url,
                    sha256=digest,
                    size_bytes=size,
                )
            )

    return ParsedPylock(
        lock_version=lock_version,
        created_by=created_by,
        lock_sha256=hashlib.sha256(payload).hexdigest(),
        resolved_packages=tuple(sorted(dict.fromkeys(resolved))),
        graph_digest=canonical_digest(
            sorted(graph, key=lambda item: str(item["name"]))
        ),
        wheels=tuple(
            sorted(
                wheels,
                key=lambda item: (
                    item.package_name,
                    item.package_version,
                    item.filename,
                    item.sha256,
                ),
            )
        ),
    )
