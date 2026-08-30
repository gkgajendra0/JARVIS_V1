from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

OWNER_PROFILE_ID = "OWNER"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class IdentityValidationError(ValueError):
    pass


class BiometricModality(str, Enum):
    FACE = "face"
    VOICE = "voice"


@dataclass(frozen=True, slots=True)
class TemplateMetadata:
    modality: BiometricModality
    provider_id: str
    model_id: str
    model_version: str
    model_sha256: str
    embedding_dimension: int
    calibration_version: str
    enrollment_compatibility_version: str
    template_format: str = "opaque-bytes-v1"

    def __post_init__(self) -> None:
        for field_name in (
            "provider_id",
            "model_id",
            "model_version",
            "calibration_version",
            "enrollment_compatibility_version",
            "template_format",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                raise IdentityValidationError(f"{field_name} must not be empty")
        if not _SHA256_RE.fullmatch(self.model_sha256):
            raise IdentityValidationError(
                "model_sha256 must be 64 hexadecimal characters"
            )
        if self.embedding_dimension <= 0:
            raise IdentityValidationError("embedding_dimension must be positive")

    def manifest_view(self) -> dict[str, object]:
        return {
            "modality": self.modality.value,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_sha256": self.model_sha256.lower(),
            "embedding_dimension": self.embedding_dimension,
            "calibration_version": self.calibration_version,
            "enrollment_compatibility_version": self.enrollment_compatibility_version,
            "template_format": self.template_format,
        }


@dataclass(frozen=True, slots=True)
class TemplateInput:
    metadata: TemplateMetadata
    payload: bytes

    def __post_init__(self) -> None:
        if not self.payload:
            raise IdentityValidationError("template payload must not be empty")


@dataclass(frozen=True, slots=True)
class OwnerProfile:
    profile_id: str
    profile_version: int
    created_at_epoch: float
    updated_at_epoch: float
    modalities: tuple[BiometricModality, ...]


@dataclass(frozen=True, slots=True)
class DecryptedTemplate:
    template_id: str
    profile_version: int
    metadata: TemplateMetadata
    payload: bytes
    created_at_epoch: float
