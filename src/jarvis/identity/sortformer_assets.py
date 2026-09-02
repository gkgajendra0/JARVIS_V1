from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

SORTFORMER_MODEL_ID = "nvidia/diar_streaming_sortformer_4spk-v2"
SORTFORMER_MODEL_REVISION = "5240a64075176943f677d30fa2171c780229f341"
SORTFORMER_MODEL_FILENAME = "diar_streaming_sortformer_4spk-v2.q8_0.gguf"
SORTFORMER_MODEL_SIZE_BYTES = 147_075_776
SORTFORMER_MODEL_SHA256 = (
    "0679cfeb1ce356d0dea9470b31274f4bfc7eb927497d82005483770666da998a"
)
SORTFORMER_MODEL_URL = (
    f"https://huggingface.co/{SORTFORMER_MODEL_ID}/resolve/"
    f"{SORTFORMER_MODEL_REVISION}/{SORTFORMER_MODEL_FILENAME}"
)


class SortformerAssetError(RuntimeError):
    pass


class SortformerAssetIntegrityError(SortformerAssetError):
    pass


def default_sortformer_model_path() -> Path:
    configured = os.getenv("JARVIS_SORTFORMER_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return (
            Path(local_app_data)
            / "JARVIS"
            / "models"
            / "diarization"
            / SORTFORMER_MODEL_FILENAME
        )
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return (
            Path(xdg_cache)
            / "jarvis"
            / "models"
            / "diarization"
            / SORTFORMER_MODEL_FILENAME
        )
    return (
        Path.home()
        / ".cache"
        / "jarvis"
        / "models"
        / "diarization"
        / SORTFORMER_MODEL_FILENAME
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sortformer_model(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise SortformerAssetIntegrityError(
            f"Sortformer model is missing: {candidate}"
        )
    size = candidate.stat().st_size
    if size != SORTFORMER_MODEL_SIZE_BYTES:
        raise SortformerAssetIntegrityError(
            "Sortformer model size mismatch: "
            f"expected {SORTFORMER_MODEL_SIZE_BYTES}, got {size}"
        )
    actual = _sha256(candidate)
    if actual != SORTFORMER_MODEL_SHA256:
        raise SortformerAssetIntegrityError(
            "Sortformer model sha256 mismatch: "
            f"expected {SORTFORMER_MODEL_SHA256}, got {actual}"
        )
    return candidate


def ensure_sortformer_model(
    path: str | Path | None = None,
    *,
    timeout_seconds: float = 300.0,
) -> Path:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    target = (
        Path(path).expanduser() if path is not None else default_sortformer_model_path()
    )
    if target.is_file():
        return verify_sortformer_model(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        SORTFORMER_MODEL_URL,
        headers={"User-Agent": "JARVIS-V1-sortformer-model-fetch/1"},
    )
    temporary_path: Path | None = None
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout_seconds) as response,
            tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{SORTFORMER_MODEL_FILENAME}.",
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
                if total > SORTFORMER_MODEL_SIZE_BYTES:
                    raise SortformerAssetIntegrityError(
                        "Sortformer download exceeded the pinned byte count"
                    )
                digest.update(chunk)
                temporary.write(chunk)
            if total != SORTFORMER_MODEL_SIZE_BYTES:
                raise SortformerAssetIntegrityError(
                    "Sortformer download size mismatch: "
                    f"expected {SORTFORMER_MODEL_SIZE_BYTES}, got {total}"
                )
            actual = digest.hexdigest()
            if actual != SORTFORMER_MODEL_SHA256:
                raise SortformerAssetIntegrityError(
                    "Sortformer download did not match the pinned SHA-256"
                )
        os.replace(temporary_path, target)
        temporary_path = None
        return verify_sortformer_model(target)
    except SortformerAssetError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise SortformerAssetError(
            "failed to download the pinned Sortformer model"
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
