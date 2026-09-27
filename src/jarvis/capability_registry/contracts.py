"""Immutable Phase-8 capability-package contracts and strict SemVer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from jarvis.engineering_substrate.canonical import canonical_digest

CAPABILITY_PACKAGE_SCHEMA_VERSION_V1 = 1
CAPABILITY_RUNTIME_API_ID = "jarvis.capability_runtime"
CAPABILITY_RUNTIME_API_VERSION_V1 = 1
CAPABILITY_PACKAGE_SCHEMA_URI_V1 = "urn:jarvis:schema:capability-package:v1"

_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class CapabilityPackageContractError(ValueError):
    """A capability-package payload violates the trusted Phase-8 contract."""


class CapabilityPackageKind(str, Enum):
    """Source ownership class for a capability package."""

    CORE_SOURCE = "core_source"
    EXTENSION_SOURCE = "extension_source"


@dataclass(frozen=True, slots=True)
class StrictSemVer:
    """Parsed SemVer 2.0.0 identity with explicit precedence comparison."""

    original: str
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: object) -> StrictSemVer:
        if not isinstance(value, str):
            raise CapabilityPackageContractError("semantic version must be a string")
        match = _SEMVER.fullmatch(value)
        if match is None:
            raise CapabilityPackageContractError(
                f"invalid strict SemVer 2.0.0 value: {value!r}"
            )
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        build = tuple(match.group(5).split(".")) if match.group(5) else ()
        return cls(
            original=value,
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
            build=build,
        )

    def compare_precedence(self, other: StrictSemVer) -> int:
        """Return -1/0/1 using SemVer precedence; build metadata is ignored."""

        if not isinstance(other, StrictSemVer):
            raise TypeError("other must be StrictSemVer")
        left_release = (self.major, self.minor, self.patch)
        right_release = (other.major, other.minor, other.patch)
        if left_release != right_release:
            return -1 if left_release < right_release else 1

        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1

        for left, right in zip(self.prerelease, other.prerelease, strict=False):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return -1 if int(left) < int(right) else 1
            if left_numeric != right_numeric:
                return -1 if left_numeric else 1
            return -1 if left < right else 1

        if len(self.prerelease) == len(other.prerelease):
            return 0
        return -1 if len(self.prerelease) < len(other.prerelease) else 1


def _token(value: str, *, field: str, max_length: int = 180) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _sha256(value: str, *, field: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return value.casefold()


def _references(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _text(item, field=field, max_length=1000)
                for item in values
            }
        )
    )


class PackageArtifactDescriptorV1(BaseModel):
    """Typed content-addressed reference to one external package artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: StrictStr = Field(min_length=1, max_length=120)
    sha256: StrictStr = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: StrictInt = Field(ge=0)
    media_type: StrictStr = Field(min_length=1, max_length=255)
    provenance_refs: tuple[StrictStr, ...] = ()

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        return _token(value, field="role", max_length=120)

    @field_validator("sha256")
    @classmethod
    def _normalize_digest(cls, value: str) -> str:
        return _sha256(value, field="sha256")

    @field_validator("media_type")
    @classmethod
    def _normalize_media_type(cls, value: str) -> str:
        return _text(value, field="media_type", max_length=255)

    @field_validator("provenance_refs")
    @classmethod
    def _normalize_provenance_refs(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    _token(item, field="provenance_ref", max_length=240)
                    for item in values
                }
            )
        )


class CapabilityPackageV1(BaseModel):
    """Closed declarative package identity; package data never names executable code."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": CAPABILITY_PACKAGE_SCHEMA_URI_V1,
        },
    )

    schema_version: StrictInt
    package_id: StrictStr = Field(min_length=1, max_length=180)
    package_version: StrictStr = Field(min_length=1, max_length=128)
    capability_id: StrictStr = Field(min_length=1, max_length=180)
    package_kind: CapabilityPackageKind
    manifest_id: StrictStr = Field(min_length=1, max_length=180)
    manifest_version: StrictInt = Field(gt=0)
    manifest_digest: StrictStr = Field(pattern=r"^[0-9a-fA-F]{64}$")
    runtime_api_id: StrictStr = Field(min_length=1, max_length=180)
    runtime_api_version: StrictInt = Field(gt=0)
    artifacts: tuple[PackageArtifactDescriptorV1, ...] = ()
    attestation_refs: tuple[StrictStr, ...] = ()
    sbom_refs: tuple[StrictStr, ...] = ()

    @field_validator(
        "package_id",
        "capability_id",
        "manifest_id",
        "runtime_api_id",
    )
    @classmethod
    def _normalize_tokens(cls, value: str, info: ValidationInfo) -> str:
        return _token(value, field=info.field_name, max_length=180)

    @field_validator("package_version")
    @classmethod
    def _validate_package_version(cls, value: str) -> str:
        StrictSemVer.parse(value)
        return value

    @field_validator("manifest_digest")
    @classmethod
    def _normalize_manifest_digest(cls, value: str) -> str:
        return _sha256(value, field="manifest_digest")

    @field_validator("artifacts")
    @classmethod
    def _normalize_artifacts(
        cls,
        artifacts: tuple[PackageArtifactDescriptorV1, ...],
    ) -> tuple[PackageArtifactDescriptorV1, ...]:
        identities = tuple((item.role, item.sha256) for item in artifacts)
        if len(identities) != len(set(identities)):
            raise ValueError("package artifact role/digest identities must be unique")
        return tuple(
            sorted(
                artifacts,
                key=lambda item: (
                    item.role,
                    item.sha256,
                    item.media_type,
                    item.size_bytes,
                ),
            )
        )

    @field_validator("attestation_refs", "sbom_refs")
    @classmethod
    def _normalize_evidence_refs(
        cls,
        values: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        return _references(values, field=info.field_name)

    @model_validator(mode="after")
    def _require_supported_schema(self) -> CapabilityPackageV1:
        if self.schema_version != CAPABILITY_PACKAGE_SCHEMA_VERSION_V1:
            raise ValueError(
                "unsupported capability package schema version: "
                f"{self.schema_version}"
            )
        return self

    @property
    def parsed_version(self) -> StrictSemVer:
        return StrictSemVer.parse(self.package_version)

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def digest(self) -> str:
        return canonical_digest(self.canonical_payload())


def parse_capability_package_v1(
    payload: Mapping[str, Any],
) -> CapabilityPackageV1:
    """Parse a mapping using the closed v1 contract and fail on unknown fields."""

    if not isinstance(payload, Mapping):
        raise CapabilityPackageContractError(
            "capability package payload must be a mapping"
        )
    try:
        return CapabilityPackageV1.model_validate(dict(payload))
    except ValidationError as exc:
        raise CapabilityPackageContractError(
            "capability package payload failed v1 validation"
        ) from exc
