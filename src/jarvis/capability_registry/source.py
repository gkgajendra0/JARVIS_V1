"""Exact-active-release package descriptor source for Phase 8."""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Protocol

from jarvis.capability_registry.contracts import (
    CapabilityPackageContractError,
    CapabilityPackageV1,
    parse_capability_package_v1,
)
from jarvis.promotion.release import (
    ReleaseError,
    ReleaseRecord,
    load_active_release_for_startup,
)

PACKAGE_DIRECTORY_NAME = "capability_packages"
_MAX_DESCRIPTOR_BYTES = 1024 * 1024


class CapabilityPackageSourceError(RuntimeError):
    pass


class CapabilityPackageSource(Protocol):
    release_sha: str

    def packages(self) -> tuple["SourcedCapabilityPackage", ...]: ...


@dataclass(frozen=True, slots=True)
class SourcedCapabilityPackage:
    package: CapabilityPackageV1
    release_sha: str
    relative_path: str

    @property
    def package_digest(self) -> str:
        return self.package.digest


class ReleaseCapabilityPackageSource:
    """Read package JSON only from one fixed directory in a verified active release."""

    def __init__(self, release: ReleaseRecord) -> None:
        if not isinstance(release, ReleaseRecord):
            raise TypeError("release must be ReleaseRecord")
        root = pathlib.Path(release.release_root).expanduser().resolve()
        if root.is_symlink() or not root.is_dir():
            raise CapabilityPackageSourceError("verified release root is unavailable")
        package_root = root / PACKAGE_DIRECTORY_NAME
        self.release = release
        self.release_sha = release.release_sha
        self.release_root = root
        self.package_root = package_root

    @classmethod
    def from_active_release(cls) -> "ReleaseCapabilityPackageSource":
        try:
            active = load_active_release_for_startup()
        except ReleaseError as exc:
            raise CapabilityPackageSourceError(
                "active release failed Phase-7 identity verification"
            ) from exc
        if active is None:
            raise CapabilityPackageSourceError(
                "no verified active release is available"
            )
        return cls(active)

    def packages(self) -> tuple[SourcedCapabilityPackage, ...]:
        if not self.package_root.exists():
            return ()
        if self.package_root.is_symlink() or not self.package_root.is_dir():
            raise CapabilityPackageSourceError(
                "capability package directory is unavailable or unsafe"
            )
        try:
            resolved_root = self.package_root.resolve(strict=True)
            resolved_root.relative_to(self.release_root)
        except (OSError, ValueError) as exc:
            raise CapabilityPackageSourceError(
                "capability package directory escaped the active release"
            ) from exc

        loaded: list[SourcedCapabilityPackage] = []
        identities: set[tuple[str, str]] = set()
        for path in sorted(self.package_root.iterdir(), key=lambda item: item.name):
            if path.name.startswith("."):
                continue
            if path.suffix.casefold() != ".json":
                continue
            if path.is_symlink() or not path.is_file():
                raise CapabilityPackageSourceError(
                    f"capability package descriptor is unsafe: {path.name}"
                )
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(resolved_root)
            except (OSError, ValueError) as exc:
                raise CapabilityPackageSourceError(
                    f"capability package descriptor escaped trusted root: {path.name}"
                ) from exc
            size = path.stat().st_size
            if size <= 0 or size > _MAX_DESCRIPTOR_BYTES:
                raise CapabilityPackageSourceError(
                    f"capability package descriptor size is invalid: {path.name}"
                )
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CapabilityPackageSourceError(
                    f"capability package descriptor is unreadable: {path.name}"
                ) from exc
            if not isinstance(payload, dict):
                raise CapabilityPackageSourceError(
                    f"capability package descriptor must be an object: {path.name}"
                )
            try:
                package = parse_capability_package_v1(payload)
            except CapabilityPackageContractError as exc:
                raise CapabilityPackageSourceError(
                    f"capability package descriptor failed v1 schema contract: {path.name}"
                ) from exc
            identity = (package.package_id, package.package_version)
            if identity in identities:
                raise CapabilityPackageSourceError(
                    "duplicate package identity/version in active release"
                )
            identities.add(identity)
            loaded.append(
                SourcedCapabilityPackage(
                    package=package,
                    release_sha=self.release_sha,
                    relative_path=f"{PACKAGE_DIRECTORY_NAME}/{path.name}",
                )
            )
        return tuple(loaded)

    def find(
        self,
        package_id: str,
        package_version: str,
    ) -> SourcedCapabilityPackage | None:
        normalized_id = str(package_id).strip().casefold()
        normalized_version = str(package_version).strip()
        for sourced in self.packages():
            if (
                sourced.package.package_id == normalized_id
                and sourced.package.package_version == normalized_version
            ):
                return sourced
        return None
