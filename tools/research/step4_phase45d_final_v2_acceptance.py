"""One-shot Phase 4.5D V2 learned-confidence acceptance harness.

Retired 320-case evidence may fit the already-selected low-capacity confidence model
and learn MAPIE SFST threshold order. Fresh V2 calibration controls precision; fresh
V2 validation only evaluates the frozen threshold. Validation never tunes anything.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import step4_phase45d_abstention_calibration as baseline
import step4_phase45d_feature_gate_diagnostic as feature_gate
import step4_phase45d_final_v2_cases as v2_cases
import step4_phase45d_independent_verifier_bakeoff as verifier_dev

from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_MODEL_ID,
    QWEN3_EMBEDDING_REVISION,
    SemanticEmbeddingStore,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    QWEN3_RERANKER_MODEL_ID,
    QWEN3_RERANKER_REVISION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)

MAPIE_REQUIRED_VERSION = "1.5.0"
TARGET_PRECISION = 0.95
CONFIDENCE_LEVEL = 0.95
MIN_VALIDATION_POSITIVE_TOP1_ACCURACY = 0.85
MIN_VALIDATION_POSITIVE_RECALL_AT_3 = 0.90
MIN_VALIDATION_RELEASE_RECALL = 0.40
MIN_VALIDATION_LANGUAGE_RELEASE_RECALL = 0.25
REQUIRE_ZERO_VALIDATION_FALSE_RELEASES = True

VERIFIER_MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
VERIFIER_MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
VERIFIER_BATCH_SIZE = 32
VERIFIER_MAX_LENGTH = 512

FEATURE_NAMES = (
    "rerank_score",
    "rerank_margin",
    "dense_score",
    "fused_score",
    "lexical_hit",
    "reciprocal_lexical_rank",
    "reciprocal_dense_rank",
    "independent_verifier_score",
)

# Frozen before V2 labels are exposed. With SFST, the order is learned on independent
# retired development rows and only that fixed order is tested on fresh calibration.
PROBABILITY_THRESHOLDS = np.linspace(0.50, 0.999, 101, dtype=np.float64)
PREDICT_PARAMS = PROBABILITY_THRESHOLDS.reshape(-1, 1)

RETIRED_DEVELOPMENT_DEFAULT = Path(".step4-phase45d-final-acceptance.json")
OUTPUT_DEFAULT = Path(".step4-phase45d-final-v2-acceptance.json")
SECURITY_CATEGORIES = frozenset(v2_cases.SECURITY_BOUNDARY_CATEGORIES)


@dataclass(frozen=True, slots=True)
class V2CaseResult:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    top_memory_id: str
    top_document: str
    positive_top1_correct: bool
    positive_hit_at_3: bool
    rerank_score: float
    rerank_margin: float
    dense_score: float
    lexical_rank: int | None
    dense_rank: int | None
    fused_score: float
    independent_verifier_score: float
    confidence_probability: float
    query_embedding_ms: float
    retrieval_ms: float
    rerank_ms: float

    @property
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _controller_cls() -> type[Any]:
    try:
        import mapie
        from mapie.risk_control import BinaryClassificationController
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            f"Phase 4.5D V2 requires research-only MAPIE=={MAPIE_REQUIRED_VERSION}"
        ) from exc
    installed = str(getattr(mapie, "__version__", "unknown"))
    if installed != MAPIE_REQUIRED_VERSION:
        raise RuntimeError(
            f"expected MAPIE {MAPIE_REQUIRED_VERSION}, found {installed}"
        )
    return BinaryClassificationController


def _probability_release_predict(values: Any, threshold: float) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 2 and array.shape[1] == 1:
        array = array[:, 0]
    if array.ndim != 1 or not np.all(np.isfinite(array)):
        raise ValueError("confidence values must be finite with shape (n,) or (n, 1)")
    return (array >= float(threshold)).astype(np.int64)


def _threshold(value: Any) -> float | None:
    if value is None:
        return None
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.shape != (1,) or not np.isfinite(array[0]):
        raise RuntimeError(f"invalid MAPIE threshold: {value!r}")
    return float(array[0])


def _retrieval_row_from_mapping(case: dict[str, Any]) -> list[float]:
    return feature_gate._feature_row(case, feature_gate.FULL_EVIDENCE)


def _fit_confidence_model(
    retired_artifact: dict[str, Any], verifier_scores: np.ndarray
) -> tuple[Any, np.ndarray, np.ndarray, dict[str, Any]]:
    cases = list(retired_artifact["cases"])
    if len(cases) != 320 or verifier_scores.shape != (320,):
        raise RuntimeError(
            "confidence fit requires exactly 320 retired development rows"
        )
    base = verifier_dev._base_matrix(cases)
    X = np.column_stack((base, verifier_scores))
    y = verifier_dev._labels(cases)
    model = feature_gate._pipeline()
    model.fit(X, y)
    probabilities = np.asarray(model.predict_proba(X)[:, 1], dtype=np.float64)

    scaler = model.named_steps["scale"]
    logistic = model.named_steps["model"]
    frozen = {
        "feature_names": list(FEATURE_NAMES),
        "training_source": "retired_exposed_320_case_development_artifact",
        "training_rows": 320,
        "qwen_retrieval_rerun": False,
        "standard_scaler": {
            "mean": [float(value) for value in scaler.mean_.tolist()],
            "scale": [float(value) for value in scaler.scale_.tolist()],
        },
        "logistic_regression": {
            "solver": str(logistic.solver),
            "max_iter": int(logistic.max_iter),
            "random_state": int(logistic.random_state),
            "classes": [int(value) for value in logistic.classes_.tolist()],
            "coef": [
                [float(value) for value in row] for row in logistic.coef_.tolist()
            ],
            "intercept": [float(value) for value in logistic.intercept_.tolist()],
        },
    }
    return model, probabilities, y, frozen


def _load_verifier(device: str) -> tuple[Any, dict[str, Any]]:
    try:
        import torch
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            "Sentence Transformers retrieval dependencies are required"
        ) from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = CrossEncoder(
        VERIFIER_MODEL_ID,
        revision=VERIFIER_MODEL_REVISION,
        device=device,
        trust_remote_code=False,
        max_length=VERIFIER_MAX_LENGTH,
    )
    return model, {
        "model_id": VERIFIER_MODEL_ID,
        "model_revision": VERIFIER_MODEL_REVISION,
        "batch_size": VERIFIER_BATCH_SIZE,
        "max_length": VERIFIER_MAX_LENGTH,
        "device": device,
        "model_load_seconds": round(time.perf_counter() - started, 4),
        "torch_version": str(torch.__version__),
        "cuda_runtime": str(torch.version.cuda),
        "cuda_available": bool(torch.cuda.is_available()),
        "device_name": torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else None,
    }


def _score_pairs(model: Any, pairs: list[tuple[str, str]]) -> tuple[np.ndarray, float]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc
    started = time.perf_counter()
    raw = model.predict(
        pairs,
        batch_size=VERIFIER_BATCH_SIZE,
        show_progress_bar=True,
        activation_fn=torch.nn.Identity(),
    )
    elapsed = time.perf_counter() - started
    scores = np.asarray(raw, dtype=np.float64).reshape(-1)
    if scores.shape != (len(pairs),) or not np.all(np.isfinite(scores)):
        raise RuntimeError("independent verifier emitted invalid scores")
    return scores, elapsed


def _calibrate(
    development_probabilities: np.ndarray,
    development_labels: np.ndarray,
    calibration_probabilities: np.ndarray,
    calibration_labels: np.ndarray,
) -> tuple[float | None, dict[str, Any]]:
    controller = _controller_cls()(
        predict_function=_probability_release_predict,
        risk="precision",
        target_level=TARGET_PRECISION,
        confidence_level=CONFIDENCE_LEVEL,
        best_predict_param_choice="recall",
        list_predict_params=PREDICT_PARAMS,
        fwer_method="split_fixed_sequence",
    )
    controller.learn_fixed_sequence_order(
        X_learn=development_probabilities.reshape(-1, 1),
        y_learn=development_labels,
        binary=True,
    )
    learned = np.asarray(controller._learned_fixed_sequence, dtype=np.float64)
    controller.calibrate(calibration_probabilities.reshape(-1, 1), calibration_labels)
    best = _threshold(controller.best_predict_param)
    valid_raw = np.asarray(controller.valid_predict_params, dtype=np.float64)
    valid = [] if valid_raw.size == 0 else valid_raw.reshape(-1).tolist()
    return best, {
        "library": "MAPIE",
        "version": MAPIE_REQUIRED_VERSION,
        "risk": "precision",
        "target_precision": TARGET_PRECISION,
        "confidence_level": CONFIDENCE_LEVEL,
        "fwer_method": "split_fixed_sequence",
        "binary_order_learning": True,
        "order_learning_source": "retired_320_case_development_data",
        "calibration_source": "fresh_v2_calibration_only",
        "candidate_thresholds": PROBABILITY_THRESHOLDS.tolist(),
        "learned_threshold_order": learned.reshape(-1).tolist(),
        "valid_thresholds": [float(value) for value in valid],
        "valid_threshold_count": len(valid),
        "best_threshold": best,
        "best_predict_param_choice": "recall",
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 4)


def _ranking(cases: list[V2CaseResult]) -> dict[str, Any]:
    positives = [case for case in cases if case.label == "release"]
    if not positives:
        return {
            "release_labels": 0,
            "positive_top1_accuracy": 0.0,
            "positive_recall_at_3": 0.0,
        }
    top1 = sum(case.positive_top1_correct for case in positives)
    hit3 = sum(case.positive_hit_at_3 for case in positives)
    return {
        "release_labels": len(positives),
        "positive_top1_correct": top1,
        "positive_hit_at_3": hit3,
        "positive_top1_accuracy": round(top1 / len(positives), 6),
        "positive_recall_at_3": round(hit3 / len(positives), 6),
    }


def _metrics(cases: list[V2CaseResult], threshold: float | None) -> dict[str, Any]:
    released = np.asarray(
        [
            threshold is not None and case.confidence_probability >= threshold
            for case in cases
        ],
        dtype=bool,
    )
    safe = np.asarray([case.safe_to_release for case in cases], dtype=bool)
    release_labels = np.asarray([case.label == "release" for case in cases], dtype=bool)
    tp = int(np.sum(released & safe))
    fp = int(np.sum(released & ~safe))
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / int(np.sum(release_labels)) if np.any(release_labels) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "released_cases": int(np.sum(released)),
        "precision": round(precision, 6),
        "positive_release_recall": round(recall, 6),
        "false_release_case_ids": [
            case.case_id
            for case, decision, is_safe in zip(cases, released, safe, strict=True)
            if decision and not is_safe
        ],
        "security_boundary_release_case_ids": [
            case.case_id
            for case, decision in zip(cases, released, strict=True)
            if decision and case.category in SECURITY_CATEGORIES
        ],
    }


def _breakdown(
    cases: list[V2CaseResult], threshold: float | None, attribute: str
) -> dict[str, Any]:
    grouped: dict[str, list[V2CaseResult]] = defaultdict(list)
    for case in cases:
        grouped[str(getattr(case, attribute))].append(case)
    return {
        key: {
            "cases": len(values),
            "ranking": _ranking(values),
            "policy": _metrics(values, threshold),
        }
        for key, values in sorted(grouped.items())
    }


def _acceptance(
    validation: list[V2CaseResult], threshold: float | None
) -> dict[str, Any]:
    ranking = _ranking(validation)
    policy = _metrics(validation, threshold)
    languages = _breakdown(validation, threshold, "language")
    language_recall = {
        key: value["policy"]["positive_release_recall"]
        for key, value in languages.items()
    }
    checks = {
        "mapie_found_valid_threshold": threshold is not None,
        "validation_positive_top1_accuracy": (
            ranking["positive_top1_accuracy"] >= MIN_VALIDATION_POSITIVE_TOP1_ACCURACY
        ),
        "validation_positive_recall_at_3": (
            ranking["positive_recall_at_3"] >= MIN_VALIDATION_POSITIVE_RECALL_AT_3
        ),
        "validation_zero_false_releases": (
            policy["fp"] == 0 if REQUIRE_ZERO_VALIDATION_FALSE_RELEASES else True
        ),
        "validation_release_recall": (
            policy["positive_release_recall"] >= MIN_VALIDATION_RELEASE_RECALL
        ),
        "validation_language_release_recall": (
            set(language_recall) == set(v2_cases.LANGUAGES)
            and all(
                value >= MIN_VALIDATION_LANGUAGE_RELEASE_RECALL
                for value in language_recall.values()
            )
        ),
        "validation_zero_security_boundary_releases": (
            not policy["security_boundary_release_case_ids"]
        ),
    }
    return {"checks": checks, "pass": all(checks.values())}


async def _retrieve_v2(device: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    payload = v2_cases.build_payload()
    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-v2-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "acceptance.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-v2-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-v2-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)
        reranker = Qwen3RetrievalReranker(device=device)
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError("V2 must use the frozen JARVIS reranker instruction")
        try:
            started = time.perf_counter()
            _, assertion_to_memory = await baseline._populate_database(
                payload, lifecycle, embeddings, embedder
            )
            populate_seconds = time.perf_counter() - started
            rows: list[dict[str, Any]] = []
            for item in payload["queries"]:
                query = str(item["query"])
                tick = time.perf_counter_ns()
                query_vector = embedder.encode_query(query)
                embedding_ms = (time.perf_counter_ns() - tick) / 1_000_000
                tick = time.perf_counter_ns()
                first_stage = await retrieval.retrieve_first_stage(
                    query,
                    query_vector,
                    eligibility=RetrievalEligibility.cloud_context(),
                    limit=3,
                )
                retrieval_ms = (time.perf_counter_ns() - tick) / 1_000_000
                if not first_stage:
                    raise RuntimeError(f"no candidates for {item['case_id']}")
                tick = time.perf_counter_ns()
                reranked = reranker.rerank(query, first_stage)
                rerank_ms = (time.perf_counter_ns() - tick) / 1_000_000
                if not reranked:
                    raise RuntimeError(
                        f"reranker returned nothing for {item['case_id']}"
                    )
                top = reranked[0]
                second = (
                    reranked[1].rerank_score if len(reranked) > 1 else top.rerank_score
                )
                top_memory_id = assertion_to_memory.get(
                    top.candidate.assertion.assertion_id
                )
                if top_memory_id is None:
                    raise RuntimeError(
                        f"unknown returned assertion for {item['case_id']}"
                    )
                top3_ids = [
                    assertion_to_memory[value.candidate.assertion.assertion_id]
                    for value in reranked
                ]
                dense_score = top.candidate.dense_score
                if dense_score is None or not math.isfinite(dense_score):
                    raise RuntimeError(f"missing dense score for {item['case_id']}")
                expected = item.get("expected_memory_id")
                label = str(item["label"])
                rows.append(
                    {
                        "case_id": str(item["case_id"]),
                        "split": str(item["split"]),
                        "label": label,
                        "expected_memory_id": str(expected)
                        if expected is not None
                        else None,
                        "language": str(item["language"]),
                        "category": str(item["category"]),
                        "query": query,
                        "top_memory_id": top_memory_id,
                        "top_document": top.candidate.assertion.normalized_text,
                        "positive_top1_correct": label == "release"
                        and top_memory_id == expected,
                        "positive_hit_at_3": label == "release"
                        and expected in top3_ids,
                        "rerank_score": float(top.rerank_score),
                        "rerank_margin": float(top.rerank_score - second),
                        "dense_score": float(dense_score),
                        "lexical_rank": top.candidate.lexical_rank,
                        "dense_rank": top.candidate.dense_rank,
                        "fused_score": float(top.candidate.fused_score),
                        "query_embedding_ms": embedding_ms,
                        "retrieval_ms": retrieval_ms,
                        "rerank_ms": rerank_ms,
                    }
                )
        finally:
            await worker.close()
    return rows, {
        "fixture_population_and_document_embedding_seconds": round(populate_seconds, 4),
        "query_embedding_p50_ms": _percentile(
            [row["query_embedding_ms"] for row in rows], 0.50
        ),
        "query_embedding_p95_ms": _percentile(
            [row["query_embedding_ms"] for row in rows], 0.95
        ),
        "retrieval_p50_ms": _percentile([row["retrieval_ms"] for row in rows], 0.50),
        "retrieval_p95_ms": _percentile([row["retrieval_ms"] for row in rows], 0.95),
        "rerank_p50_ms": _percentile([row["rerank_ms"] for row in rows], 0.50),
        "rerank_p95_ms": _percentile([row["rerank_ms"] for row in rows], 0.95),
        "qwen_peak_cuda_bytes": int(torch.cuda.max_memory_allocated())
        if torch.cuda.is_available()
        else None,
    }


def _materialize(
    rows: list[dict[str, Any]], verifier_scores: np.ndarray, confidence_model: Any
) -> list[V2CaseResult]:
    if verifier_scores.shape != (len(rows),):
        raise RuntimeError("V2 verifier score count mismatch")
    base = np.asarray(
        [_retrieval_row_from_mapping(row) for row in rows], dtype=np.float64
    )
    X = np.column_stack((base, verifier_scores))
    probabilities = np.asarray(
        confidence_model.predict_proba(X)[:, 1], dtype=np.float64
    )
    output: list[V2CaseResult] = []
    for row, verifier_score, probability in zip(
        rows, verifier_scores, probabilities, strict=True
    ):
        values = dict(row)
        values.pop("query")
        values["independent_verifier_score"] = float(verifier_score)
        values["confidence_probability"] = float(probability)
        output.append(V2CaseResult(**values))
    return output


def _public_case(case: V2CaseResult) -> dict[str, Any]:
    payload = asdict(case)
    payload.pop("top_document")
    payload["safe_to_release"] = case.safe_to_release
    return payload


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    retired_path = Path(args.retired_development)
    retired = verifier_dev._load_artifact(retired_path)
    retired_pairs = verifier_dev._pair_records(retired)

    verifier, verifier_environment = _load_verifier(args.device)
    retired_scores, retired_seconds = _score_pairs(
        verifier,
        [(record["query"], record["document"]) for record in retired_pairs],
    )
    confidence_model, dev_probabilities, dev_labels, frozen_model = (
        _fit_confidence_model(retired, retired_scores)
    )

    rows, qwen_timing = await _retrieve_v2(args.device)
    v2_scores, v2_seconds = _score_pairs(
        verifier, [(row["query"], row["top_document"]) for row in rows]
    )
    results = _materialize(rows, v2_scores, confidence_model)
    calibration = [case for case in results if case.split == "calibration"]
    validation = [case for case in results if case.split == "validation"]
    if len(calibration) != 1200 or len(validation) != 600:
        raise RuntimeError("V2 split sizes changed unexpectedly")

    calibration_probabilities = np.asarray(
        [case.confidence_probability for case in calibration], dtype=np.float64
    )
    calibration_labels = np.asarray(
        [case.safe_to_release for case in calibration], dtype=np.int64
    )
    best, mapie = _calibrate(
        dev_probabilities,
        dev_labels,
        calibration_probabilities,
        calibration_labels,
    )
    acceptance = _acceptance(validation, best)
    payload = v2_cases.build_payload()

    verifier_environment.update(
        {
            "retired_pair_scoring_seconds": round(retired_seconds, 4),
            "v2_pair_scoring_seconds": round(v2_seconds, 4),
            "v2_per_pair_ms": round((v2_seconds * 1000.0) / len(rows), 4),
        }
    )
    return {
        "status": "PASS" if acceptance["pass"] else "FAIL_ACCEPTANCE",
        "purpose": "Phase 4.5D final V2 learned-confidence release acceptance",
        "final_acceptance_eligible": True,
        "phase45e_blocked_until_pass_and_closure": True,
        "retired_development": {
            "path": str(retired_path),
            "sha256": _file_sha256(retired_path),
            "cases": 320,
            "used_for": [
                "fit_frozen_low_capacity_confidence_model",
                "learn_split_fixed_sequence_threshold_order",
            ],
            "qwen_retrieval_rerun": False,
            "acceptance_evidence": False,
        },
        "models": {
            "embedding": {
                "model_id": QWEN3_EMBEDDING_MODEL_ID,
                "revision": QWEN3_EMBEDDING_REVISION,
            },
            "reranker": {
                "model_id": QWEN3_RERANKER_MODEL_ID,
                "revision": QWEN3_RERANKER_REVISION,
                "instruction": JARVIS_MEMORY_RERANK_INSTRUCTION,
            },
            "independent_verifier": verifier_environment,
            "confidence_model": frozen_model,
        },
        "corpus": {
            "schema_version": v2_cases.V2_CORPUS_SCHEMA_VERSION,
            "sha256": v2_cases.payload_sha256(payload),
            "documents": len(payload["documents"]),
            "queries": len(payload["queries"]),
            "calibration_labels": dict(Counter(case.label for case in calibration)),
            "validation_labels": dict(Counter(case.label for case in validation)),
            "validation_languages": dict(Counter(case.language for case in validation)),
            "retired_query_acceptance_reuse": False,
            "exchangeability_claim": False,
            "exchangeability_note": (
                "Synthetic V2 data do not establish exchangeability with future owner traffic; "
                "operational shadow-labelled risk/drift review remains required."
            ),
        },
        "mapie": mapie,
        "calibration": {
            "ranking": _ranking(calibration),
            "policy": _metrics(calibration, best),
            "languages": _breakdown(calibration, best, "language"),
            "categories": _breakdown(calibration, best, "category"),
        },
        "validation": {
            "ranking": _ranking(validation),
            "policy": _metrics(validation, best),
            "languages": _breakdown(validation, best, "language"),
            "categories": _breakdown(validation, best, "category"),
        },
        "acceptance": acceptance,
        "timing": qwen_timing,
        "validation_used_for_tuning": False,
        "cases": [_public_case(case) for case in results],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retired-development", default=str(RETIRED_DEVELOPMENT_DEFAULT)
    )
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing exposed V2 evidence: {output_path}"
        )
    output = asyncio.run(_run(args))
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print("ACCEPTANCE:", json.dumps(output["acceptance"]))


if __name__ == "__main__":
    main()
