"""Development-only answerability verifier bake-off after Phase 4.5D V2 failure.

The V2 corpus is fully exposed and retired from acceptance. This harness reuses it only
for architecture selection. It widens the already-selected Qwen retrieve/rerank path to
ten candidates, then asks a revision-pinned multilingual SQuAD2 model whether the
selected memory actually contains an extractive answer to the memory question.

No result from this harness is final acceptance evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import step4_phase45d_abstention_calibration as baseline
import step4_phase45d_final_v2_cases as v2_cases

from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_CONTRACT,
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

QA_MODEL_ID = "deepset/xlm-roberta-base-squad2-distilled"
QA_MODEL_REVISION = "c1bbfe57bc3335c37960a48c5628ba26d7e9e3b7"
QA_MAX_SEQUENCE_LENGTH = 384
QA_MAX_ANSWER_LENGTH = 30
QA_N_BEST = 20
QWEN_CANDIDATE_WINDOW = 10
TARGET_PRECISION = 0.95
MIN_VALIDATION_RELEASE_RECALL = 0.40
MIN_VALIDATION_LANGUAGE_RELEASE_RECALL = 0.25
SECURITY_BOUNDARY_CATEGORIES = frozenset(
    {"historical", "forgotten", "local_only", "secret", "untrusted"}
)
OUTPUT_DEFAULT = Path(".step4-phase45d-v2-answerability-verifier-bakeoff-v1.json")


@dataclass(frozen=True, slots=True)
class RetrievalPair:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    query: str
    top_memory_id: str
    top_document: str
    positive_top1_correct: bool
    rerank_score: float
    rerank_margin: float | None

    @property
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct


@dataclass(frozen=True, slots=True)
class AnswerabilityCase:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    top_memory_id: str
    positive_top1_correct: bool
    rerank_score: float
    rerank_margin: float | None
    answerability_margin: float
    best_span_score: float
    null_score: float
    answer_char_length: int

    @property
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct


@dataclass(frozen=True, slots=True)
class AnswerabilityEvidence:
    margin: float
    best_span_score: float
    null_score: float
    answer_text: str


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 6)


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("p10", "p25", "p50", "p75", "p90", "p95")}
    array = np.asarray(values, dtype=np.float64)
    return {
        "p10": round(float(np.quantile(array, 0.10)), 6),
        "p25": round(float(np.quantile(array, 0.25)), 6),
        "p50": round(float(np.quantile(array, 0.50)), 6),
        "p75": round(float(np.quantile(array, 0.75)), 6),
        "p90": round(float(np.quantile(array, 0.90)), 6),
        "p95": round(float(np.quantile(array, 0.95)), 6),
    }


def _best_answerability_evidence(
    *,
    start_logits: Sequence[float] | np.ndarray,
    end_logits: Sequence[float] | np.ndarray,
    context_mask: Sequence[bool] | np.ndarray,
    offsets: Sequence[Sequence[int]],
    context: str,
    cls_index: int,
    n_best: int = QA_N_BEST,
    max_answer_length: int = QA_MAX_ANSWER_LENGTH,
) -> AnswerabilityEvidence:
    start = np.asarray(start_logits, dtype=np.float64).reshape(-1)
    end = np.asarray(end_logits, dtype=np.float64).reshape(-1)
    mask = np.asarray(context_mask, dtype=bool).reshape(-1)
    if start.shape != end.shape or start.shape != mask.shape:
        raise ValueError("QA logits and context mask must have matching one-dimensional shapes")
    if len(offsets) != start.shape[0]:
        raise ValueError("QA offset count must match logit count")
    if cls_index < 0 or cls_index >= start.shape[0]:
        raise ValueError("CLS index is out of range")
    if n_best <= 0 or max_answer_length <= 0:
        raise ValueError("QA n_best and max_answer_length must be positive")

    context_indexes = np.flatnonzero(mask)
    if context_indexes.size == 0:
        raise ValueError("QA input contains no context tokens")

    null_score = float(start[cls_index] + end[cls_index])
    top_start = context_indexes[
        np.argsort(start[context_indexes])[-min(n_best, context_indexes.size) :][::-1]
    ]
    top_end = context_indexes[
        np.argsort(end[context_indexes])[-min(n_best, context_indexes.size) :][::-1]
    ]

    best_score = -math.inf
    best_start = best_end = None
    for start_index in top_start:
        for end_index in top_end:
            start_int = int(start_index)
            end_int = int(end_index)
            if end_int < start_int:
                continue
            if end_int - start_int + 1 > max_answer_length:
                continue
            start_offset = offsets[start_int]
            end_offset = offsets[end_int]
            if len(start_offset) != 2 or len(end_offset) != 2:
                raise ValueError("QA offsets must contain start/end pairs")
            char_start = int(start_offset[0])
            char_end = int(end_offset[1])
            if char_end <= char_start:
                continue
            score = float(start[start_int] + end[end_int])
            if score > best_score:
                best_score = score
                best_start = char_start
                best_end = char_end

    if best_start is None or best_end is None or not math.isfinite(best_score):
        raise RuntimeError("QA verifier produced no legal non-null context span")

    answer_text = context[best_start:best_end]
    return AnswerabilityEvidence(
        margin=float(best_score - null_score),
        best_span_score=float(best_score),
        null_score=float(null_score),
        answer_text=answer_text,
    )


def _roc_auc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    values = np.asarray(scores, dtype=np.float64)
    targets = np.asarray(labels, dtype=bool)
    if values.shape != targets.shape or values.ndim != 1:
        raise ValueError("ROC-AUC scores and labels must be aligned one-dimensional arrays")
    positives = int(targets.sum())
    negatives = int((~targets).sum())
    if positives == 0 or negatives == 0:
        raise ValueError("ROC-AUC requires both positive and negative labels")

    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    cursor = 0
    while cursor < values.size:
        end = cursor + 1
        while end < values.size and values[order[end]] == values[order[cursor]]:
            end += 1
        average_rank = ((cursor + 1) + end) / 2.0
        ranks[order[cursor:end]] = average_rank
        cursor = end

    positive_rank_sum = float(ranks[targets].sum())
    auc = (
        positive_rank_sum - positives * (positives + 1) / 2.0
    ) / (positives * negatives)
    return round(float(auc), 6)


def _average_precision(scores: Sequence[float], labels: Sequence[bool]) -> float:
    values = np.asarray(scores, dtype=np.float64)
    targets = np.asarray(labels, dtype=bool)
    if values.shape != targets.shape or values.ndim != 1:
        raise ValueError("AP scores and labels must be aligned one-dimensional arrays")
    positives = int(targets.sum())
    if positives == 0:
        raise ValueError("average precision requires at least one positive label")

    order = np.argsort(-values, kind="mergesort")
    sorted_targets = targets[order]
    cumulative = np.cumsum(sorted_targets, dtype=np.int64)
    positive_positions = np.flatnonzero(sorted_targets)
    precision_at_positive = cumulative[positive_positions] / (positive_positions + 1)
    return round(float(precision_at_positive.sum() / positives), 6)


def _select_empirical_threshold(
    cases: Sequence[AnswerabilityCase],
    *,
    target_precision: float = TARGET_PRECISION,
) -> dict[str, Any] | None:
    if not 0.0 < target_precision <= 1.0:
        raise ValueError("target precision must be in (0, 1]")
    ordered = sorted(cases, key=lambda case: (-case.answerability_margin, case.case_id))
    positive_total = sum(case.label == "release" for case in ordered)
    if positive_total == 0:
        raise ValueError("threshold selection needs positive release cases")

    tp = fp = 0
    best: dict[str, Any] | None = None
    for index, case in enumerate(ordered):
        if case.safe_to_release:
            tp += 1
        else:
            fp += 1
        next_margin = (
            ordered[index + 1].answerability_margin
            if index + 1 < len(ordered)
            else None
        )
        if next_margin is not None and next_margin == case.answerability_margin:
            continue
        released = tp + fp
        precision = tp / released if released else 1.0
        recall = tp / positive_total
        if precision < target_precision:
            continue
        candidate = {
            "threshold": float(case.answerability_margin),
            "tp": tp,
            "fp": fp,
            "released_cases": released,
            "precision": round(precision, 6),
            "positive_release_recall": round(recall, 6),
        }
        if best is None or (
            candidate["positive_release_recall"],
            candidate["precision"],
            candidate["threshold"],
        ) > (
            best["positive_release_recall"],
            best["precision"],
            best["threshold"],
        ):
            best = candidate
    return best


def _policy_metrics(
    cases: Sequence[AnswerabilityCase], threshold: float | None
) -> dict[str, Any]:
    positive_total = sum(case.label == "release" for case in cases)
    tp = fp = 0
    false_release_ids: list[str] = []
    security_boundary_release_ids: list[str] = []
    released_ids: list[str] = []
    for case in cases:
        released = threshold is not None and case.answerability_margin >= threshold
        if not released:
            continue
        released_ids.append(case.case_id)
        if case.safe_to_release:
            tp += 1
        else:
            fp += 1
            false_release_ids.append(case.case_id)
        if case.category in SECURITY_BOUNDARY_CATEGORIES:
            security_boundary_release_ids.append(case.case_id)

    released_count = tp + fp
    precision = tp / released_count if released_count else 1.0
    recall = tp / positive_total if positive_total else 0.0
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "released_cases": released_count,
        "precision": round(precision, 6),
        "positive_release_recall": round(recall, 6),
        "released_case_ids": released_ids,
        "false_release_case_ids": false_release_ids,
        "security_boundary_release_case_ids": security_boundary_release_ids,
    }


def _language_metrics(
    cases: Sequence[AnswerabilityCase], threshold: float | None
) -> dict[str, Any]:
    return {
        language: _policy_metrics(
            [case for case in cases if case.language == language], threshold
        )
        for language in v2_cases.LANGUAGES
    }


def _category_false_releases(
    cases: Sequence[AnswerabilityCase], threshold: float | None
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    if threshold is None:
        return {}
    for case in cases:
        if case.answerability_margin >= threshold and not case.safe_to_release:
            counts[case.category] += 1
    return dict(sorted(counts.items()))


def _score_summary(cases: Sequence[AnswerabilityCase]) -> dict[str, Any]:
    safe = [case.answerability_margin for case in cases if case.safe_to_release]
    unsafe = [case.answerability_margin for case in cases if not case.safe_to_release]
    scores = [case.answerability_margin for case in cases]
    labels = [case.safe_to_release for case in cases]
    return {
        "roc_auc": _roc_auc(scores, labels),
        "average_precision": _average_precision(scores, labels),
        "safe_margin_quantiles": _quantiles(safe),
        "unsafe_margin_quantiles": _quantiles(unsafe),
    }


def _public_case(case: AnswerabilityCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "split": case.split,
        "label": case.label,
        "expected_memory_id": case.expected_memory_id,
        "language": case.language,
        "category": case.category,
        "top_memory_id": case.top_memory_id,
        "positive_top1_correct": case.positive_top1_correct,
        "rerank_score": case.rerank_score,
        "rerank_margin": case.rerank_margin,
        "answerability_margin": case.answerability_margin,
        "best_span_score": case.best_span_score,
        "null_score": case.null_score,
        "answer_char_length": case.answer_char_length,
        "safe_to_release": case.safe_to_release,
    }


async def _retrieve_pairs(device: str) -> tuple[list[RetrievalPair], dict[str, Any]]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc

    payload = v2_cases.build_payload()
    queries = list(payload["queries"])
    if len(queries) != 1800:
        raise RuntimeError("V2 query count changed unexpectedly")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-answerability-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "answerability.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-answerability-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-answerability-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)
        reranker = Qwen3RetrievalReranker(
            device=device,
            candidate_window=QWEN_CANDIDATE_WINDOW,
        )
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError("answerability bake-off must use frozen reranker instruction")

        pairs: list[RetrievalPair] = []
        query_embedding_ms: list[float] = []
        retrieval_ms: list[float] = []
        rerank_ms: list[float] = []
        try:
            populate_started = time.perf_counter()
            _, assertion_to_memory = await baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            populate_seconds = time.perf_counter() - populate_started

            for item in queries:
                query = str(item["query"])
                tick = time.perf_counter_ns()
                query_vector = embedder.encode_query(query)
                query_embedding_ms.append((time.perf_counter_ns() - tick) / 1_000_000)

                tick = time.perf_counter_ns()
                first_stage = await retrieval.retrieve_first_stage(
                    query,
                    query_vector,
                    eligibility=RetrievalEligibility.cloud_context(),
                    limit=QWEN_CANDIDATE_WINDOW,
                )
                retrieval_ms.append((time.perf_counter_ns() - tick) / 1_000_000)
                if not first_stage:
                    raise RuntimeError(f"no candidates for {item['case_id']}")

                tick = time.perf_counter_ns()
                reranked = reranker.rerank(query, first_stage)
                rerank_ms.append((time.perf_counter_ns() - tick) / 1_000_000)
                if not reranked:
                    raise RuntimeError(f"reranker returned nothing for {item['case_id']}")

                top = reranked[0]
                top_memory_id = assertion_to_memory.get(top.candidate.assertion.assertion_id)
                if top_memory_id is None:
                    raise RuntimeError(f"unknown top assertion for {item['case_id']}")
                expected = item.get("expected_memory_id")
                positive_top1_correct = (
                    item["label"] == "release" and top_memory_id == expected
                )
                margin = (
                    float(top.rerank_score - reranked[1].rerank_score)
                    if len(reranked) > 1
                    else None
                )
                pairs.append(
                    RetrievalPair(
                        case_id=str(item["case_id"]),
                        split=str(item["split"]),
                        label=str(item["label"]),
                        expected_memory_id=(str(expected) if expected is not None else None),
                        language=str(item["language"]),
                        category=str(item["category"]),
                        query=query,
                        top_memory_id=top_memory_id,
                        top_document=top.candidate.assertion.normalized_text,
                        positive_top1_correct=positive_top1_correct,
                        rerank_score=float(top.rerank_score),
                        rerank_margin=margin,
                    )
                )
        finally:
            await worker.close()

        qwen_peak_cuda_bytes = (
            int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
        )

    timing = {
        "fixture_population_and_document_embedding_seconds": round(populate_seconds, 4),
        "query_embedding_p50_ms": _percentile(query_embedding_ms, 0.50),
        "query_embedding_p95_ms": _percentile(query_embedding_ms, 0.95),
        "retrieval_top10_p50_ms": _percentile(retrieval_ms, 0.50),
        "retrieval_top10_p95_ms": _percentile(retrieval_ms, 0.95),
        "rerank_top10_p50_ms": _percentile(rerank_ms, 0.50),
        "rerank_top10_p95_ms": _percentile(rerank_ms, 0.95),
        "qwen_peak_cuda_bytes": qwen_peak_cuda_bytes,
    }
    return pairs, timing


def _load_qa(device: str) -> tuple[Any, Any, dict[str, Any]]:
    try:
        import torch
        from transformers import AutoModelForQuestionAnswering, AutoTokenizer
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("answerability bake-off requires Torch and Transformers") from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        QA_MODEL_ID,
        revision=QA_MODEL_REVISION,
        trust_remote_code=False,
        use_fast=True,
    )
    model = AutoModelForQuestionAnswering.from_pretrained(
        QA_MODEL_ID,
        revision=QA_MODEL_REVISION,
        trust_remote_code=False,
        use_safetensors=True,
    )
    model.to(device)
    model.eval()
    load_seconds = time.perf_counter() - started
    if tokenizer.cls_token_id is None:
        raise RuntimeError("QA tokenizer does not expose a CLS token")
    return tokenizer, model, {
        "model_id": QA_MODEL_ID,
        "revision": QA_MODEL_REVISION,
        "license": "MIT",
        "device": device,
        "model_load_seconds": round(load_seconds, 4),
        "max_sequence_length": QA_MAX_SEQUENCE_LENGTH,
        "max_answer_length": QA_MAX_ANSWER_LENGTH,
        "n_best": QA_N_BEST,
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


def _score_qa_pairs(
    tokenizer: Any,
    model: Any,
    pairs: Sequence[RetrievalPair],
    *,
    device: str,
    batch_size: int,
) -> tuple[list[AnswerabilityCase], dict[str, Any]]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc
    if batch_size <= 0:
        raise ValueError("batch size must be positive")

    output: list[AnswerabilityCase] = []
    batch_times: list[float] = []
    started_all = time.perf_counter()
    cls_token_id = int(tokenizer.cls_token_id)

    for start_index in range(0, len(pairs), batch_size):
        batch = list(pairs[start_index : start_index + batch_size])
        questions = [item.query for item in batch]
        contexts = [item.top_document for item in batch]
        encoded = tokenizer(
            questions,
            contexts,
            padding=True,
            truncation="only_second",
            max_length=QA_MAX_SEQUENCE_LENGTH,
            return_offsets_mapping=True,
            return_tensors="pt",
        )
        offsets = encoded.pop("offset_mapping").cpu().numpy()
        sequence_ids = [encoded.sequence_ids(index) for index in range(len(batch))]
        input_ids_cpu = encoded["input_ids"].cpu().numpy()
        model_inputs = {key: value.to(device) for key, value in encoded.items()}

        tick = time.perf_counter()
        with torch.inference_mode():
            result = model(**model_inputs)
        batch_times.append(time.perf_counter() - tick)
        start_logits = result.start_logits.detach().float().cpu().numpy()
        end_logits = result.end_logits.detach().float().cpu().numpy()

        for row_index, pair in enumerate(batch):
            cls_positions = np.flatnonzero(input_ids_cpu[row_index] == cls_token_id)
            if cls_positions.size == 0:
                raise RuntimeError(f"no CLS token for {pair.case_id}")
            context_mask = np.asarray(
                [sequence_id == 1 for sequence_id in sequence_ids[row_index]],
                dtype=bool,
            )
            evidence = _best_answerability_evidence(
                start_logits=start_logits[row_index],
                end_logits=end_logits[row_index],
                context_mask=context_mask,
                offsets=offsets[row_index],
                context=pair.top_document,
                cls_index=int(cls_positions[0]),
            )
            output.append(
                AnswerabilityCase(
                    case_id=pair.case_id,
                    split=pair.split,
                    label=pair.label,
                    expected_memory_id=pair.expected_memory_id,
                    language=pair.language,
                    category=pair.category,
                    top_memory_id=pair.top_memory_id,
                    positive_top1_correct=pair.positive_top1_correct,
                    rerank_score=pair.rerank_score,
                    rerank_margin=pair.rerank_margin,
                    answerability_margin=evidence.margin,
                    best_span_score=evidence.best_span_score,
                    null_score=evidence.null_score,
                    answer_char_length=len(evidence.answer_text),
                )
            )

    elapsed = time.perf_counter() - started_all
    timing = {
        "scoring_seconds": round(elapsed, 4),
        "per_pair_ms": round((elapsed * 1000.0) / len(pairs), 4) if pairs else None,
        "batch_p50_ms": _percentile([value * 1000.0 for value in batch_times], 0.50),
        "batch_p95_ms": _percentile([value * 1000.0 for value in batch_times], 0.95),
        "peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
        ),
    }
    return output, timing


def _ranking_summary(cases: Sequence[AnswerabilityCase]) -> dict[str, Any]:
    positives = [case for case in cases if case.label == "release"]
    correct = sum(case.positive_top1_correct for case in positives)
    return {
        "release_labels": len(positives),
        "positive_top1_correct": correct,
        "positive_top1_accuracy": round(correct / len(positives), 6) if positives else 0.0,
    }


def _development_selection(
    validation: Sequence[AnswerabilityCase], threshold: float | None
) -> dict[str, Any]:
    policy = _policy_metrics(validation, threshold)
    languages = _language_metrics(validation, threshold)
    checks = {
        "calibration_threshold_found": threshold is not None,
        "validation_precision": policy["precision"] >= TARGET_PRECISION,
        "validation_release_recall": (
            policy["positive_release_recall"] >= MIN_VALIDATION_RELEASE_RECALL
        ),
        "validation_language_release_recall": all(
            metrics["positive_release_recall"]
            >= MIN_VALIDATION_LANGUAGE_RELEASE_RECALL
            for metrics in languages.values()
        ),
        "validation_zero_security_boundary_releases": not policy[
            "security_boundary_release_case_ids"
        ],
    }
    return {
        "checks": checks,
        "selected_for_v3_freeze": all(checks.values()),
    }


async def _run(device: str, batch_size: int) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc

    pairs, retrieval_timing = await _retrieve_pairs(device)
    if len(pairs) != 1800:
        raise RuntimeError("retrieval pair count changed unexpectedly")

    # Release the Qwen model objects before loading the QA verifier so the diagnostic
    # measures a realistic sequential local-model path on the owner's 8 GB GPU.
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    tokenizer, qa_model, qa_environment = _load_qa(device)
    cases, qa_timing = _score_qa_pairs(
        tokenizer,
        qa_model,
        pairs,
        device=device,
        batch_size=batch_size,
    )
    calibration = [case for case in cases if case.split == "calibration"]
    validation = [case for case in cases if case.split == "validation"]
    if len(calibration) != 1200 or len(validation) != 600:
        raise RuntimeError("V2 split sizes changed unexpectedly")

    calibration_choice = _select_empirical_threshold(calibration)
    threshold = calibration_choice["threshold"] if calibration_choice is not None else None
    calibration_policy = _policy_metrics(calibration, threshold)
    validation_policy = _policy_metrics(validation, threshold)
    validation_languages = _language_metrics(validation, threshold)
    selection = _development_selection(validation, threshold)

    return {
        "status": "DEVELOPMENT_BAKEOFF_COMPLETE",
        "purpose": "Phase 4.5D task-matched multilingual answerability verifier bake-off",
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "validation_used_for_threshold_selection": False,
        "models": {
            "embedding": {
                "model_id": QWEN3_EMBEDDING_MODEL_ID,
                "revision": QWEN3_EMBEDDING_REVISION,
                "dimension": QWEN3_EMBEDDING_CONTRACT.dimension,
            },
            "reranker": {
                "model_id": QWEN3_RERANKER_MODEL_ID,
                "revision": QWEN3_RERANKER_REVISION,
                "candidate_window": QWEN_CANDIDATE_WINDOW,
                "instruction": JARVIS_MEMORY_RERANK_INSTRUCTION,
            },
            "answerability_verifier": qa_environment,
        },
        "targets": {
            "empirical_development_precision": TARGET_PRECISION,
            "minimum_validation_release_recall": MIN_VALIDATION_RELEASE_RECALL,
            "minimum_validation_language_release_recall": (
                MIN_VALIDATION_LANGUAGE_RELEASE_RECALL
            ),
        },
        "ranking": {
            "overall": _ranking_summary(cases),
            "calibration": _ranking_summary(calibration),
            "validation": _ranking_summary(validation),
        },
        "score_quality": {
            "overall": _score_summary(cases),
            "calibration": _score_summary(calibration),
            "validation": _score_summary(validation),
        },
        "calibration": {
            "selected_threshold": calibration_choice,
            "policy": calibration_policy,
        },
        "validation": {
            "policy": validation_policy,
            "languages": validation_languages,
            "false_releases_by_category": _category_false_releases(
                validation, threshold
            ),
        },
        "development_selection": selection,
        "timing": {
            "qwen": retrieval_timing,
            "answerability": qa_timing,
        },
        "cases": [_public_case(case) for case in cases],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch size must be positive")
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing answerability evidence: {output_path}"
        )
    output = asyncio.run(_run(args.device, args.batch_size))
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print("RANKING:", json.dumps(output["ranking"]))
    print("CALIBRATION:", json.dumps(output["calibration"]["selected_threshold"]))
    print("VALIDATION:", json.dumps(output["validation"]["policy"]))
    print("SELECTION:", json.dumps(output["development_selection"]))


if __name__ == "__main__":
    main()
