from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2

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
from jarvis.identity.calibration import _capture_stage, _sample_quality_summary
from jarvis.identity.crypto import WindowsDpapiKeyProtector
from jarvis.identity.face_template import (
    FACE_TEMPLATE_FORMAT,
    build_face_prototype_set,
    serialize_face_prototype_set,
)
from jarvis.identity.lifecycle import (
    OwnerProfileAuthorizationDenied,
    OwnerProfileLifecycleService,
)
from jarvis.identity.model_assets import ModelAssetCache, load_default_face_model_manifest
from jarvis.identity.store import OwnerProfileAlreadyExists, SqliteOwnerProfileStore
from jarvis.identity.types import BiometricModality, TemplateInput, TemplateMetadata

_DEFAULT_MINIMUM_SAMPLES = 180
_DEFAULT_MAXIMUM_SAMPLES = 240
_DEFAULT_ANALYSIS_INTERVAL_SECONDS = 0.20
_DEFAULT_PROTOTYPE_COUNT = 8


def default_identity_data_dir() -> Path:
    configured = os.getenv("JARVIS_IDENTITY_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "JARVIS" / "identity"
    xdg_data = os.getenv("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "jarvis" / "identity"
    return Path.home() / ".local" / "share" / "jarvis" / "identity"


def _default_hello_helper_path() -> Path | None:
    configured = os.getenv("JARVIS_WINDOWS_HELLO_HELPER")
    if configured:
        return Path(configured).expanduser()
    repo_root = Path(__file__).resolve().parents[3]
    candidate = (
        repo_root
        / "tools"
        / "windows"
        / "Jarvis.WindowsHelloVerifier"
        / "bin"
        / "Release"
        / "net9.0-windows10.0.22000.0"
        / "Jarvis.WindowsHelloVerifier.exe"
    )
    return candidate if candidate.is_file() else None


def _load_face_models():
    manifest = load_default_face_model_manifest()
    cache = ModelAssetCache()
    detector_asset = manifest.by_role("face_detector")
    recognizer_asset = manifest.by_role("face_recognizer")
    detector_path = cache.fetch(detector_asset)
    recognizer_path = cache.fetch(recognizer_asset)
    yunet = cv2.FaceDetectorYN.create(
        str(detector_path),
        "",
        (320, 320),
        0.9,
        0.3,
        5000,
    )
    sface = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
    return manifest, recognizer_asset, yunet, sface


def run_owner_enrollment(
    *,
    minimum_samples: int = _DEFAULT_MINIMUM_SAMPLES,
    maximum_samples: int = _DEFAULT_MAXIMUM_SAMPLES,
    analysis_interval_seconds: float = _DEFAULT_ANALYSIS_INTERVAL_SECONDS,
    prototype_count: int = _DEFAULT_PROTOTYPE_COUNT,
) -> int:
    if sys.platform != "win32":
        print("OWNER enrollment is currently supported only on Windows.")
        return 2
    if minimum_samples < 120:
        raise ValueError("OWNER enrollment minimum_samples must be at least 120")
    if maximum_samples < minimum_samples:
        raise ValueError("maximum_samples must be at least minimum_samples")
    if prototype_count < 2:
        raise ValueError("prototype_count must be at least 2")

    data_dir = default_identity_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    identity_db = data_dir / "owner_identity.db"
    audit_db = data_dir / "authority_audit.db"

    helper_path = _default_hello_helper_path()
    if helper_path is None or not helper_path.is_file():
        print(
            "Windows Hello helper is missing. Build the Release helper or set "
            "JARVIS_WINDOWS_HELLO_HELPER before enrollment."
        )
        return 2

    store = SqliteOwnerProfileStore(
        identity_db,
        key_protector=WindowsDpapiKeyProtector(),
    )
    try:
        if store.has_owner():
            print(f"OWNER is already enrolled in {identity_db}")
            print("Use a future re-enrollment command rather than overwriting silently.")
            return 2

        manifest, recognizer_asset, yunet, sface = _load_face_models()
        print("JARVIS Step 3B.6 real OWNER face enrollment")
        print("-------------------------------------------")
        print("This command WILL persist your encrypted OWNER face template.")
        print("Raw camera frames and aligned face images are never saved.")
        print("A small normalized SFace prototype set is derived in RAM.")
        print("Windows Hello must approve the exact final template commitment.")
        print(f"Encrypted identity database: {identity_db}")
        print()

        stage = _capture_stage(
            stage_name="OWNER ENROLLMENT",
            yunet=yunet,
            sface=sface,
            minimum_samples=minimum_samples,
            maximum_samples=maximum_samples,
            analysis_interval_seconds=analysis_interval_seconds,
        )
        if stage.aborted:
            print("STEP_3B6_OWNER_ENROLLMENT = ABORTED")
            return 2

        features = [sample.feature for sample in stage.samples]
        prototype_set = build_face_prototype_set(
            features,
            prototype_count=prototype_count,
        )
        payload = serialize_face_prototype_set(prototype_set)

        print()
        print("ENROLLMENT TEMPLATE SUMMARY")
        print(f"Valid SFace samples: {len(stage.samples)}")
        print(f"Associated-head attempts: {stage.associated_attempts}")
        _sample_quality_summary("OWNER", stage.samples)
        print(f"Prototype count: {prototype_set.prototype_count}")
        print(f"Embedding dimension: {prototype_set.embedding_dimension}")
        print(f"Prototype inlier samples: {prototype_set.inlier_sample_count}")
        print(
            "Prototype coverage cosine: "
            f"min={prototype_set.coverage_minimum:.4f}, "
            f"p05={prototype_set.coverage_p05:.4f}, "
            f"median={prototype_set.coverage_median:.4f}"
        )
        print("No raw frame or aligned face will be persisted.")
        print("Windows Hello will now ask you to authorize this exact enrollment.")
        print()

        template = TemplateInput(
            metadata=TemplateMetadata(
                modality=BiometricModality.FACE,
                provider_id="opencv-sface-prototype-set-v1",
                model_id=recognizer_asset.asset_id,
                model_version=recognizer_asset.source_revision,
                model_sha256=recognizer_asset.sha256,
                embedding_dimension=prototype_set.embedding_dimension,
                calibration_version="step3b-owner-positive-baseline-v1",
                enrollment_compatibility_version=(
                    f"sface:{recognizer_asset.sha256}:prototype-set-v1"
                ),
                template_format=FACE_TEMPLATE_FORMAT,
            ),
            payload=payload,
        )

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
                result = lifecycle.create_owner([template])
        finally:
            audit_store.close()

        loaded = store.load_template(BiometricModality.FACE)
        payload_matches = loaded.payload == payload
        metadata_matches = loaded.metadata == template.metadata
        if not payload_matches or not metadata_matches:
            print("FAIL: persisted OWNER template did not round-trip exactly.")
            return 3

        profile = store.get_owner()
        print()
        print("OWNER ENROLLMENT COMPLETE")
        print(f"profile_id = {profile.profile_id}")
        print(f"profile_version = {profile.profile_version}")
        print(f"modalities = {[item.value for item in profile.modalities]}")
        print(f"proposal_id = {result.proposal_id}")
        print(f"template_format = {loaded.metadata.template_format}")
        print(f"prototype_count = {prototype_set.prototype_count}")
        print(f"encrypted_store = {identity_db}")
        print("raw_frames_saved = False")
        print("aligned_faces_saved = False")
        print("face_evidence_grants_T2 = False")
        print("STEP_3B6_OWNER_ENROLLMENT = PASS")
        features.clear()
        return 0
    except LocalOpaError as exc:
        print(f"OPA policy sidecar unavailable: {exc}")
        print("No OWNER profile was written.")
        return 2
    except OwnerProfileAlreadyExists:
        print("OWNER profile already exists; enrollment did not overwrite it.")
        return 2
    except OwnerProfileAuthorizationDenied as exc:
        print(f"OWNER enrollment authorization denied: {exc}")
        print("No weaker verification fallback was attempted.")
        return 2
    finally:
        store.close()


def main() -> None:
    raise SystemExit(run_owner_enrollment())


if __name__ == "__main__":
    main()
