"""Development-only task-specific local memory-guard model bake-off."""

from __future__ import annotations

import argparse
import gc
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import step4_phase45d_task_specific_guard_cases as cases

OUTPUT_DEFAULT = Path(".step4-phase45d-task-specific-guard-bakeoff-v1.json")
FROZEN_CORPUS_SHA256: Final = (
    "ae854ed664ef6ee0214f65f5fe4b252099fd1dcaea00c13aaf7789cd84afd3ab"
)
RANDOM_STATE: Final = 45
LOGISTIC_C: Final = 1.0
MAX_ITER: Final = 2000
SOLVER: Final = "lbfgs"

CANDIDATES: Final = (
    {
        "key": "multilingual_minilm_l12",
        "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
        "dimension": 384,
        "input_prefix": "",
        "truncate_dim": None,
    },
    {
        "key": "multilingual_e5_small",
        "model_id": "intfloat/multilingual-e5-small",
        "revision": "fd1525a9fd15316a2d503bf26ab031a61d056e98",
        "dimension": 384,
        "input_prefix": "query: ",
        "truncate_dim": None,
    },
    {
        "key": "multilingual_mpnet_base_v2",
        "model_id": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "revision": "4328cf26390c98c5e3c738b4460a05b95f4911f5",
        "dimension": 768,
        "input_prefix": "",
        "truncate_dim": None,
    },
    {
        "key": "qwen3_embedding_0_6b_256d",
        "model_id": "Qwen/Qwen3-Embedding-0.6B",
        "revision": "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        "dimension": 256,
        "input_prefix": "",
        "truncate_dim": 256,
    },
)

OVERALL_ALLOW_RECALL_FLOOR: Final = 0.90
DIRECT_ALLOW_RECALL_FLOOR: Final = 0.90
COMPARISON_ALLOW_RECALL_FLOOR: Final = 0.85
LANGUAGE_ALLOW_RECALL_FLOOR: Final = 0.85
MACRO_F1_FLOOR: Final = 0.85


@dataclass(frozen=True, slots=True)
class CandidatePrediction:
    case_id: str
    language: str
    expected_label: str
    predicted_label: str
    expected_allow: bool
    predicted_allow: bool


def _assert_frozen_corpus() -> dict[str, object]:
    payload = cases.build_payload()
    digest = cases.payload_sha256(payload)
    if digest != FROZEN_CORPUS_SHA256:
        raise RuntimeError(
            "task-specific guard corpus hash mismatch: "
            f"{digest} != {FROZEN_CORPUS_SHA256}"
        )
    return payload


def _assert_no_v4_exact_query_overlap(payload: dict[str, object]) -> None:
    """Use retired V4 only as a deny-list; never as train/eval evidence."""

    import step4_phase45d_final_composite_cases as v4

    v4_payload = v4.build_payload()
    v4_queries = {
        cases.normalized_query(str(row["query"])) for row in v4_payload["queries"]
    }
    new_rows = list(payload["train"]) + list(payload["holdout"])
    new_queries = {cases.normalized_query(str(row["query"])) for row in new_rows}
    overlap = sorted(v4_queries.intersection(new_queries))
    if overlap:
        raise RuntimeError(
            f"task-specific guard corpus overlaps retired V4 queries: {overlap[:3]}"
        )


def _rows(payload: dict[str, object], split: str) -> list[dict[str, object]]:
    raw = payload[split]
    if not isinstance(raw, list):
        raise TypeError(f"{split} corpus must be a list")
    return raw


def _labels(rows: list[dict[str, object]]) -> list[str]:
    return [str(row["label"]) for row in rows]


def _texts(
    rows: list[dict[str, object]],
    *,
    prefix: str = "",
) -> list[str]:
    if not isinstance(prefix, str):
        raise TypeError("prefix must be a string")
    return [f"{prefix}{row['query']}" for row in rows]


def _encode(
    model: Any,
    texts: list[str],
    *,
    batch_size: int,
    truncate_dim: int | None,
) -> tuple[np.ndarray, float]:
    kwargs: dict[str, Any] = {
        "batch_size": batch_size,
        "convert_to_numpy": True,
        "normalize_embeddings": True,
        "show_progress_bar": False,
    }
    if truncate_dim is not None:
        kwargs["truncate_dim"] = truncate_dim
    started = time.perf_counter()
    vectors = model.encode(texts, **kwargs)
    elapsed = time.perf_counter() - started
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] != len(texts):
        raise RuntimeError("sentence-transformer returned unexpected embedding shape")
    if not np.all(np.isfinite(array)):
        raise RuntimeError("sentence-transformer returned non-finite embeddings")
    return array, elapsed


def _rss_bytes() -> int:
    import psutil

    return int(psutil.Process().memory_info().rss)


def _prediction_rows(
    holdout: list[dict[str, object]],
    predicted_labels: list[str],
) -> list[CandidatePrediction]:
    if len(holdout) != len(predicted_labels):
        raise RuntimeError("prediction count does not match holdout count")
    output: list[CandidatePrediction] = []
    for row, predicted in zip(holdout, predicted_labels, strict=True):
        expected = str(row["label"])
        output.append(
            CandidatePrediction(
                case_id=str(row["case_id"]),
                language=str(row["language"]),
                expected_label=expected,
                predicted_label=predicted,
                expected_allow=expected in cases.ALLOW_LABELS,
                predicted_allow=predicted in cases.ALLOW_LABELS,
            )
        )
    return output


def summarize_predictions(
    predictions: list[CandidatePrediction],
    *,
    macro_f1: float,
    accuracy: float,
    train_seconds: float,
    holdout_encode_seconds: float,
    embedding_dimension: int,
) -> dict[str, Any]:
    allow_targets = [row for row in predictions if row.expected_allow]
    veto_targets = [row for row in predictions if not row.expected_allow]
    allowed_targets = [row for row in allow_targets if row.predicted_allow]
    false_allows = [row for row in veto_targets if row.predicted_allow]
    false_vetoes = [row for row in allow_targets if not row.predicted_allow]
    direct_targets = [
        row for row in allow_targets if row.expected_label == "current_value"
    ]
    comparison_targets = [
        row for row in allow_targets if row.expected_label == "current_value_comparison"
    ]
    direct_allowed = [row for row in direct_targets if row.predicted_allow]
    comparison_allowed = [row for row in comparison_targets if row.predicted_allow]
    negation_false_allows = [
        row for row in false_allows if row.expected_label == "negated_or_contradicted"
    ]

    by_language: dict[str, dict[str, int | float]] = {}
    for language in cases.LANGUAGES:
        language_targets = [row for row in allow_targets if row.language == language]
        language_allowed = [row for row in language_targets if row.predicted_allow]
        by_language[language] = {
            "allow_targets": len(language_targets),
            "allowed": len(language_allowed),
            "allow_recall": round(
                len(language_allowed) / len(language_targets),
                6,
            ),
        }

    by_label: dict[str, dict[str, int | float]] = {}
    for label in cases.LABELS:
        label_rows = [row for row in predictions if row.expected_label == label]
        exact = [row for row in label_rows if row.predicted_label == label]
        by_label[label] = {
            "cases": len(label_rows),
            "exact": len(exact),
            "exact_recall": round(len(exact) / len(label_rows), 6),
        }

    overall_allow_recall = len(allowed_targets) / len(allow_targets)
    direct_allow_recall = len(direct_allowed) / len(direct_targets)
    comparison_allow_recall = len(comparison_allowed) / len(comparison_targets)
    checks = {
        "zero_false_allows": not false_allows,
        "zero_negation_false_allows": not negation_false_allows,
        "overall_allow_recall_at_least_0_90": (
            overall_allow_recall >= OVERALL_ALLOW_RECALL_FLOOR
        ),
        "direct_allow_recall_at_least_0_90": (
            direct_allow_recall >= DIRECT_ALLOW_RECALL_FLOOR
        ),
        "comparison_allow_recall_at_least_0_85": (
            comparison_allow_recall >= COMPARISON_ALLOW_RECALL_FLOOR
        ),
        "each_language_allow_recall_at_least_0_85": all(
            float(metrics["allow_recall"]) >= LANGUAGE_ALLOW_RECALL_FLOOR
            for metrics in by_language.values()
        ),
        "macro_f1_at_least_0_85": macro_f1 >= MACRO_F1_FLOOR,
        "argmax_only_no_probability_threshold": True,
        "cloud_provider_calls_zero": True,
        "v4_not_used_for_training_or_scoring": True,
    }
    return {
        "holdout_cases": len(predictions),
        "allow_targets": len(allow_targets),
        "veto_targets": len(veto_targets),
        "allowed_target_cases": len(allowed_targets),
        "false_allow_cases": len(false_allows),
        "false_veto_cases": len(false_vetoes),
        "overall_allow_recall": round(overall_allow_recall, 6),
        "direct_allow_recall": round(direct_allow_recall, 6),
        "comparison_allow_recall": round(comparison_allow_recall, 6),
        "accuracy": round(float(accuracy), 6),
        "macro_f1": round(float(macro_f1), 6),
        "by_language": by_language,
        "by_label": by_label,
        "false_allow_case_ids": [row.case_id for row in false_allows],
        "false_veto_case_ids": [row.case_id for row in false_vetoes],
        "negation_false_allow_case_ids": [row.case_id for row in negation_false_allows],
        "false_allows_by_expected_label": dict(
            sorted(Counter(row.expected_label for row in false_allows).items())
        ),
        "embedding_dimension": embedding_dimension,
        "train_seconds": round(train_seconds, 4),
        "holdout_encode_seconds": round(holdout_encode_seconds, 4),
        "holdout_encode_ms_per_query": round(
            (holdout_encode_seconds * 1000.0) / len(predictions),
            4,
        ),
        "continuation_checks": checks,
        "passes_development_gate": all(checks.values()),
    }


def select_candidate(candidate_results: list[dict[str, Any]]) -> str | None:
    passing = [
        row
        for row in candidate_results
        if bool(row["summary"]["passes_development_gate"])
    ]
    if not passing:
        return None

    def key(row: dict[str, Any]) -> tuple[float, ...]:
        summary = row["summary"]
        return (
            float(summary["false_allow_cases"]),
            float(len(summary["negation_false_allow_case_ids"])),
            -float(summary["comparison_allow_recall"]),
            -float(summary["overall_allow_recall"]),
            -float(summary["macro_f1"]),
            float(summary["holdout_encode_ms_per_query"]),
        )

    return str(min(passing, key=key)["key"])


def _run_candidate(
    candidate: dict[str, object],
    *,
    train_rows: list[dict[str, object]],
    holdout_rows: list[dict[str, object]],
    device: str,
    batch_size: int,
) -> dict[str, Any]:
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score

    print(
        f"Loading {candidate['key']}: {candidate['model_id']}@{candidate['revision']}"
    )
    rss_baseline = _rss_bytes()
    rss_samples = [rss_baseline]

    torch_module: Any | None = None
    cuda_baseline = 0
    if device == "cuda":
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA bake-off requested but torch.cuda.is_available() is false"
            )
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        cuda_baseline = int(torch.cuda.memory_allocated())
        torch_module = torch

    load_started = time.perf_counter()
    model = SentenceTransformer(
        str(candidate["model_id"]),
        revision=str(candidate["revision"]),
        device=device,
        trust_remote_code=False,
    )
    model_load_seconds = time.perf_counter() - load_started
    rss_samples.append(_rss_bytes())

    parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
    parameter_bytes = sum(
        int(parameter.numel() * parameter.element_size())
        for parameter in model.parameters()
    )

    input_prefix = str(candidate["input_prefix"])
    raw_truncate_dim = candidate["truncate_dim"]
    if raw_truncate_dim is not None and (
        isinstance(raw_truncate_dim, bool)
        or not isinstance(raw_truncate_dim, int)
        or raw_truncate_dim <= 0
    ):
        raise TypeError("truncate_dim must be a positive integer or None")
    truncate_dim = int(raw_truncate_dim) if raw_truncate_dim is not None else None

    train_vectors, train_encode_seconds = _encode(
        model,
        _texts(train_rows, prefix=input_prefix),
        batch_size=batch_size,
        truncate_dim=truncate_dim,
    )
    rss_samples.append(_rss_bytes())
    holdout_vectors, holdout_encode_seconds = _encode(
        model,
        _texts(holdout_rows, prefix=input_prefix),
        batch_size=batch_size,
        truncate_dim=truncate_dim,
    )
    rss_samples.append(_rss_bytes())
    expected_dimension = int(candidate["dimension"])
    if train_vectors.shape[1] != expected_dimension:
        raise RuntimeError(
            f"{candidate['key']} dimension changed: "
            f"{train_vectors.shape[1]} != {expected_dimension}"
        )

    classifier = LogisticRegression(
        C=LOGISTIC_C,
        max_iter=MAX_ITER,
        solver=SOLVER,
        random_state=RANDOM_STATE,
    )
    started = time.perf_counter()
    classifier.fit(train_vectors, _labels(train_rows))
    fit_seconds = time.perf_counter() - started
    rss_samples.append(_rss_bytes())
    predicted = [str(value) for value in classifier.predict(holdout_vectors)]
    expected = _labels(holdout_rows)
    macro_f1 = float(
        f1_score(
            expected,
            predicted,
            labels=list(cases.LABELS),
            average="macro",
            zero_division=0,
        )
    )
    accuracy = float(accuracy_score(expected, predicted))
    prediction_rows = _prediction_rows(holdout_rows, predicted)
    summary = summarize_predictions(
        prediction_rows,
        macro_f1=macro_f1,
        accuracy=accuracy,
        train_seconds=train_encode_seconds + fit_seconds,
        holdout_encode_seconds=holdout_encode_seconds,
        embedding_dimension=expected_dimension,
    )

    rss_peak_sampled = max(rss_samples)
    cuda_peak_allocated = (
        int(torch_module.cuda.max_memory_allocated()) if torch_module is not None else 0
    )
    result = {
        "key": candidate["key"],
        "model_id": candidate["model_id"],
        "revision": candidate["revision"],
        "input_prefix": input_prefix,
        "truncate_dim": truncate_dim,
        "classifier": {
            "type": "sklearn.linear_model.LogisticRegression",
            "solver": SOLVER,
            "C": LOGISTIC_C,
            "max_iter": MAX_ITER,
            "random_state": RANDOM_STATE,
            "probability_threshold": None,
        },
        "resources": {
            "model_load_seconds": round(model_load_seconds, 4),
            "parameter_count": parameter_count,
            "parameter_bytes": parameter_bytes,
            "rss_baseline_bytes": rss_baseline,
            "rss_peak_sampled_bytes": rss_peak_sampled,
            "rss_delta_peak_sampled_bytes": max(0, rss_peak_sampled - rss_baseline),
            "cuda_baseline_allocated_bytes": cuda_baseline,
            "cuda_peak_allocated_bytes": cuda_peak_allocated,
            "cuda_delta_peak_allocated_bytes": max(
                0, cuda_peak_allocated - cuda_baseline
            ),
            "rss_measurement": "sampled process RSS at model/train/holdout/fit boundaries",
            "cuda_measurement": "torch.cuda.max_memory_allocated for this candidate",
        },
        "summary": summary,
    }
    del classifier, train_vectors, holdout_vectors, model
    gc.collect()
    if torch_module is not None:
        torch_module.cuda.empty_cache()
    return result


def run(*, device: str, batch_size: int) -> dict[str, Any]:
    payload = _assert_frozen_corpus()
    _assert_no_v4_exact_query_overlap(payload)
    train_rows = _rows(payload, "train")
    holdout_rows = _rows(payload, "holdout")
    results = [
        _run_candidate(
            candidate,
            train_rows=train_rows,
            holdout_rows=holdout_rows,
            device=device,
            batch_size=batch_size,
        )
        for candidate in CANDIDATES
    ]
    selected = select_candidate(results)
    return {
        "status": "DEVELOPMENT_TASK_SPECIFIC_GUARD_BAKEOFF_COMPLETE",
        "phase45d": "ACTIVE",
        "phase45e_authorized": False,
        "cloud_provider_calls": 0,
        "corpus": {
            **cases.public_summary(),
            "v4_exact_query_overlap": 0,
            "v4_used_for_training": False,
            "v4_used_for_scoring": False,
        },
        "taxonomy": {
            "labels": list(cases.LABELS),
            "allow_labels": sorted(cases.ALLOW_LABELS),
            "negation_is_explicit_class": True,
        },
        "candidates": results,
        "decision": {
            "selected_candidate": selected,
            "candidate_selected": selected is not None,
            "production_guard_change_authorized": selected is not None,
            "fresh_v5_acceptance_authorized": False,
            "phase45e_authorized": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    output = Path(args.output)
    if output.exists():
        raise RuntimeError(f"refusing to overwrite bake-off evidence: {output}")
    result = run(device=str(args.device), batch_size=int(args.batch_size))
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output}")
    print("STATUS:", result["status"])
    print(
        "SUMMARY:",
        json.dumps(
            {
                row["key"]: {
                    "false_allow_cases": row["summary"]["false_allow_cases"],
                    "overall_allow_recall": row["summary"]["overall_allow_recall"],
                    "direct_allow_recall": row["summary"]["direct_allow_recall"],
                    "comparison_allow_recall": row["summary"][
                        "comparison_allow_recall"
                    ],
                    "macro_f1": row["summary"]["macro_f1"],
                    "passes_development_gate": row["summary"][
                        "passes_development_gate"
                    ],
                    "holdout_encode_ms_per_query": row["summary"][
                        "holdout_encode_ms_per_query"
                    ],
                    "rss_delta_peak_sampled_bytes": row["resources"][
                        "rss_delta_peak_sampled_bytes"
                    ],
                    "cuda_delta_peak_allocated_bytes": row["resources"][
                        "cuda_delta_peak_allocated_bytes"
                    ],
                }
                for row in result["candidates"]
            },
            ensure_ascii=False,
        ),
    )
    print("DECISION:", json.dumps(result["decision"], ensure_ascii=False))


if __name__ == "__main__":
    main()
