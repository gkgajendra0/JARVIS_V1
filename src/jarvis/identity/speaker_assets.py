from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.identity.speaker_identity import (
    CAMPP_MODEL_FILENAME,
    CAMPP_MODEL_SHA256,
    CAMPP_MODEL_SIZE_BYTES,
)

CAMPP_MODEL_ID = "3dspeaker-campplus-zh-en-common-advanced"
CAMPP_MODEL_VERSION = "sherpa-onnx-export-aa3cfc16"
CAMPP_MODEL_URL = (
    "https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/"
    f"{CAMPP_MODEL_FILENAME}"
)


class SpeakerAssetError(RuntimeError):
    pass


class SpeakerAssetIntegrityError(SpeakerAssetError):
    pass


def default_campp_model_path() -> Path:
    configured = os.getenv("JARVIS_SPEAKER_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JARVIS" / "models" / "speaker" / CAMPP_MODEL_FILENAME
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "jarvis" / "models" / "speaker" / CAMPP_MODEL_FILENAME
    return Path.home() / ".cache" / "jarvis" / "models" / "speaker" / CAMPP_MODEL_FILENAME


def verify_campp_model(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise SpeakerAssetIntegrityError(f"CAM++ model is missing: {candidate}")
    size = candidate.stat().st_size
    if size != CAMPP_MODEL_SIZE_BYTES:
        raise SpeakerAssetIntegrityError(
            f"CAM++ model size mismatch: expected {CAMPP_MODEL_SIZE_BYTES}, got {size}"
        )
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != CAMPP_MODEL_SHA256:
        raise SpeakerAssetIntegrityError(
            f"CAM++ model sha256 mismatch: expected {CAMPP_MODEL_SHA256}, got {actual}"
        )
    return candidate


def ensure_campp_model(
    path: str | Path | None = None,
    *,
    timeout_seconds: float = 120.0,
) -> Path:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    target = Path(path).expanduser() if path is not None else default_campp_model_path()
    if target.is_file():
        return verify_campp_model(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        CAMPP_MODEL_URL,
        headers={"User-Agent": "JARVIS-V1-campp-model-fetch/1"},
    )
    temporary_path: Path | None = None
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout_seconds) as response,
            tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{CAMPP_MODEL_FILENAME}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary,
        ):
            temporary_path = Path(temporary.name)
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > CAMPP_MODEL_SIZE_BYTES:
                    raise SpeakerAssetIntegrityError(
                        "CAM++ download exceeded the pinned byte count"
                    )
                digest.update(chunk)
                temporary.write(chunk)
            if total != CAMPP_MODEL_SIZE_BYTES:
                raise SpeakerAssetIntegrityError(
                    f"CAM++ download size mismatch: expected {CAMPP_MODEL_SIZE_BYTES}, got {total}"
                )
            actual = digest.hexdigest()
            if actual != CAMPP_MODEL_SHA256:
                raise SpeakerAssetIntegrityError(
                    "CAM++ download did not match the pinned SHA-256"
                )
        os.replace(temporary_path, target)
        temporary_path = None
        return verify_campp_model(target)
    except SpeakerAssetError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise SpeakerAssetError("failed to download the pinned CAM++ model") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
