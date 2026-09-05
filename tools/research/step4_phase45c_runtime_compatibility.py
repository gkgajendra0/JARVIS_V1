"""Owner-machine Phase 4.5C local retrieval runtime compatibility harness.

This is a narrow acceptance harness, not production retrieval orchestration. It
verifies that the selected Qwen embedding/reranker adapters can run together on
the accepted JARVIS Torch/CUDA environment without changing the Step-3 vision
package set.
"""

from __future__ import annotations

import importlib
import json
import math
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

import numpy as np

from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.retrieval import RetrievalCandidate
from jarvis.memory.retrieval_models import (
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)

EXPECTED_VERSIONS = {
    "torch": "2.13.0",
    "sentence-transformers": "6.0.1",
    "transformers": "5.16.1",
}
VISION_PACKAGES = (
    "torchvision",
    "rfdetr",
    "trackers",
    "mediapipe",
    "opencv-python",
)
DOCUMENTS = (
    (
        "camera",
        "JARVIS vision camera is the DJI Osmo Pocket 3, used as the active visual sensor.",
    ),
    ("bike", "Gajendra owns a BMW G 310 GS motorcycle."),
    (
        "research_rule",
        "Before implementing a feature or fixing a problem, JARVIS must research current mature existing technology and prefer integrating the best suitable proven solution over custom building.",
    ),
)
QUERY = "Which device gives Jarvis eyes?"
NOW = datetime(2026, 9, 5, 19, 30, tzinfo=UTC)


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _release(version_text: str | None) -> str | None:
    if version_text is None:
        return None
    return version_text.split("+", 1)[0]


def _record(assertion_id: str, text: str) -> SemanticAssertionRecord:
    return SemanticAssertionRecord(
        assertion_id=assertion_id,
        subject_scope="owner",
        subject="owner",
        predicate="compatibility_memory",
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        source_id=f"compatibility:{assertion_id}",
        valid_from=None,
        valid_to=None,
        system_from=NOW,
        system_to=None,
        last_verified_at=None,
        state=AssertionState.ACTIVE,
        supersedes_id=None,
        verification_state=VerificationState.UNVERIFIED,
        confidence=None,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=Sensitivity.STANDARD,
        created_at=NOW,
        updated_at=NOW,
    )


def _candidate(
    assertion_id: str, text: str, rank: int, score: float
) -> RetrievalCandidate:
    return RetrievalCandidate(
        assertion=_record(assertion_id, text),
        fused_rank=rank,
        fused_score=1.0 / (60 + rank),
        lexical_rank=None,
        lexical_score=None,
        dense_rank=rank,
        dense_score=score,
    )


def main() -> None:
    import torch

    packages = {
        name: _package_version(name) for name in (*EXPECTED_VERSIONS, *VISION_PACKAGES)
    }
    checks: dict[str, bool] = {}
    for package, expected in EXPECTED_VERSIONS.items():
        checks[f"version:{package}"] = _release(packages[package]) == expected

    vision_imports: dict[str, str] = {}
    for module_name in ("torchvision", "rfdetr", "trackers", "mediapipe", "cv2"):
        try:
            importlib.import_module(module_name)
            vision_imports[module_name] = "ok"
        except Exception as exc:  # noqa: BLE001
            # Acceptance harness must report any import incompatibility.
            vision_imports[module_name] = f"{type(exc).__name__}: {exc}"
    checks["vision_imports"] = all(value == "ok" for value in vision_imports.values())

    checks["cuda_available"] = bool(torch.cuda.is_available())
    if not torch.cuda.is_available():
        output = {
            "status": "FAIL",
            "reason": "CUDA is not available",
            "packages": packages,
            "checks": checks,
            "vision_imports": vision_imports,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        raise SystemExit(1)

    torch.cuda.reset_peak_memory_stats()
    cuda_before = int(torch.cuda.memory_allocated())

    embedder = Qwen3EmbeddingEncoder(device="cuda")
    embed_started = time.perf_counter()
    query_vector = embedder.encode_query(QUERY)
    document_vectors = embedder.encode_documents([text for _, text in DOCUMENTS])
    embed_elapsed_ms = (time.perf_counter() - embed_started) * 1000.0

    dense_scores = [
        float(np.dot(query_vector.astype(np.float64), vector.astype(np.float64)))
        for vector in document_vectors
    ]
    dense_order = sorted(
        range(len(DOCUMENTS)),
        key=lambda index: (-dense_scores[index], DOCUMENTS[index][0]),
    )
    dense_ids = [DOCUMENTS[index][0] for index in dense_order]
    checks["embedding_shape"] = query_vector.shape == (256,) and all(
        vector.shape == (256,) for vector in document_vectors
    )
    checks["embedding_finite"] = bool(np.all(np.isfinite(query_vector))) and all(
        bool(np.all(np.isfinite(vector))) for vector in document_vectors
    )
    checks["embedding_normalized"] = math.isclose(
        float(np.linalg.norm(query_vector)), 1.0, rel_tol=1e-5, abs_tol=1e-5
    ) and all(
        math.isclose(float(np.linalg.norm(vector)), 1.0, rel_tol=1e-5, abs_tol=1e-5)
        for vector in document_vectors
    )
    checks["dense_camera_top1"] = dense_ids[0] == "camera"

    first_stage = tuple(
        _candidate(
            DOCUMENTS[index][0],
            DOCUMENTS[index][1],
            rank,
            dense_scores[index],
        )
        for rank, index in enumerate(dense_order, start=1)
    )
    reranker = Qwen3RetrievalReranker(device="cuda")
    rerank_started = time.perf_counter()
    reranked = reranker.rerank(QUERY, first_stage)
    rerank_elapsed_ms = (time.perf_counter() - rerank_started) * 1000.0
    reranked_ids = [item.candidate.assertion.assertion_id for item in reranked]
    reranker_scores = [item.rerank_score for item in reranked]
    checks["reranker_count"] = len(reranked) == 3
    checks["reranker_finite"] = all(math.isfinite(score) for score in reranker_scores)
    checks["reranker_camera_top1"] = bool(reranked_ids) and reranked_ids[0] == "camera"

    cuda_after = int(torch.cuda.memory_allocated())
    peak_cuda = int(torch.cuda.max_memory_allocated())
    checks["both_models_loaded"] = embedder.loaded and reranker.loaded

    status = "PASS" if all(checks.values()) else "FAIL"
    output = {
        "status": status,
        "purpose": "Phase 4.5C owner-machine compatibility acceptance",
        "packages": packages,
        "torch_runtime": {
            "torch_version": str(torch.__version__),
            "cuda_runtime": str(torch.version.cuda),
            "device_name": torch.cuda.get_device_name(0),
        },
        "vision_imports": vision_imports,
        "checks": checks,
        "embedding": {
            "query": QUERY,
            "dense_order": dense_ids,
            "dense_scores": [round(score, 6) for score in dense_scores],
            "elapsed_ms_including_lazy_load": round(embed_elapsed_ms, 3),
        },
        "reranker": {
            "order": reranked_ids,
            "scores": [round(score, 6) for score in reranker_scores],
            "elapsed_ms_including_lazy_load": round(rerank_elapsed_ms, 3),
        },
        "cuda_memory_bytes": {
            "before_models": cuda_before,
            "after_both_models": cuda_after,
            "peak_with_both_models": peak_cuda,
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
