from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.identity.active_speaker import (
    LR_ASD_AVA_FILENAME,
    LR_ASD_AVA_GIT_BLOB_SHA1,
    LR_ASD_AVA_SIZE_BYTES,
    LR_ASD_SOURCE_COMMIT,
)

LR_ASD_AVA_URL = (
    "https://raw.githubusercontent.com/Junhua-Liao/LR-ASD/"
    f"{LR_ASD_SOURCE_COMMIT}/weight/{LR_ASD_AVA_FILENAME}"
)


class ActiveSpeakerAssetError(RuntimeError):
    pass


class ActiveSpeakerAssetIntegrityError(ActiveSpeakerAssetError):
    pass


def default_lr_asd_model_path() -> Path:
    configured = os.getenv("JARVIS_LR_ASD_MODEL_PATH")
    if configured and not configured.strip().casefold().startswith("index:"):
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "JARVIS" / "models" / "lr-asd" / LR_ASD_AVA_FILENAME
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "jarvis" / "models" / "lr-asd" / LR_ASD_AVA_FILENAME
    return Path.home() / ".cache" / "jarvis" / "models" / "lr-asd" / LR_ASD_AVA_FILENAME


def verify_lr_asd_model(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_file():
        raise ActiveSpeakerAssetIntegrityError(f"LR-ASD model is missing: {candidate}")
    payload = candidate.read_bytes()
    if len(payload) != LR_ASD_AVA_SIZE_BYTES:
        raise ActiveSpeakerAssetIntegrityError(
            f"LR-ASD model size mismatch: expected {LR_ASD_AVA_SIZE_BYTES}, got {len(payload)}"
        )
    header = f"blob {len(payload)}\0".encode()
    digest = hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()
    if digest != LR_ASD_AVA_GIT_BLOB_SHA1:
        raise ActiveSpeakerAssetIntegrityError(
            "LR-ASD model does not match the pinned official Git blob"
        )
    return candidate


def ensure_lr_asd_model(
    path: str | Path | None = None,
    *,
    timeout_seconds: float = 120.0,
) -> Path:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    target = Path(path).expanduser() if path is not None else default_lr_asd_model_path()
    if target.is_file():
        return verify_lr_asd_model(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        LR_ASD_AVA_URL,
        headers={"User-Agent": "JARVIS-V1-lr-asd-model-fetch/1"},
    )
    temporary_path: Path | None = None
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout_seconds) as response,
            tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{LR_ASD_AVA_FILENAME}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary,
        ):
            temporary_path = Path(temporary.name)
            total = 0
            chunks: list[bytes] = []
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > LR_ASD_AVA_SIZE_BYTES:
                    raise ActiveSpeakerAssetIntegrityError(
                        "LR-ASD download exceeded expected byte count"
                    )
                chunks.append(chunk)
                temporary.write(chunk)
            if total != LR_ASD_AVA_SIZE_BYTES:
                raise ActiveSpeakerAssetIntegrityError(
                    "LR-ASD download byte count mismatch"
                )
            payload = b"".join(chunks)
            header = f"blob {len(payload)}\0".encode()
            digest = hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()
            if digest != LR_ASD_AVA_GIT_BLOB_SHA1:
                raise ActiveSpeakerAssetIntegrityError(
                    "LR-ASD download did not match the pinned official Git blob"
                )
        os.replace(temporary_path, target)
        temporary_path = None
        return verify_lr_asd_model(target)
    except (OSError, urllib.error.URLError) as exc:
        raise ActiveSpeakerAssetError("failed to download LR-ASD model") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
