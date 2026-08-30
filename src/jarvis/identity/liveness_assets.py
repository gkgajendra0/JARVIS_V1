from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO


class LivenessModelAssetError(RuntimeError):
    pass


class LivenessModelIntegrityError(LivenessModelAssetError):
    pass


FACE_LANDMARKER_FILENAME = "face_landmarker.task"
FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_LANDMARKER_SIZE_BYTES = 3_758_596
FACE_LANDMARKER_SHA256 = (
    "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
)

UrlOpener = Callable[..., BinaryIO]


def default_face_landmarker_path() -> Path:
    configured = os.getenv("JARVIS_FACE_LANDMARKER_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JARVIS" / "models" / FACE_LANDMARKER_FILENAME
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "jarvis" / "models" / FACE_LANDMARKER_FILENAME
    return Path.home() / ".cache" / "jarvis" / "models" / FACE_LANDMARKER_FILENAME


def verify_face_landmarker_model(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_file():
        raise LivenessModelIntegrityError(f"face landmarker model is missing: {candidate}")
    digest = hashlib.sha256()
    size = 0
    with candidate.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    if size != FACE_LANDMARKER_SIZE_BYTES:
        raise LivenessModelIntegrityError(
            f"face landmarker model size mismatch: expected "
            f"{FACE_LANDMARKER_SIZE_BYTES}, got {size}"
        )
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != FACE_LANDMARKER_SHA256:
        raise LivenessModelIntegrityError(
            "face landmarker model sha256 mismatch: "
            f"expected {FACE_LANDMARKER_SHA256}, got {actual_sha256}"
        )
    return candidate


def ensure_face_landmarker_model(
    path: str | Path | None = None,
    *,
    timeout_seconds: float = 120.0,
    opener: UrlOpener = urllib.request.urlopen,
) -> Path:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    target = Path(path) if path is not None else default_face_landmarker_path()
    if target.is_file():
        return verify_face_landmarker_model(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        FACE_LANDMARKER_URL,
        headers={"User-Agent": "JARVIS-V1-liveness-model-fetch/1"},
    )
    temporary_path: Path | None = None
    try:
        with (
            opener(request, timeout=timeout_seconds) as response,
            tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{FACE_LANDMARKER_FILENAME}.",
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
                if total > FACE_LANDMARKER_SIZE_BYTES:
                    raise LivenessModelIntegrityError(
                        "face landmarker download exceeded expected byte count"
                    )
                digest.update(chunk)
                temporary.write(chunk)
            if total != FACE_LANDMARKER_SIZE_BYTES:
                raise LivenessModelIntegrityError(
                    "face landmarker download byte count mismatch"
                )
            if digest.hexdigest() != FACE_LANDMARKER_SHA256:
                raise LivenessModelIntegrityError(
                    "face landmarker download sha256 mismatch"
                )
        os.replace(temporary_path, target)
        temporary_path = None
        return verify_face_landmarker_model(target)
    except (OSError, urllib.error.URLError) as exc:
        raise LivenessModelAssetError("failed to download face landmarker model") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
