from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from jarvis.identity.crypto import WindowsDpapiKeyProtector
from jarvis.identity.owner_enrollment import default_identity_data_dir
from jarvis.identity.speaker_assets import (
    CAMPP_MODEL_ID,
    CAMPP_MODEL_VERSION,
    SpeakerAssetError,
    ensure_campp_model,
)
from jarvis.identity.speaker_identity import (
    CAMPP_MODEL_SHA256,
    CAMPP_PROVIDER_ID,
    SherpaCamPlusEmbeddingProvider,
)
from jarvis.identity.speaker_template import (
    SPEAKER_TEMPLATE_FORMAT,
    SpeakerTemplateError,
    deserialize_speaker_prototype_set,
)
from jarvis.identity.store import OwnerProfileStoreError, SqliteOwnerProfileStore
from jarvis.identity.types import BiometricModality, DecryptedTemplate

CAMPP_ENROLLMENT_COMPATIBILITY = f"campplus:{CAMPP_MODEL_SHA256}:prototype-set-v1"


class SpeakerShadowRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeOwnerSpeakerTemplate:
    template_id: str
    profile_version: int
    provider_id: str
    model_id: str
    model_version: str
    model_sha256: str
    prototypes: np.ndarray

    @property
    def prototype_count(self) -> int:
        return int(self.prototypes.shape[0])

    @property
    def embedding_dimension(self) -> int:
        return int(self.prototypes.shape[1])


@dataclass(frozen=True, slots=True)
class SpeakerShadowScore:
    state: str
    max_reference_cosine: float | None
    embedding_ms: float
    reason_codes: tuple[str, ...]


class EnrolledSpeakerShadowObserver:
    """Read-only CAM++ comparison against strongly enrolled OWNER prototypes.

    This observer never mutates the encrypted template and never grants authority.
    Runtime classification remains disabled until a later non-owner/overlap/replay
    acceptance gate selects deployment semantics.
    """

    def __init__(
        self,
        *,
        template: RuntimeOwnerSpeakerTemplate,
        embedding_provider: SherpaCamPlusEmbeddingProvider,
    ) -> None:
        if template.embedding_dimension != embedding_provider.dimension:
            raise SpeakerShadowRuntimeError(
                "OWNER speaker template dimension does not match CAM++ runtime"
            )
        self.template = template
        self.embedding_provider = embedding_provider

    def score(self, samples: np.ndarray, *, sample_rate: int) -> SpeakerShadowScore:
        started = time.perf_counter()
        embedding = self.embedding_provider.embed(samples, sample_rate=sample_rate)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if embedding is None:
            return SpeakerShadowScore(
                state="insufficient",
                max_reference_cosine=None,
                embedding_ms=elapsed_ms,
                reason_codes=("speaker_embedding_not_ready",),
            )
        prototypes = self.template.prototypes
        if embedding.size != prototypes.shape[1]:
            raise SpeakerShadowRuntimeError(
                "runtime speaker embedding dimension changed unexpectedly"
            )
        score = float(np.max(prototypes @ embedding))
        return SpeakerShadowScore(
            state="scored",
            max_reference_cosine=score,
            embedding_ms=elapsed_ms,
            reason_codes=("speaker_shadow_score_observed_no_threshold",),
        )


def load_compatible_owner_speaker_template(
    store: SqliteOwnerProfileStore,
) -> RuntimeOwnerSpeakerTemplate:
    loaded = store.load_template(BiometricModality.VOICE)
    _validate_metadata(loaded)
    try:
        prototypes = deserialize_speaker_prototype_set(loaded.payload)
    except SpeakerTemplateError as exc:
        raise SpeakerShadowRuntimeError(
            "encrypted OWNER speaker template payload is invalid"
        ) from exc
    if prototypes.shape[1] != loaded.metadata.embedding_dimension:
        raise SpeakerShadowRuntimeError(
            "OWNER speaker template embedding dimension does not match metadata"
        )
    return RuntimeOwnerSpeakerTemplate(
        template_id=loaded.template_id,
        profile_version=loaded.profile_version,
        provider_id=loaded.metadata.provider_id,
        model_id=loaded.metadata.model_id,
        model_version=loaded.metadata.model_version,
        model_sha256=loaded.metadata.model_sha256.lower(),
        prototypes=prototypes,
    )


def build_default_enrolled_speaker_observer() -> EnrolledSpeakerShadowObserver:
    identity_db = default_identity_data_dir() / "owner_identity.db"
    store = SqliteOwnerProfileStore(
        identity_db,
        key_protector=WindowsDpapiKeyProtector(),
    )
    try:
        template = load_compatible_owner_speaker_template(store)
    except (OwnerProfileStoreError, SpeakerShadowRuntimeError) as exc:
        raise SpeakerShadowRuntimeError(
            f"enrolled OWNER speaker template is unavailable: {exc}"
        ) from exc
    finally:
        store.close()

    try:
        model_path = ensure_campp_model()
        provider = SherpaCamPlusEmbeddingProvider(model_path)
    except (SpeakerAssetError, OSError, RuntimeError) as exc:
        raise SpeakerShadowRuntimeError(
            f"CAM++ speaker runtime is unavailable: {exc}"
        ) from exc
    return EnrolledSpeakerShadowObserver(
        template=template,
        embedding_provider=provider,
    )


def _validate_metadata(loaded: DecryptedTemplate) -> None:
    metadata = loaded.metadata
    mismatches: list[str] = []
    if metadata.modality is not BiometricModality.VOICE:
        mismatches.append("modality")
    if metadata.provider_id != CAMPP_PROVIDER_ID:
        mismatches.append("provider_id")
    if metadata.model_id != CAMPP_MODEL_ID:
        mismatches.append("model_id")
    if metadata.model_version != CAMPP_MODEL_VERSION:
        mismatches.append("model_version")
    if metadata.model_sha256.lower() != CAMPP_MODEL_SHA256.lower():
        mismatches.append("model_sha256")
    if metadata.template_format != SPEAKER_TEMPLATE_FORMAT:
        mismatches.append("template_format")
    if metadata.enrollment_compatibility_version != CAMPP_ENROLLMENT_COMPATIBILITY:
        mismatches.append("enrollment_compatibility_version")
    if mismatches:
        raise SpeakerShadowRuntimeError(
            "OWNER speaker template is incompatible with current CAM++ runtime: "
            + ", ".join(mismatches)
        )
