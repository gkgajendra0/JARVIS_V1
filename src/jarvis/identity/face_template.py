from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

_MAGIC = b"JFT1"
_HEADER_LENGTH = struct.Struct(">I")
_TEMPLATE_FORMAT = "sface-prototype-set-v1"
_SELECTION_METHOD = "centroid-plus-farthest-inlier-v1"


class FaceTemplateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FacePrototypeSet:
    prototypes: np.ndarray
    source_sample_count: int
    inlier_sample_count: int
    centroid_inlier_floor: float
    coverage_minimum: float
    coverage_p05: float
    coverage_median: float

    @property
    def prototype_count(self) -> int:
        return int(self.prototypes.shape[0])

    @property
    def embedding_dimension(self) -> int:
        return int(self.prototypes.shape[1])


def _normalize_feature(feature: np.ndarray) -> np.ndarray:
    vector = np.asarray(feature, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise FaceTemplateError("face feature must be finite and non-empty")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise FaceTemplateError("face feature norm must be positive")
    return vector / norm


def build_face_prototype_set(
    features: Sequence[np.ndarray],
    *,
    prototype_count: int = 8,
    inlier_percentile: float = 5.0,
) -> FacePrototypeSet:
    if prototype_count < 2:
        raise FaceTemplateError("prototype_count must be at least 2")
    if len(features) < prototype_count * 2:
        raise FaceTemplateError(
            "OWNER prototype selection needs at least twice the prototype count"
        )
    if not 0 <= inlier_percentile < 50:
        raise FaceTemplateError("inlier_percentile must be in [0, 50)")

    normalized = np.stack([_normalize_feature(feature) for feature in features]).astype(
        np.float32,
        copy=False,
    )
    dimension = normalized.shape[1]
    if dimension <= 0:
        raise FaceTemplateError("embedding dimension must be positive")
    if any(row.size != dimension for row in normalized):
        raise FaceTemplateError("face features must share one embedding dimension")

    centroid = _normalize_feature(np.mean(normalized, axis=0))
    centroid_scores = normalized @ centroid
    inlier_floor = float(np.percentile(centroid_scores, inlier_percentile))
    inlier_indices = np.flatnonzero(centroid_scores >= inlier_floor)
    if inlier_indices.size < prototype_count - 1:
        order = np.argsort(-centroid_scores, kind="stable")
        inlier_indices = order[: prototype_count - 1]

    selected: list[np.ndarray] = [centroid]
    used: set[int] = set()
    while len(selected) < prototype_count:
        selected_matrix = np.stack(selected)
        best_index: int | None = None
        best_distance = -1.0
        for raw_index in inlier_indices.tolist():
            index = int(raw_index)
            if index in used:
                continue
            candidate = normalized[index]
            maximum_similarity = float(np.max(selected_matrix @ candidate))
            distance = 1.0 - maximum_similarity
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index is None:
            raise FaceTemplateError("unable to select distinct OWNER prototypes")
        used.add(best_index)
        selected.append(normalized[best_index])

    prototypes = np.stack(selected).astype(np.float32, copy=False)
    coverage = np.max(normalized @ prototypes.T, axis=1)
    return FacePrototypeSet(
        prototypes=prototypes,
        source_sample_count=len(features),
        inlier_sample_count=int(inlier_indices.size),
        centroid_inlier_floor=inlier_floor,
        coverage_minimum=float(np.min(coverage)),
        coverage_p05=float(np.percentile(coverage, 5)),
        coverage_median=float(np.median(coverage)),
    )


def serialize_face_prototype_set(template: FacePrototypeSet) -> bytes:
    matrix = np.asarray(template.prototypes, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] <= 0:
        raise FaceTemplateError(
            "prototype matrix must be two-dimensional and non-empty"
        )
    if not np.isfinite(matrix).all():
        raise FaceTemplateError("prototype matrix must be finite")

    normalized = np.stack([_normalize_feature(row) for row in matrix]).astype("<f4")
    header = {
        "schema_version": 1,
        "template_format": _TEMPLATE_FORMAT,
        "selection_method": _SELECTION_METHOD,
        "prototype_count": int(normalized.shape[0]),
        "embedding_dimension": int(normalized.shape[1]),
        "dtype": "float32-le",
        "normalization": "l2",
        "source_sample_count": int(template.source_sample_count),
        "inlier_sample_count": int(template.inlier_sample_count),
    }
    header_bytes = json.dumps(
        header,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return (
        _MAGIC
        + _HEADER_LENGTH.pack(len(header_bytes))
        + header_bytes
        + normalized.tobytes()
    )


def deserialize_face_prototype_set(payload: bytes) -> np.ndarray:
    if len(payload) < len(_MAGIC) + _HEADER_LENGTH.size:
        raise FaceTemplateError("face template payload is truncated")
    if payload[:4] != _MAGIC:
        raise FaceTemplateError("face template magic is invalid")

    header_length = _HEADER_LENGTH.unpack(payload[4:8])[0]
    header_end = 8 + header_length
    if header_length <= 0 or header_end > len(payload):
        raise FaceTemplateError("face template header length is invalid")
    try:
        header = json.loads(payload[8:header_end].decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaceTemplateError("face template header is invalid") from exc
    if not isinstance(header, dict):
        raise FaceTemplateError("face template header must be an object")
    if header.get("schema_version") != 1:
        raise FaceTemplateError("unsupported face template schema version")
    if header.get("template_format") != _TEMPLATE_FORMAT:
        raise FaceTemplateError("unsupported face template format")
    if header.get("selection_method") != _SELECTION_METHOD:
        raise FaceTemplateError("unsupported face template selection method")
    if header.get("dtype") != "float32-le" or header.get("normalization") != "l2":
        raise FaceTemplateError("unsupported face template numeric encoding")

    prototype_count = header.get("prototype_count")
    dimension = header.get("embedding_dimension")
    if not isinstance(prototype_count, int) or prototype_count < 2:
        raise FaceTemplateError("invalid face prototype count")
    if not isinstance(dimension, int) or dimension <= 0:
        raise FaceTemplateError("invalid face embedding dimension")

    body = payload[header_end:]
    expected_size = prototype_count * dimension * np.dtype("<f4").itemsize
    if len(body) != expected_size:
        raise FaceTemplateError("face template payload size does not match header")
    matrix = np.frombuffer(body, dtype="<f4").reshape(prototype_count, dimension).copy()
    if not np.isfinite(matrix).all():
        raise FaceTemplateError("face template contains non-finite values")
    norms = np.linalg.norm(matrix, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise FaceTemplateError("face template prototypes are not L2-normalized")
    return matrix


FACE_TEMPLATE_FORMAT = _TEMPLATE_FORMAT
