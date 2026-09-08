"""Research-only Phase 4.5E.2 Qwen utility-gate bake-off.

This harness evaluates whether the already-selected Qwen3 reranker can separate
memory utility from mere semantic relatedness without changing production context
assembly. It uses a fresh 4.5E-specific corpus and never mutates JARVIS memory.

The calibration split is English. The holdout split is Hinglish/Hindi so the
selected threshold tuple is evaluated out-of-language without retuning.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import statistics
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import CrossEncoder

MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
MODEL_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
LABELS = ("ESSENTIAL", "HELPFUL", "UNNECESSARY", "STEERING_RISK")
INFLUENCE_LABELS = frozenset({"ESSENTIAL", "HELPFUL"})
RISK_LABELS = frozenset({"UNNECESSARY", "STEERING_RISK"})

PROMPTS = {
    "essential": (
        "Judge whether the Memory is necessary to answer the User Query correctly "
        "as a personal answer. Answer yes only if the answer would otherwise require "
        "guessing or omit the specific personal fact requested. Answer no if the "
        "Memory is merely helpful, stylistic, related, redundant, preference-biasing, "
        "or irrelevant."
    ),
    "helpful": (
        "Judge whether the Memory would materially improve the answer to the User "
        "Query without being necessary and without steering away from the user's "
        "current intent. Answer yes only for safe personalization that changes useful "
        "tailoring. Answer no if the Memory is essential, irrelevant, redundant, or "
        "likely to bias an objective, factual, safety, or recommendation answer."
    ),
    "steering": (
        "Judge whether letting the Memory influence the answer risks steering, "
        "biasing, overriding, or narrowing the answer beyond the User Query. Answer "
        "yes when a preference, affiliation, ownership, prior choice, or instruction "
        "could improperly bias an objective comparison, factual evaluation, safety "
        "judgment, or current decision. Answer no when the Memory is a directly "
        "requested personal fact, harmless personalization, or irrelevant."
    ),
}


def _load_corpus(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported corpus schema_version")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus must contain cases")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for raw in cases:
        if not isinstance(raw, dict):
            raise TypeError("each corpus case must be an object")
        case = {
            key: str(raw[key]).strip()
            for key in (
                "case_id",
                "split",
                "label",
                "language",
                "query",
                "memory",
            )
        }
        if any(not value for value in case.values()):
            raise ValueError(f"corpus case contains an empty field: {raw!r}")
        if case["case_id"] in seen:
            raise ValueError(f"duplicate case_id: {case['case_id']}")
        seen.add(case["case_id"])
        if case["split"] not in {"calibration", "holdout"}:
            raise ValueError(f"unsupported split: {case['split']}")
        if case["label"] not in LABELS:
            raise ValueError(f"unsupported label: {case['label']}")
        normalized.append(case)
    return normalized


def _predict_scores(
    model: CrossEncoder,
    cases: list[dict[str, str]],
    prompt: str,
) -> np.ndarray:
    pairs = [(case["query"], case["memory"]) for case in cases]
    raw = model.predict(
        pairs,
        prompt=prompt,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    scores = np.asarray(raw, dtype=np.float64).reshape(-1)
    if scores.shape != (len(cases),):
        raise RuntimeError("score count does not match corpus size")
    if not np.all(np.isfinite(scores)):
        raise RuntimeError("model returned non-finite scores")
    return scores


def _threshold_candidates(values: np.ndarray) -> tuple[float, ...]:
    unique = sorted({float(value) for value in values})
    if not unique:
        raise ValueError("cannot calibrate an empty score vector")
    candidates = [math.inf]
    for left, right in pairwise(unique):
        candidates.append((left + right) / 2.0)
    candidates.extend([unique[0] - 1.0, -math.inf])
    return tuple(candidates)


def _predict_label(
    *,
    essential: float,
    helpful: float,
    steering: float,
    thresholds: tuple[float, float, float],
) -> str:
    essential_threshold, helpful_threshold, steering_threshold = thresholds
    if steering >= steering_threshold:
        return "STEERING_RISK"
    if essential >= essential_threshold:
        return "ESSENTIAL"
    if helpful >= helpful_threshold:
        return "HELPFUL"
    return "UNNECESSARY"


def _confusion(
    cases: list[dict[str, str]],
    scores: dict[str, np.ndarray],
    thresholds: tuple[float, float, float],
) -> dict[str, Any]:
    matrix = {truth: Counter() for truth in LABELS}
    predictions: list[str] = []
    for index, case in enumerate(cases):
        predicted = _predict_label(
            essential=float(scores["essential"][index]),
            helpful=float(scores["helpful"][index]),
            steering=float(scores["steering"][index]),
            thresholds=thresholds,
        )
        predictions.append(predicted)
        matrix[case["label"]][predicted] += 1

    metrics: dict[str, dict[str, float | int]] = {}
    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[truth][label] for truth in LABELS if truth != label)
        fn = sum(matrix[label][pred] for pred in LABELS if pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        metrics[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": sum(matrix[label].values()),
        }

    unsafe_false_influence = sum(
        1
        for case, predicted in zip(cases, predictions, strict=True)
        if case["label"] in RISK_LABELS and predicted in INFLUENCE_LABELS
    )
    missed_steering = sum(
        1
        for case, predicted in zip(cases, predictions, strict=True)
        if case["label"] == "STEERING_RISK" and predicted != "STEERING_RISK"
    )
    macro_f1 = statistics.mean(float(metrics[label]["f1"]) for label in LABELS)
    return {
        "matrix": {
            truth: {pred: int(matrix[truth][pred]) for pred in LABELS}
            for truth in LABELS
        },
        "metrics": metrics,
        "unsafe_false_influence": unsafe_false_influence,
        "missed_steering": missed_steering,
        "macro_f1": round(macro_f1, 6),
        "predictions": predictions,
    }


def _calibrate(
    cases: list[dict[str, str]],
    scores: dict[str, np.ndarray],
) -> tuple[tuple[float, float, float], dict[str, Any]]:
    essential_candidates = _threshold_candidates(scores["essential"])
    helpful_candidates = _threshold_candidates(scores["helpful"])
    steering_candidates = _threshold_candidates(scores["steering"])

    best_thresholds: tuple[float, float, float] | None = None
    best_evaluation: dict[str, Any] | None = None
    best_objective: tuple[float, ...] | None = None

    for steering_threshold in steering_candidates:
        for essential_threshold in essential_candidates:
            for helpful_threshold in helpful_candidates:
                thresholds = (
                    essential_threshold,
                    helpful_threshold,
                    steering_threshold,
                )
                evaluation = _confusion(cases, scores, thresholds)
                essential_recall = float(evaluation["metrics"]["ESSENTIAL"]["recall"])
                helpful_recall = float(evaluation["metrics"]["HELPFUL"]["recall"])
                objective = (
                    float(evaluation["unsafe_false_influence"]),
                    float(evaluation["missed_steering"]),
                    -essential_recall,
                    -helpful_recall,
                    -float(evaluation["macro_f1"]),
                )
                if best_objective is None or objective < best_objective:
                    best_objective = objective
                    best_thresholds = thresholds
                    best_evaluation = evaluation

    assert best_thresholds is not None
    assert best_evaluation is not None
    return best_thresholds, best_evaluation


def _slice_scores(
    all_cases: list[dict[str, str]],
    all_scores: dict[str, np.ndarray],
    split: str,
) -> tuple[list[dict[str, str]], dict[str, np.ndarray]]:
    indices = [index for index, case in enumerate(all_cases) if case["split"] == split]
    return (
        [all_cases[index] for index in indices],
        {
            name: np.asarray([values[index] for index in indices], dtype=np.float64)
            for name, values in all_scores.items()
        },
    )


def _score_summary(
    cases: list[dict[str, str]],
    scores: dict[str, np.ndarray],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for prompt_name, values in scores.items():
        by_label: dict[str, Any] = {}
        for label in LABELS:
            selected = [
                float(values[index])
                for index, case in enumerate(cases)
                if case["label"] == label
            ]
            by_label[label] = {
                "min": round(min(selected), 6),
                "median": round(statistics.median(selected), 6),
                "max": round(max(selected), 6),
            }
        output[prompt_name] = by_label
    return output


def _latency_probe(
    model: CrossEncoder,
    cases: list[dict[str, str]],
    repeats: int,
) -> dict[str, Any]:
    if repeats <= 0:
        return {}
    probe_cases = cases[:3]
    pairs = [(case["query"], case["memory"]) for case in probe_cases]

    for prompt in PROMPTS.values():
        model.predict(pairs, prompt=prompt, show_progress_bar=False)

    prompt_samples: dict[str, list[float]] = {name: [] for name in PROMPTS}
    combined_samples: list[float] = []
    for _ in range(repeats):
        combined_started = time.perf_counter_ns()
        for name, prompt in PROMPTS.items():
            started = time.perf_counter_ns()
            model.predict(pairs, prompt=prompt, show_progress_bar=False)
            prompt_samples[name].append((time.perf_counter_ns() - started) / 1_000_000)
        combined_samples.append((time.perf_counter_ns() - combined_started) / 1_000_000)

    def summarize(samples: list[float]) -> dict[str, float]:
        ordered = sorted(samples)
        p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "p50_ms": round(statistics.median(samples), 3),
            "p95_ms": round(ordered[p95_index], 3),
        }

    return {
        "probe_candidate_count": len(pairs),
        "repeats": repeats,
        "per_prompt": {
            name: summarize(samples) for name, samples in prompt_samples.items()
        },
        "three_prompt_combined": summarize(combined_samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).with_name("step4_phase45e2_utility_corpus.json"),
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--latency-repeats", type=int, default=20)
    args = parser.parse_args()

    cases = _load_corpus(args.corpus)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    load_started = time.perf_counter()
    model = CrossEncoder(
        MODEL_ID,
        revision=MODEL_REVISION,
        device=args.device,
        trust_remote_code=False,
    )
    load_seconds = time.perf_counter() - load_started

    scores = {
        name: _predict_scores(model, cases, prompt) for name, prompt in PROMPTS.items()
    }

    calibration_cases, calibration_scores = _slice_scores(cases, scores, "calibration")
    holdout_cases, holdout_scores = _slice_scores(cases, scores, "holdout")
    thresholds, calibration_eval = _calibrate(
        calibration_cases,
        calibration_scores,
    )
    holdout_eval = _confusion(holdout_cases, holdout_scores, thresholds)
    full_eval = _confusion(cases, scores, thresholds)

    case_results = []
    for index, case in enumerate(cases):
        case_results.append(
            {
                **case,
                "scores": {
                    name: round(float(values[index]), 6)
                    for name, values in scores.items()
                },
                "predicted": _predict_label(
                    essential=float(scores["essential"][index]),
                    helpful=float(scores["helpful"][index]),
                    steering=float(scores["steering"][index]),
                    thresholds=thresholds,
                ),
            }
        )

    result = {
        "status": "MEASURE_ONLY",
        "purpose": (
            "Phase 4.5E.2 research-only utility/steering bake-off; "
            "no production memory injection authority"
        ),
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "device": str(next(model.parameters()).device),
        "prompts": PROMPTS,
        "corpus": {
            "path": str(args.corpus),
            "case_count": len(cases),
            "label_counts": dict(Counter(case["label"] for case in cases)),
            "language_counts": dict(Counter(case["language"] for case in cases)),
            "split_counts": dict(Counter(case["split"] for case in cases)),
        },
        "load_seconds": round(load_seconds, 4),
        "peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None
        ),
        "calibration": {
            "thresholds": {
                "essential": thresholds[0],
                "helpful": thresholds[1],
                "steering": thresholds[2],
            },
            "selection_rule": (
                "lexicographically minimize unsafe false influence, then missed "
                "steering; maximize essential recall, helpful recall, then macro F1"
            ),
            "evaluation": calibration_eval,
        },
        "holdout": {
            "note": "Hinglish/Hindi holdout; thresholds are not retuned",
            "evaluation": holdout_eval,
        },
        "full_corpus": {
            "evaluation": full_eval,
            "score_summary": _score_summary(cases, scores),
        },
        "latency": _latency_probe(model, cases, args.latency_repeats),
        "cases": case_results,
        "decision_boundary": (
            "No threshold from this run is production-approved. A useful E.2 "
            "candidate must show low false influence and strong steering rejection "
            "on holdout evidence before any later E.3 proposal."
        ),
    }

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
