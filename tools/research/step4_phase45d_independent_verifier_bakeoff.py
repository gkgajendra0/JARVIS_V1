"""Development-only independent verifier bake-off for Phase 4.5D.

This script never reruns JARVIS retrieval. It consumes the already-exposed 320-case
Phase-4.5D artifact, reconstructs each original synthetic query and returned top memory
passage, scores those pairs with one independent multilingual cross-encoder, then asks
whether that new score adds useful out-of-fold release-confidence information.

The source corpus is retired. Every output from this script is development evidence and
must never be treated as final acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

import step4_phase45d_feature_gate_diagnostic as feature_gate
import step4_phase45d_final_cases as final_cases

MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODEL_REVISION_HINT = "1427fd6"
BATCH_SIZE = 32
MAX_LENGTH = 512
MIN_DEVELOPMENT_RECALL = 0.40
MIN_LANGUAGE_RECALL = 0.25


def _load_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("final_acceptance_eligible") is not True:
        raise RuntimeError(
            "input is not the retired Phase 4.5D final-acceptance artifact"
        )
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 320:
        raise RuntimeError("expected exactly 320 retired Phase 4.5D cases")
    return payload


def _memory_text_index(corpus: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for document in corpus["documents"]:
        memory_id = str(document["memory_id"])
        text = str(document["text"])
        index[memory_id] = text

    # Historical-transition replacement memories are created by the lifecycle harness.
    # Include them explicitly so the returned current assertion can always be resolved.
    for item in final_cases.BOUNDARY_DOCUMENTS:
        replacement_memory_id = item.get("replacement_memory_id")
        replacement_text = item.get("replacement_text")
        if replacement_memory_id and replacement_text:
            index[str(replacement_memory_id)] = str(replacement_text)
    return index


def _pair_records(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    corpus = final_cases.build_payload()
    queries = {str(item["case_id"]): item for item in corpus["queries"]}
    documents = _memory_text_index(corpus)

    records: list[dict[str, Any]] = []
    for case in artifact["cases"]:
        case_id = str(case["case_id"])
        query_item = queries.get(case_id)
        if query_item is None:
            raise RuntimeError(
                f"case id missing from frozen corpus generator: {case_id}"
            )
        if str(query_item["label"]) != str(case["label"]):
            raise RuntimeError(f"label drift for {case_id}")
        if str(query_item["language"]) != str(case["language"]):
            raise RuntimeError(f"language drift for {case_id}")

        top_memory_id = str(case["top_memory_id"])
        document_text = documents.get(top_memory_id)
        if document_text is None:
            raise RuntimeError(
                f"returned top memory cannot be reconstructed for {case_id}: "
                f"{top_memory_id}"
            )
        records.append(
            {
                "case": case,
                "query": str(query_item["query"]),
                "document": document_text,
            }
        )
    return records


def _resolve_model_revision() -> str:
    try:
        from huggingface_hub import model_info
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            "huggingface_hub is required for verifier revision pinning"
        ) from exc
    info = model_info(MODEL_ID, revision=MODEL_REVISION_HINT)
    revision = getattr(info, "sha", None)
    if not isinstance(revision, str) or len(revision) != 40:
        raise RuntimeError(
            "could not resolve verifier model to a full immutable commit SHA"
        )
    return revision


def _score_pairs(
    records: list[dict[str, Any]],
    *,
    device: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        import torch
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            "Sentence Transformers retrieval dependencies are required for this bake-off"
        ) from exc

    revision = _resolve_model_revision()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    load_started = time.perf_counter()
    model = CrossEncoder(
        MODEL_ID,
        revision=revision,
        device=device,
        trust_remote_code=False,
        max_length=MAX_LENGTH,
    )
    load_seconds = time.perf_counter() - load_started

    pairs = [(record["query"], record["document"]) for record in records]
    score_started = time.perf_counter()
    scores = model.predict(
        pairs,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        activation_fn=torch.nn.Identity(),
    )
    score_seconds = time.perf_counter() - score_started
    array = np.asarray(scores, dtype=np.float64).reshape(-1)
    if array.shape != (len(records),):
        raise RuntimeError("independent verifier score count does not match case count")
    if not np.all(np.isfinite(array)):
        raise RuntimeError("independent verifier emitted non-finite scores")

    environment = {
        "model_id": MODEL_ID,
        "model_revision": revision,
        "batch_size": BATCH_SIZE,
        "max_length": MAX_LENGTH,
        "device_requested": device,
        "torch_version": str(torch.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_runtime": str(torch.version.cuda),
        "device_name": (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        ),
        "peak_cuda_bytes": (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None
        ),
        "model_load_seconds": round(load_seconds, 4),
        "score_seconds": round(score_seconds, 4),
        "per_pair_ms": round((score_seconds * 1000.0) / len(records), 4),
    }
    return array, environment


def _labels(cases: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([bool(case["safe_to_release"]) for case in cases], dtype=np.int64)


def _base_matrix(cases: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray(
        [feature_gate._feature_row(case, feature_gate.FULL_EVIDENCE) for case in cases],
        dtype=np.float64,
    )


def _oof_evaluate(
    X: np.ndarray,
    y: np.ndarray,
    *,
    feature_names: list[str],
) -> tuple[dict[str, Any], np.ndarray]:
    try:
        from sklearn.metrics import average_precision_score, roc_auc_score
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            "scikit-learn is required for verifier confidence analysis"
        ) from exc

    cv = StratifiedKFold(
        n_splits=feature_gate.N_SPLITS,
        shuffle=True,
        random_state=feature_gate.RANDOM_STATE,
    )
    probabilities = cross_val_predict(
        feature_gate._pipeline(),
        X,
        y,
        cv=cv,
        method="predict_proba",
        n_jobs=None,
    )[:, 1]
    metrics = {
        "feature_names": feature_names,
        "oof_protocol": {
            "folds": feature_gate.N_SPLITS,
            "shuffle": True,
            "random_state": feature_gate.RANDOM_STATE,
            "training_row_scores_used": False,
        },
        "roc_auc": round(float(roc_auc_score(y, probabilities)), 6),
        "average_precision": round(float(average_precision_score(y, probabilities)), 6),
        "empirical_operating_point": feature_gate._best_empirical_operating_point(
            probabilities, y
        ),
    }
    return metrics, probabilities


def _raw_score_metrics(scores: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    try:
        from sklearn.metrics import average_precision_score, roc_auc_score
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            "scikit-learn is required for verifier score analysis"
        ) from exc
    return {
        "roc_auc": round(float(roc_auc_score(y, scores)), 6),
        "average_precision": round(float(average_precision_score(y, scores)), 6),
        "safe_score": {
            "min": round(float(np.min(scores[y == 1])), 6),
            "median": round(float(np.median(scores[y == 1])), 6),
            "max": round(float(np.max(scores[y == 1])), 6),
        },
        "unsafe_score": {
            "min": round(float(np.min(scores[y == 0])), 6),
            "median": round(float(np.median(scores[y == 0])), 6),
            "max": round(float(np.max(scores[y == 0])), 6),
        },
    }


def _language_breakdown(
    cases: list[dict[str, Any]],
    probabilities: np.ndarray,
    operating_point: dict[str, Any],
) -> dict[str, Any]:
    best = operating_point.get("best") if operating_point.get("found") else None
    threshold = float(best["threshold"]) if best is not None else math.inf
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, case in enumerate(cases):
        grouped[str(case["language"])].append(index)

    result: dict[str, Any] = {}
    for language, indices in sorted(grouped.items()):
        positives = [
            index for index in indices if bool(cases[index]["safe_to_release"])
        ]
        released_positive = [
            index for index in positives if float(probabilities[index]) >= threshold
        ]
        released_all = [
            index for index in indices if float(probabilities[index]) >= threshold
        ]
        false_release_ids = [
            str(cases[index]["case_id"])
            for index in released_all
            if not bool(cases[index]["safe_to_release"])
        ]
        result[language] = {
            "cases": len(indices),
            "safe_cases": len(positives),
            "released_safe_cases": len(released_positive),
            "positive_release_recall": (
                round(len(released_positive) / len(positives), 6) if positives else 0.0
            ),
            "false_release_case_ids": false_release_ids,
        }
    return result


def _recommendation(
    baseline: dict[str, Any],
    augmented: dict[str, Any],
    languages: dict[str, Any],
) -> dict[str, Any]:
    best = augmented["empirical_operating_point"].get("best")
    improved = (
        augmented["roc_auc"] > baseline["roc_auc"]
        and augmented["average_precision"] > baseline["average_precision"]
    )
    if best is None:
        return {
            "decision": "independent_signal_insufficient",
            "reason": "no_empirical_95_precision_operating_point",
        }
    language_floor_met = all(
        float(details["positive_release_recall"]) >= MIN_LANGUAGE_RECALL
        for details in languages.values()
    )
    if (
        improved
        and float(best["recall"]) >= MIN_DEVELOPMENT_RECALL
        and language_floor_met
    ):
        return {
            "decision": "independent_signal_promising",
            "reason": "combined_oof_signal_clears_pre_registered_development_gates",
        }
    return {
        "decision": "independent_signal_insufficient",
        "reason": "combined_oof_signal_does_not_clear_recall_or_language_gates",
    }


def _run(path: Path, *, device: str) -> dict[str, Any]:
    artifact = _load_artifact(path)
    records = _pair_records(artifact)
    cases = [record["case"] for record in records]
    y = _labels(cases)
    verifier_scores, environment = _score_pairs(records, device=device)

    base_X = _base_matrix(cases)
    baseline, _ = _oof_evaluate(
        base_X,
        y,
        feature_names=list(feature_gate.FULL_EVIDENCE.feature_names),
    )
    verifier_X = verifier_scores.reshape(-1, 1)
    verifier_only, _ = _oof_evaluate(
        verifier_X,
        y,
        feature_names=["independent_verifier_score"],
    )
    augmented_X = np.column_stack((base_X, verifier_scores))
    augmented, augmented_probabilities = _oof_evaluate(
        augmented_X,
        y,
        feature_names=[
            *feature_gate.FULL_EVIDENCE.feature_names,
            "independent_verifier_score",
        ],
    )
    languages = _language_breakdown(
        cases,
        augmented_probabilities,
        augmented["empirical_operating_point"],
    )
    recommendation = _recommendation(baseline, augmented, languages)

    return {
        "status": "PASS_DEVELOPMENT_BAKEOFF",
        "final_acceptance_eligible": False,
        "source": {
            "path": str(path),
            "cases": len(cases),
            "note": (
                "All source cases are the exposed/retired Phase 4.5D development corpus; "
                "Qwen retrieval was not rerun."
            ),
        },
        "model": environment,
        "raw_verifier_score": _raw_score_metrics(verifier_scores, y),
        "evaluations": {
            "existing_full_retrieval_evidence": baseline,
            "independent_verifier_only": verifier_only,
            "full_evidence_plus_independent_verifier": augmented,
        },
        "language_breakdown": languages,
        "development_gates": {
            "target_empirical_precision": feature_gate.TARGET_EMPIRICAL_PRECISION,
            "min_positive_release_recall": MIN_DEVELOPMENT_RECALL,
            "min_language_positive_release_recall": MIN_LANGUAGE_RECALL,
        },
        "development_recommendation": recommendation,
        "next_step_if_promising": (
            "Freeze the selected confidence architecture on retired development data, then "
            "build a new untouched Phase 4.5D calibration/validation corpus."
        ),
        "next_step_if_insufficient": (
            "Benchmark the deferred heavier independent verifier before changing any "
            "acceptance target or entering Phase 4.5E."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=".step4-phase45d-final-acceptance.json",
        help="Existing retired Phase 4.5D evidence JSON.",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="CrossEncoder device, normally cuda on the owner machine.",
    )
    parser.add_argument(
        "--output",
        default=".step4-phase45d-independent-verifier-bakeoff.json",
        help="Development-only UTF-8 result JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = _run(Path(args.input), device=args.device)
    path = Path(args.output)
    path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {path}")
    print("STATUS:", output["status"])
    print("MODEL:", json.dumps(output["model"]))
    for name, metrics in output["evaluations"].items():
        print(name, json.dumps(metrics))
    print("LANGUAGES:", json.dumps(output["language_breakdown"]))
    print("RECOMMENDATION:", json.dumps(output["development_recommendation"]))


if __name__ == "__main__":
    main()
