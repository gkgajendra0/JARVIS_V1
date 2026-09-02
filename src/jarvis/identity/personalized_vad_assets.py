from __future__ import annotations

import hashlib
import os
from pathlib import Path

FIRERED_PVAD_MODEL_ID = "FireRedTeam/FireRedChat-pvad"
FIRERED_PVAD_MODEL_REVISION = "74561b17a50fbe9d8f84dacc453f175cb97f567c"
FIRERED_PVAD_ONNX_FILENAME = "pvad.onnx"
FIRERED_PVAD_ONNX_SIZE_BYTES = 3_940_567
FIRERED_PVAD_ONNX_SHA256 = (
    "2114fd3c3fa87b560eaf4cad6a6e1a0a73aefba08da05521a27bfe2382ef4bdd"
)
FIRERED_PVAD_SPEAKER_DIRNAME = "spkrec-ecapa-voxceleb"


class PersonalizedVadAssetError(RuntimeError):
    pass


class PersonalizedVadAssetIntegrityError(PersonalizedVadAssetError):
    pass


def default_personalized_vad_asset_dir() -> Path:
    configured = os.getenv("JARVIS_FIRERED_PVAD_ASSET_DIR")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JARVIS" / "models" / "personalized-vad" / "firered"
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "jarvis" / "models" / "personalized-vad" / "firered"
    return Path.home() / ".cache" / "jarvis" / "models" / "personalized-vad" / "firered"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_personalized_vad_assets(path: str | Path) -> Path:
    root = Path(path).expanduser()
    model = root / FIRERED_PVAD_ONNX_FILENAME
    speaker_dir = root / FIRERED_PVAD_SPEAKER_DIRNAME
    if not model.is_file():
        raise PersonalizedVadAssetIntegrityError(f"FireRed pVAD model is missing: {model}")
    if model.stat().st_size != FIRERED_PVAD_ONNX_SIZE_BYTES:
        raise PersonalizedVadAssetIntegrityError(
            "FireRed pVAD model size mismatch: "
            f"expected {FIRERED_PVAD_ONNX_SIZE_BYTES}, got {model.stat().st_size}"
        )
    actual = _sha256(model)
    if actual != FIRERED_PVAD_ONNX_SHA256:
        raise PersonalizedVadAssetIntegrityError(
            "FireRed pVAD model sha256 mismatch: "
            f"expected {FIRERED_PVAD_ONNX_SHA256}, got {actual}"
        )
    if not speaker_dir.is_dir():
        raise PersonalizedVadAssetIntegrityError(
            f"FireRed ECAPA speaker assets are missing: {speaker_dir}"
        )
    required = ("hyperparams.yaml", "classifier.ckpt", "embedding_model.ckpt")
    missing = [name for name in required if not (speaker_dir / name).is_file()]
    if missing:
        raise PersonalizedVadAssetIntegrityError(
            "FireRed ECAPA speaker assets are incomplete: " + ", ".join(missing)
        )
    return root


def ensure_personalized_vad_assets(path: str | Path | None = None) -> Path:
    target = Path(path).expanduser() if path is not None else default_personalized_vad_asset_dir()
    try:
        return verify_personalized_vad_assets(target)
    except PersonalizedVadAssetIntegrityError:
        pass

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise PersonalizedVadAssetError(
            "huggingface-hub is required for the FireRed pVAD benchmark; install "
            'the optional extra with: pip install -e ".[personalized-vad-benchmark]"'
        ) from exc

    target.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id=FIRERED_PVAD_MODEL_ID,
            revision=FIRERED_PVAD_MODEL_REVISION,
            allow_patterns=(
                FIRERED_PVAD_ONNX_FILENAME,
                f"{FIRERED_PVAD_SPEAKER_DIRNAME}/*",
            ),
            local_dir=target,
        )
    except Exception as exc:
        raise PersonalizedVadAssetError(
            "failed to download the pinned FireRed pVAD benchmark assets"
        ) from exc
    return verify_personalized_vad_assets(target)
