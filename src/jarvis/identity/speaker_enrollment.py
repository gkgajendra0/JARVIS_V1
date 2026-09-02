from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import numpy as np

from jarvis.authority import (
    ApprovalService,
    AuthorityService,
    OpaPolicyEngine,
    PermitRegistry,
    RiskClassifier,
    SqliteAuditEventStore,
    StrongApprovalService,
    WindowsHelloVerifier,
    WindowsWtsSessionProvider,
)
from jarvis.authority.local_opa import LocalOpaError, ManagedOpaServer
from jarvis.config import JarvisConfig
from jarvis.identity.crypto import WindowsDpapiKeyProtector
from jarvis.identity.lifecycle import (
    OwnerProfileAuthorizationDenied,
    OwnerProfileLifecycleService,
)
from jarvis.identity.owner_enrollment import (
    _default_hello_helper_path,
    default_identity_data_dir,
)
from jarvis.identity.speaker_assets import (
    CAMPP_MODEL_ID,
    CAMPP_MODEL_VERSION,
    SpeakerAssetError,
    ensure_campp_model,
)
from jarvis.identity.speaker_benchmark import InMemorySegmentRecorder
from jarvis.identity.speaker_identity import (
    CAMPP_MODEL_SHA256,
    CAMPP_PROVIDER_ID,
    SherpaCamPlusEmbeddingProvider,
    assess_speaker_segment,
)
from jarvis.identity.speaker_shadow import CAMPP_ENROLLMENT_COMPATIBILITY
from jarvis.identity.speaker_template import (
    SPEAKER_TEMPLATE_FORMAT,
    SpeakerTemplateError,
    build_speaker_prototype_set,
    serialize_speaker_prototype_set,
)
from jarvis.identity.store import SqliteOwnerProfileStore
from jarvis.identity.types import BiometricModality, TemplateInput, TemplateMetadata
from jarvis.voice.audio import SessionAudioInput
from jarvis.voice.media_devices_audio import MediaDevicesConversationRuntime

_DEFAULT_SEGMENT_COUNT = 12
_DEFAULT_SEGMENT_SECONDS = 3.0
_DEFAULT_PROTOTYPE_COUNT = 6
_MAX_CAPTURE_ATTEMPTS = 30

_CAPTURE_CUES = (
    "natural English",
    "natural Hinglish",
    "natural Hindi",
    "normal desk voice",
    "slightly quieter natural voice",
    "normal voice with different wording",
    "natural Hinglish",
    "natural English",
    "slightly farther from the microphone",
    "normal desk distance again",
    "natural Hindi or Hinglish",
    "comfortable everyday speaking voice",
)


class _NoOpWakeDetector:
    def enable(self) -> None:
        return None

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer

    def feed(self, frame) -> None:
        del frame

    async def aclose(self) -> None:
        return None


async def _consume_frames(
    source: SessionAudioInput,
    recorder: InMemorySegmentRecorder,
) -> None:
    async for frame in source:
        recorder.accept_frame(frame)


async def _capture_segment(
    recorder: InMemorySegmentRecorder,
    *,
    index: int,
    total: int,
    duration_seconds: float,
    cue: str,
) -> tuple[np.ndarray, int]:
    await asyncio.to_thread(
        input,
        f"\n[{index}/{total}] Prepare for {cue}. Press Enter when ready... ",
    )
    print("  3...")
    await asyncio.sleep(0.35)
    print("  2...")
    await asyncio.sleep(0.35)
    print("  1...")
    await asyncio.sleep(0.35)
    print(f"  >>> START SPEAKING — {duration_seconds:.1f}s <<<")
    recorder.start()
    try:
        await asyncio.sleep(duration_seconds)
        samples, sample_rate = recorder.stop()
    except BaseException:
        recorder.clear()
        raise
    print("  >>> STOP <<<")
    return samples, sample_rate


async def _capture_owner_embeddings(
    *,
    config: JarvisConfig,
    provider: SherpaCamPlusEmbeddingProvider,
    segment_count: int,
    segment_seconds: float,
) -> list[np.ndarray]:
    runtime = MediaDevicesConversationRuntime(
        _NoOpWakeDetector(),  # type: ignore[arg-type]
        input_device_name=config.audio_input_device,
        output_device_name=config.audio_output_device,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=max(1.0, config.audio_ring_buffer_seconds),
    )
    session_input = SessionAudioInput(capacity_frames=2_000)
    recorder = InMemorySegmentRecorder()
    consumer_task: asyncio.Task[None] | None = None
    embeddings: list[np.ndarray] = []
    attempts = 0
    try:
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-speaker-enrollment-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.15)

        while len(embeddings) < segment_count:
            attempts += 1
            if attempts > _MAX_CAPTURE_ATTEMPTS:
                raise RuntimeError(
                    "too many rejected enrollment captures; check microphone level/noise"
                )
            target_index = len(embeddings) + 1
            cue = _CAPTURE_CUES[(target_index - 1) % len(_CAPTURE_CUES)]
            samples, sample_rate = await _capture_segment(
                recorder,
                index=target_index,
                total=segment_count,
                duration_seconds=segment_seconds,
                cue=cue,
            )
            try:
                quality = assess_speaker_segment(samples, sample_rate=sample_rate)
                print(
                    f"  quality: {quality.duration_seconds:.2f}s | "
                    f"RMS {quality.rms_dbfs:.1f} dBFS | "
                    f"clipped {quality.clipping_ratio * 100.0:.3f}%"
                )
                if not quality.accepted:
                    print(
                        "  RETRY: "
                        + ", ".join(quality.reason_codes)
                        + ". This sample was not enrolled."
                    )
                    continue
                embedding = await asyncio.to_thread(
                    provider.embed,
                    samples,
                    sample_rate=sample_rate,
                )
                if embedding is None:
                    print("  RETRY: CAM++ did not produce an embedding.")
                    continue
                embeddings.append(embedding.copy())
                print(f"  accepted ({len(embeddings)}/{segment_count})")
            finally:
                del samples
    finally:
        recorder.clear()
        runtime.deactivate_session()
        if consumer_task is not None:
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        await runtime.aclose()
    return embeddings


def _preserved_templates(store: SqliteOwnerProfileStore) -> list[TemplateInput]:
    profile = store.get_owner()
    preserved: list[TemplateInput] = []
    for modality in profile.modalities:
        if modality is BiometricModality.VOICE:
            continue
        loaded = store.load_template(modality)
        preserved.append(TemplateInput(metadata=loaded.metadata, payload=loaded.payload))
    return preserved


def _commit_voice_template(
    *,
    template: TemplateInput,
    data_dir: Path,
) -> None:
    identity_db = data_dir / "owner_identity.db"
    audit_db = data_dir / "authority_audit.db"
    helper_path = _default_hello_helper_path()
    if helper_path is None or not helper_path.is_file():
        raise RuntimeError(
            "Windows Hello helper is missing. Build the Release helper or set "
            "JARVIS_WINDOWS_HELLO_HELPER before speaker enrollment."
        )

    store = SqliteOwnerProfileStore(
        identity_db,
        key_protector=WindowsDpapiKeyProtector(),
    )
    try:
        if not store.has_owner():
            raise RuntimeError(
                "OWNER face profile is not enrolled. Run jarvis-owner enrollment first."
            )
        templates = _preserved_templates(store)
        templates.append(template)

        approvals = ApprovalService()
        audit_store = SqliteAuditEventStore(audit_db)
        try:
            with ManagedOpaServer() as opa:
                authority = AuthorityService(
                    risk_classifier=RiskClassifier(),
                    policy_engine=OpaPolicyEngine(endpoint=opa.endpoint),
                    approvals=approvals,
                    audit_store=audit_store,
                    permits=PermitRegistry(),
                )
                lifecycle = OwnerProfileLifecycleService(
                    store=store,
                    strong_approval=StrongApprovalService(
                        approvals=approvals,
                        verifier=WindowsHelloVerifier(helper_path=helper_path),
                    ),
                    authority=authority,
                    session_provider=WindowsWtsSessionProvider(),
                )
                lifecycle.replace_owner(templates)
        finally:
            audit_store.close()

        loaded = store.load_template(BiometricModality.VOICE)
        if loaded.metadata != template.metadata or loaded.payload != template.payload:
            raise RuntimeError("persisted OWNER voice template did not round-trip exactly")
        profile = store.get_owner()
        print(f"profile_version = {profile.profile_version}")
        print(f"modalities = {[item.value for item in profile.modalities]}")
    finally:
        store.close()


async def run_speaker_enrollment(
    *,
    segment_count: int = _DEFAULT_SEGMENT_COUNT,
    segment_seconds: float = _DEFAULT_SEGMENT_SECONDS,
    prototype_count: int = _DEFAULT_PROTOTYPE_COUNT,
) -> int:
    if sys.platform != "win32":
        print("OWNER speaker enrollment is currently supported only on Windows.")
        return 2
    if segment_count < prototype_count * 2:
        raise ValueError("segment_count must be at least twice prototype_count")
    if not math.isfinite(segment_seconds) or segment_seconds < 2.0:
        raise ValueError("segment_seconds must be at least 2 seconds")

    print("JARVIS OWNER speaker enrollment")
    print("-------------------------------")
    print("One-time enrollment only. Normal JARVIS conversations will not ask for this.")
    print("Capture uses the accepted LiveKit MediaDevices/WebRTC 48 kHz microphone path.")
    print("Raw audio is memory-only and is discarded immediately after each segment.")
    print("Only a small encrypted CAM++ prototype set will be persisted.")
    print("Windows Hello must approve the final exact OWNER profile replacement.")
    print("Speaker similarity remains SHADOW ONLY and grants no authority.")

    try:
        model_path = ensure_campp_model()
        provider = SherpaCamPlusEmbeddingProvider(model_path)
        config = JarvisConfig.from_environment()
        embeddings = await _capture_owner_embeddings(
            config=config,
            provider=provider,
            segment_count=segment_count,
            segment_seconds=segment_seconds,
        )
        try:
            prototype_set = build_speaker_prototype_set(
                embeddings,
                prototype_count=prototype_count,
            )
            payload = serialize_speaker_prototype_set(prototype_set)
            template = TemplateInput(
                metadata=TemplateMetadata(
                    modality=BiometricModality.VOICE,
                    provider_id=CAMPP_PROVIDER_ID,
                    model_id=CAMPP_MODEL_ID,
                    model_version=CAMPP_MODEL_VERSION,
                    model_sha256=CAMPP_MODEL_SHA256,
                    embedding_dimension=prototype_set.embedding_dimension,
                    calibration_version="step3b10-real-machine-campp-v1",
                    enrollment_compatibility_version=CAMPP_ENROLLMENT_COMPATIBILITY,
                    template_format=SPEAKER_TEMPLATE_FORMAT,
                ),
                payload=payload,
            )

            print("\nVOICE TEMPLATE SUMMARY")
            print(f"accepted speech segments = {len(embeddings)}")
            print(f"prototype_count = {prototype_set.prototype_count}")
            print(f"embedding_dimension = {prototype_set.embedding_dimension}")
            print(
                "coverage cosine: "
                f"min={prototype_set.coverage_minimum:.4f}, "
                f"p05={prototype_set.coverage_p05:.4f}, "
                f"median={prototype_set.coverage_median:.4f}"
            )
            print("Windows Hello will now authorize this exact encrypted profile update.")
            _commit_voice_template(
                template=template,
                data_dir=default_identity_data_dir(),
            )
        finally:
            embeddings.clear()

        print("\nOWNER SPEAKER ENROLLMENT COMPLETE")
        print(f"model = {model_path}")
        print("raw_audio_saved = False")
        print("speaker_threshold_selected = False")
        print("speaker_identity_grants_authority = False")
        print("STEP_3B12_SPEAKER_ENROLLMENT = PASS")
        return 0
    except (SpeakerAssetError, SpeakerTemplateError, LocalOpaError) as exc:
        print(f"Speaker enrollment failed safely: {exc}")
        return 2
    except OwnerProfileAuthorizationDenied as exc:
        print(f"OWNER speaker enrollment authorization denied: {exc}")
        return 2
    except RuntimeError as exc:
        print(f"Speaker enrollment failed safely: {exc}")
        return 2


def main() -> None:
    try:
        raise SystemExit(asyncio.run(run_speaker_enrollment()))
    except KeyboardInterrupt:
        print("\nSpeaker enrollment stopped. No partial voice template was committed.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
