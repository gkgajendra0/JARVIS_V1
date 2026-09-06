"""Development-only semantic judge bake-off after Phase 4.5D QA failure.

V2 is exposed and retired from acceptance. This harness keeps the proven Qwen 256d
retrieve/rerank path at candidate depth 10, then compares two task-matched semantic
judges on the same selected query/document pairs:

1. local GLiClass Multilang Mini zero-shot rule-following classification;
2. Gemini 3.5 Flash-Lite structured semantic sufficiency classification.

It also measures their conservative conjunction. No result from this harness is final
acceptance evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import step4_phase45d_answerability_verifier_bakeoff as answerability
import step4_phase45d_final_v2_cases as v2_cases
from pydantic import BaseModel, ValidationError

from jarvis.ai_provider import require_provider_api_key

GLICLASS_PACKAGE_VERSION = "0.1.20"
GLICLASS_MODEL_ID = "knowledgator/gliclass-multilang-mini"
GLICLASS_MODEL_REVISION = "c09fb5ca4cb7957044168e6bf8bcefa2e14b8dfb"
GLICLASS_RELEASE_LABEL = (
    "release: the memory directly and sufficiently answers the exact query, "
    "including the requested relation and temporal scope"
)
GLICLASS_ABSTAIN_LABEL = (
    "abstain: the memory does not directly and sufficiently answer the exact query"
)
GLICLASS_TASK_PROMPT = (
    "Classify JARVIS memory evidence conservatively. Release only when the memory "
    "directly and sufficiently answers the exact query using facts stated in the "
    "memory. Treat relation, subject, polarity and temporal scope as binding."
)

GEMINI_MODEL_ID = "gemini-3.5-flash-lite"
GEMINI_SYSTEM_PROMPT = """You are the semantic sufficiency verifier for JARVIS memory retrieval.

Classify EACH supplied case independently.

Return RELEASE only when the Memory document directly and sufficiently answers the exact Query using only facts explicitly stated in the Memory.

The requested subject, relation, polarity, modality, and temporal scope are binding. A Memory that is merely related, answers a different relation, answers current state when historical state was requested (or vice versa), is ambiguous, negated/contradictory, misses the requested detail, or requires an unsupported inference MUST be ABSTAIN.

Queries may be English, Hindi, or Hinglish. Do not prefer one language over another.

Never infer ground truth from the case index. Preserve every input index exactly once. Return only the requested schema.
"""

TARGET_PRECISION = 0.95
MIN_VALIDATION_RELEASE_RECALL = 0.40
MIN_VALIDATION_LANGUAGE_RELEASE_RECALL = 0.25
SECURITY_BOUNDARY_CATEGORIES = answerability.SECURITY_BOUNDARY_CATEGORIES
OUTPUT_DEFAULT = Path(".step4-phase45d-v2-semantic-judge-bakeoff-v1.json")


FailureMode = Literal[
    "none",
    "relation_mismatch",
    "temporal_mismatch",
    "ambiguous",
    "negated_or_contradictory",
    "missing_or_unsupported",
    "other",
]
Decision = Literal["release", "abstain"]


class GeminiJudgeItem(BaseModel):
    index: int
    decision: Decision
    failure_mode: FailureMode


class GeminiJudgeBatch(BaseModel):
    results: list[GeminiJudgeItem]


@dataclass(frozen=True, slots=True)
class GliclassEvidence:
    release_score: float
    abstain_score: float

    @property
    def margin(self) -> float:
        return self.release_score - self.abstain_score


@dataclass(frozen=True, slots=True)
class SemanticJudgeCase:
    pair: answerability.RetrievalPair
    gliclass: GliclassEvidence
    gemini_decision: Decision
    gemini_failure_mode: FailureMode

    @property
    def safe_to_release(self) -> bool:
        return self.pair.safe_to_release


@dataclass(frozen=True, slots=True)
class GeminiBatchResult:
    judgments: list[GeminiJudgeItem]
    elapsed_seconds: float
    usage: dict[str, int]


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


def _roc_auc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    values = np.asarray(scores, dtype=np.float64)
    targets = np.asarray(labels, dtype=np.bool_)
    if values.shape != targets.shape or values.ndim != 1:
        raise ValueError("ROC-AUC scores and labels must be aligned one-dimensional arrays")
    positives = int(targets.sum())
    negatives = int((~targets).sum())
    if positives == 0 or negatives == 0:
        return 0.0

    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.shape[0], dtype=np.float64)
    cursor = 0
    while cursor < values.shape[0]:
        end = cursor + 1
        while end < values.shape[0] and values[order[end]] == values[order[cursor]]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        ranks[order[cursor:end]] = average_rank
        cursor = end

    positive_rank_sum = float(ranks[targets].sum())
    auc = (positive_rank_sum - positives * (positives + 1) / 2.0) / (
        positives * negatives
    )
    return round(float(auc), 6)


def _average_precision(scores: Sequence[float], labels: Sequence[bool]) -> float:
    values = np.asarray(scores, dtype=np.float64)
    targets = np.asarray(labels, dtype=np.bool_)
    positives = int(targets.sum())
    if positives == 0:
        return 0.0
    order = np.argsort(-values, kind="mergesort")
    true_positives = 0
    precision_sum = 0.0
    for rank, index in enumerate(order, start=1):
        if targets[index]:
            true_positives += 1
            precision_sum += true_positives / rank
    return round(precision_sum / positives, 6)


def _ranking_summary(pairs: Sequence[answerability.RetrievalPair]) -> dict[str, Any]:
    positives = [pair for pair in pairs if pair.label == "release"]
    correct = sum(pair.positive_top1_correct for pair in positives)
    return {
        "release_labels": len(positives),
        "positive_top1_correct": correct,
        "positive_top1_accuracy": round(correct / len(positives), 6) if positives else 0.0,
    }


def _select_empirical_threshold(
    cases: Sequence[SemanticJudgeCase],
) -> dict[str, Any] | None:
    thresholds = sorted({case.gliclass.margin for case in cases}, reverse=True)
    positive_total = sum(case.pair.label == "release" for case in cases)
    best: dict[str, Any] | None = None
    for threshold in thresholds:
        released = [case for case in cases if case.gliclass.margin >= threshold]
        if not released:
            continue
        tp = sum(case.safe_to_release for case in released)
        fp = len(released) - tp
        precision = tp / len(released)
        recall = tp / positive_total if positive_total else 0.0
        if precision < TARGET_PRECISION:
            continue
        candidate = {
            "threshold": float(threshold),
            "tp": tp,
            "fp": fp,
            "released_cases": len(released),
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
    cases: Sequence[SemanticJudgeCase],
    release_predicate: Callable[[SemanticJudgeCase], bool],
) -> dict[str, Any]:
    positive_total = sum(case.pair.label == "release" for case in cases)
    tp = fp = 0
    released_ids: list[str] = []
    false_ids: list[str] = []
    security_ids: list[str] = []
    false_by_category: dict[str, int] = defaultdict(int)
    for case in cases:
        if not release_predicate(case):
            continue
        released_ids.append(case.pair.case_id)
        if case.safe_to_release:
            tp += 1
        else:
            fp += 1
            false_ids.append(case.pair.case_id)
            false_by_category[case.pair.category] += 1
        if case.pair.category in SECURITY_BOUNDARY_CATEGORIES:
            security_ids.append(case.pair.case_id)

    released_count = tp + fp
    precision = tp / released_count if released_count else 1.0
    recall = tp / positive_total if positive_total else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "released_cases": released_count,
        "precision": round(precision, 6),
        "positive_release_recall": round(recall, 6),
        "released_case_ids": released_ids,
        "false_release_case_ids": false_ids,
        "false_releases_by_category": dict(sorted(false_by_category.items())),
        "security_boundary_release_case_ids": security_ids,
    }


def _language_metrics(
    cases: Sequence[SemanticJudgeCase],
    release_predicate: Callable[[SemanticJudgeCase], bool],
) -> dict[str, Any]:
    return {
        language: _policy_metrics(
            [case for case in cases if case.pair.language == language],
            release_predicate,
        )
        for language in v2_cases.LANGUAGES
    }


def _development_checks(
    *,
    calibration_policy: dict[str, Any],
    validation_policy: dict[str, Any],
    validation_languages: dict[str, Any],
    decision_available: bool,
) -> dict[str, Any]:
    checks = {
        "decision_available": decision_available,
        "calibration_precision": calibration_policy["precision"] >= TARGET_PRECISION,
        "validation_precision": validation_policy["precision"] >= TARGET_PRECISION,
        "validation_release_recall": (
            validation_policy["positive_release_recall"]
            >= MIN_VALIDATION_RELEASE_RECALL
        ),
        "validation_language_release_recall": all(
            metrics["positive_release_recall"]
            >= MIN_VALIDATION_LANGUAGE_RELEASE_RECALL
            for metrics in validation_languages.values()
        ),
        "validation_zero_security_boundary_releases": not validation_policy[
            "security_boundary_release_case_ids"
        ],
    }
    return {
        "checks": checks,
        "promising_for_v3_design": all(checks.values()),
    }


def _score_quality(cases: Sequence[SemanticJudgeCase]) -> dict[str, Any]:
    scores = [case.gliclass.margin for case in cases]
    labels = [case.safe_to_release for case in cases]
    safe_scores = [case.gliclass.margin for case in cases if case.safe_to_release]
    unsafe_scores = [case.gliclass.margin for case in cases if not case.safe_to_release]
    return {
        "roc_auc": _roc_auc(scores, labels),
        "average_precision": _average_precision(scores, labels),
        "safe_margin_quantiles": _quantiles(safe_scores),
        "unsafe_margin_quantiles": _quantiles(unsafe_scores),
    }


def _load_gliclass(device: str) -> tuple[Any, dict[str, Any]]:
    try:
        import gliclass
        import torch
        from gliclass import GLiClassModel, ZeroShotClassificationPipeline
        from transformers import AutoTokenizer
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "semantic judge bake-off requires gliclass==0.1.20 and retrieval dependencies"
        ) from exc

    installed_version = getattr(gliclass, "__version__", None)
    if installed_version != GLICLASS_PACKAGE_VERSION:
        raise RuntimeError(
            f"expected gliclass {GLICLASS_PACKAGE_VERSION}, got {installed_version!r}"
        )
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA semantic judge bake-off requested but CUDA is unavailable")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        GLICLASS_MODEL_ID,
        revision=GLICLASS_MODEL_REVISION,
        trust_remote_code=False,
    )
    model = GLiClassModel.from_pretrained(
        GLICLASS_MODEL_ID,
        revision=GLICLASS_MODEL_REVISION,
    )
    pipeline = ZeroShotClassificationPipeline(
        model,
        tokenizer,
        classification_type="multi-label",
        device="cuda:0" if device == "cuda" else "cpu",
    )
    load_seconds = time.perf_counter() - started
    metadata = {
        "package": "gliclass",
        "package_version": installed_version,
        "model_id": GLICLASS_MODEL_ID,
        "revision": GLICLASS_MODEL_REVISION,
        "license": "Apache-2.0",
        "device": device,
        "model_load_seconds": round(load_seconds, 4),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    return pipeline, metadata


def _score_gliclass(
    pipeline: Any,
    pairs: Sequence[answerability.RetrievalPair],
) -> tuple[list[GliclassEvidence], dict[str, Any]]:
    labels = [GLICLASS_RELEASE_LABEL, GLICLASS_ABSTAIN_LABEL]
    started = time.perf_counter()
    evidence: list[GliclassEvidence] = []
    for pair in pairs:
        text = f"Query:\n{pair.query}\n\nMemory document:\n{pair.top_document}"
        raw = pipeline(
            text,
            labels,
            prompt=GLICLASS_TASK_PROMPT,
            threshold=0.0,
        )
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], list):
            raise RuntimeError(f"unexpected GLiClass output shape for {pair.case_id}")
        scores = {
            str(item.get("label")): float(item.get("score"))
            for item in raw[0]
            if isinstance(item, dict)
        }
        if set(scores) != set(labels):
            raise RuntimeError(
                f"GLiClass did not return both frozen labels for {pair.case_id}: {scores}"
            )
        evidence.append(
            GliclassEvidence(
                release_score=scores[GLICLASS_RELEASE_LABEL],
                abstain_score=scores[GLICLASS_ABSTAIN_LABEL],
            )
        )
    elapsed = time.perf_counter() - started

    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc
    timing = {
        "cases": len(pairs),
        "scoring_seconds": round(elapsed, 4),
        "milliseconds_per_case": round(elapsed * 1000.0 / len(pairs), 4),
        "peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
        ),
    }
    return evidence, timing


def _usage_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _extract_usage(response: Any) -> dict[str, int]:
    raw = _usage_to_dict(
        getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
    )
    aliases = {
        "input_tokens": ("input_tokens", "input_token_count", "prompt_token_count"),
        "output_tokens": (
            "output_tokens",
            "output_token_count",
            "candidates_token_count",
        ),
        "total_tokens": ("total_tokens", "total_token_count"),
    }
    result: dict[str, int] = {}
    for target, keys in aliases.items():
        for key in keys:
            value = raw.get(key)
            if isinstance(value, int):
                result[target] = value
                break
    return result


def _batched(
    pairs: Sequence[answerability.RetrievalPair], batch_size: int
) -> list[list[answerability.RetrievalPair]]:
    return [list(pairs[index : index + batch_size]) for index in range(0, len(pairs), batch_size)]


async def _call_gemini_batch(
    client: Any,
    batch: Sequence[answerability.RetrievalPair],
    *,
    semaphore: asyncio.Semaphore,
) -> GeminiBatchResult:
    input_payload = {
        "cases": [
            {
                "index": index,
                "query": pair.query,
                "memory": pair.top_document,
            }
            for index, pair in enumerate(batch)
        ]
    }

    async with semaphore:
        last_error: Exception | None = None
        for attempt in range(5):
            started = time.perf_counter()
            try:
                response = await client.aio.interactions.create(
                    model=GEMINI_MODEL_ID,
                    input=json.dumps(input_payload, ensure_ascii=False),
                    system_instruction=GEMINI_SYSTEM_PROMPT,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": GeminiJudgeBatch.model_json_schema(),
                    },
                    store=False,
                )
                elapsed = time.perf_counter() - started
                output_text = getattr(response, "output_text", None)
                if not isinstance(output_text, str) or not output_text.strip():
                    raise RuntimeError("Gemini returned no semantic-judge output")
                try:
                    parsed = GeminiJudgeBatch.model_validate_json(output_text)
                except ValidationError as exc:
                    raise RuntimeError("Gemini returned invalid semantic-judge JSON") from exc

                expected_indexes = set(range(len(batch)))
                actual_indexes = [item.index for item in parsed.results]
                if len(actual_indexes) != len(set(actual_indexes)):
                    raise RuntimeError("Gemini repeated a semantic-judge case index")
                if set(actual_indexes) != expected_indexes:
                    raise RuntimeError(
                        "Gemini semantic-judge indexes do not match the submitted batch"
                    )
                ordered = sorted(parsed.results, key=lambda item: item.index)
                return GeminiBatchResult(
                    judgments=ordered,
                    elapsed_seconds=elapsed,
                    usage=_extract_usage(response),
                )
            except Exception as exc:  # noqa: BLE001 - API retry boundary is deliberate
                last_error = exc
                message = str(exc).upper()
                retryable = any(
                    marker in message
                    for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")
                )
                if not retryable or attempt == 4:
                    raise
                await asyncio.sleep(2**attempt)
        raise AssertionError(f"unreachable Gemini retry state: {last_error}")


async def _score_gemini(
    pairs: Sequence[answerability.RetrievalPair],
    *,
    batch_size: int,
    concurrency: int,
) -> tuple[list[GeminiJudgeItem], dict[str, Any]]:
    from google import genai

    api_key = require_provider_api_key("gemini", purpose="semantic verifier bake-off")
    client = genai.Client(api_key=api_key)
    batches = _batched(pairs, batch_size)
    semaphore = asyncio.Semaphore(concurrency)
    started = time.perf_counter()
    results = await asyncio.gather(
        *[
            _call_gemini_batch(client, batch, semaphore=semaphore)
            for batch in batches
        ]
    )
    elapsed = time.perf_counter() - started

    judgments: list[GeminiJudgeItem] = []
    usage_totals: Counter[str] = Counter()
    request_seconds: list[float] = []
    for result in results:
        judgments.extend(result.judgments)
        request_seconds.append(result.elapsed_seconds)
        usage_totals.update(result.usage)
    if len(judgments) != len(pairs):
        raise RuntimeError("Gemini judgment count does not match retrieval pair count")

    timing = {
        "model_id": GEMINI_MODEL_ID,
        "requests": len(batches),
        "cases": len(pairs),
        "batch_size": batch_size,
        "concurrency": concurrency,
        "wall_seconds": round(elapsed, 4),
        "mean_request_seconds": round(sum(request_seconds) / len(request_seconds), 4),
        "usage": dict(usage_totals),
    }
    return judgments, timing


def _public_case(case: SemanticJudgeCase) -> dict[str, Any]:
    return {
        "case_id": case.pair.case_id,
        "split": case.pair.split,
        "label": case.pair.label,
        "expected_memory_id": case.pair.expected_memory_id,
        "language": case.pair.language,
        "category": case.pair.category,
        "top_memory_id": case.pair.top_memory_id,
        "positive_top1_correct": case.pair.positive_top1_correct,
        "rerank_score": case.pair.rerank_score,
        "rerank_margin": case.pair.rerank_margin,
        "gliclass_release_score": case.gliclass.release_score,
        "gliclass_abstain_score": case.gliclass.abstain_score,
        "gliclass_margin": case.gliclass.margin,
        "gemini_decision": case.gemini_decision,
        "gemini_failure_mode": case.gemini_failure_mode,
        "safe_to_release": case.safe_to_release,
    }


async def _run(
    device: str,
    gemini_batch_size: int,
    gemini_concurrency: int,
) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc

    pairs, retrieval_timing = await answerability._retrieve_pairs(device)
    if len(pairs) != 1800:
        raise RuntimeError("retrieval pair count changed unexpectedly")
    if _ranking_summary(pairs)["positive_top1_correct"] != 900:
        raise RuntimeError("top-10 Qwen ranking no longer reproduces 900/900 positives")

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    gliclass_pipeline, gliclass_environment = _load_gliclass(device)
    gliclass_evidence, gliclass_timing = _score_gliclass(gliclass_pipeline, pairs)

    gemini_judgments, gemini_timing = await _score_gemini(
        pairs,
        batch_size=gemini_batch_size,
        concurrency=gemini_concurrency,
    )

    cases = [
        SemanticJudgeCase(
            pair=pair,
            gliclass=evidence,
            gemini_decision=judgment.decision,
            gemini_failure_mode=judgment.failure_mode,
        )
        for pair, evidence, judgment in zip(
            pairs,
            gliclass_evidence,
            gemini_judgments,
            strict=True,
        )
    ]
    calibration = [case for case in cases if case.pair.split == "calibration"]
    validation = [case for case in cases if case.pair.split == "validation"]
    if len(calibration) != 1200 or len(validation) != 600:
        raise RuntimeError("V2 split sizes changed unexpectedly")

    threshold_choice = _select_empirical_threshold(calibration)
    threshold = threshold_choice["threshold"] if threshold_choice is not None else None

    gliclass_predicate = (
        (lambda case: case.gliclass.margin >= float(threshold))
        if threshold is not None
        else (lambda case: False)
    )
    gemini_predicate = lambda case: case.gemini_decision == "release"
    conjunction_predicate = lambda case: (
        threshold is not None
        and case.gemini_decision == "release"
        and case.gliclass.margin >= float(threshold)
    )

    policies: dict[str, Any] = {}
    selections: dict[str, Any] = {}
    for name, predicate, available in (
        ("gliclass", gliclass_predicate, threshold is not None),
        ("gemini", gemini_predicate, True),
        ("conjunction", conjunction_predicate, threshold is not None),
    ):
        calibration_policy = _policy_metrics(calibration, predicate)
        validation_policy = _policy_metrics(validation, predicate)
        languages = _language_metrics(validation, predicate)
        policies[name] = {
            "calibration": calibration_policy,
            "validation": validation_policy,
            "validation_languages": languages,
        }
        selections[name] = _development_checks(
            calibration_policy=calibration_policy,
            validation_policy=validation_policy,
            validation_languages=languages,
            decision_available=available,
        )

    promising = [
        name
        for name, result in selections.items()
        if result["promising_for_v3_design"]
    ]

    return {
        "status": "DEVELOPMENT_SEMANTIC_JUDGE_BAKEOFF_COMPLETE",
        "purpose": "Phase 4.5D local-vs-cloud semantic sufficiency judge selection",
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "validation_used_for_gliclass_threshold_selection": False,
        "models": {
            "retrieval": {
                "embedding_model_id": answerability.QWEN3_EMBEDDING_MODEL_ID,
                "embedding_revision": answerability.QWEN3_EMBEDDING_REVISION,
                "embedding_dimension": answerability.QWEN3_EMBEDDING_CONTRACT.dimension,
                "reranker_model_id": answerability.QWEN3_RERANKER_MODEL_ID,
                "reranker_revision": answerability.QWEN3_RERANKER_REVISION,
                "candidate_window": answerability.QWEN_CANDIDATE_WINDOW,
            },
            "gliclass": {
                **gliclass_environment,
                "release_label": GLICLASS_RELEASE_LABEL,
                "abstain_label": GLICLASS_ABSTAIN_LABEL,
                "task_prompt": GLICLASS_TASK_PROMPT,
            },
            "gemini": {
                "model_id": GEMINI_MODEL_ID,
                "provider": "gemini",
                "structured_output": True,
                "system_prompt": GEMINI_SYSTEM_PROMPT,
            },
        },
        "targets": {
            "empirical_development_precision": TARGET_PRECISION,
            "minimum_validation_release_recall": MIN_VALIDATION_RELEASE_RECALL,
            "minimum_validation_language_release_recall": (
                MIN_VALIDATION_LANGUAGE_RELEASE_RECALL
            ),
        },
        "ranking": {
            "overall": _ranking_summary(pairs),
            "calibration": _ranking_summary(
                [pair for pair in pairs if pair.split == "calibration"]
            ),
            "validation": _ranking_summary(
                [pair for pair in pairs if pair.split == "validation"]
            ),
        },
        "gliclass_score_quality": {
            "overall": _score_quality(cases),
            "calibration": _score_quality(calibration),
            "validation": _score_quality(validation),
        },
        "gliclass_selected_threshold": threshold_choice,
        "policies": policies,
        "development_selection": {
            **selections,
            "promising_candidates": promising,
            "selected_for_v3_freeze": False,
            "note": (
                "A promising V2 development candidate still requires architecture review "
                "and a completely fresh V3 acceptance protocol before any freeze."
            ),
        },
        "gemini_diagnostics": {
            "failure_modes": dict(
                sorted(Counter(case.gemini_failure_mode for case in cases).items())
            ),
            "release_decisions": sum(
                case.gemini_decision == "release" for case in cases
            ),
            "abstain_decisions": sum(
                case.gemini_decision == "abstain" for case in cases
            ),
        },
        "timing": {
            "qwen": retrieval_timing,
            "gliclass": gliclass_timing,
            "gemini": gemini_timing,
        },
        "cases": [_public_case(case) for case in cases],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-batch-size", type=int, default=8)
    parser.add_argument("--gemini-concurrency", type=int, default=4)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gemini_batch_size <= 0:
        raise ValueError("Gemini batch size must be positive")
    if args.gemini_concurrency <= 0:
        raise ValueError("Gemini concurrency must be positive")
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing semantic-judge evidence: {output_path}"
        )

    output = asyncio.run(
        _run(
            args.device,
            args.gemini_batch_size,
            args.gemini_concurrency,
        )
    )
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print("RANKING:", json.dumps(output["ranking"]))
    print(
        "GLICLASS_THRESHOLD:",
        json.dumps(output["gliclass_selected_threshold"]),
    )
    for name in ("gliclass", "gemini", "conjunction"):
        print(
            name.upper() + ":",
            json.dumps(output["policies"][name]["validation"]),
        )
        print(
            name.upper() + "_SELECTION:",
            json.dumps(output["development_selection"][name]),
        )
    print(
        "PROMISING:",
        json.dumps(output["development_selection"]["promising_candidates"]),
    )


if __name__ == "__main__":
    main()
