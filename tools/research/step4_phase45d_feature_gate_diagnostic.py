"""Development-only selective-gate diagnostic for Phase 4.5D.

This script reads the already-exposed 320-case final-acceptance artifact and asks a
narrow question: can a mature low-capacity classifier combine evidence JARVIS already
computes into a better release-confidence signal than reranker score + margin alone?

All outputs are development evidence only. The source corpus is retired and must never
be reused as final acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

RANDOM_STATE = 45
N_SPLITS = 5
TARGET_EMPIRICAL_PRECISION = 0.95


@dataclass(frozen=True, slots=True)
class FeatureSet:
    name: str
    feature_names: tuple[str, ...]


SCORE_MARGIN = FeatureSet(
    name="score_margin",
    feature_names=("rerank_score", "rerank_margin"),
)
FULL_EVIDENCE = FeatureSet(
    name="full_retrieval_evidence",
    feature_names=(
        "rerank_score",
        "rerank_margin",
        "dense_score",
        "fused_score",
        "lexical_hit",
        "reciprocal_lexical_rank",
        "reciprocal_dense_rank",
    ),
)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("final_acceptance_eligible") is not True:
        raise RuntimeError("input is not the Phase 4.5D final-acceptance artifact")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 320:
        raise RuntimeError("expected the frozen 320-case Phase 4.5D artifact")
    return list(cases)


def _feature_row(case: dict[str, Any], feature_set: FeatureSet) -> list[float]:
    lexical_rank = case.get("lexical_rank")
    dense_rank = case.get("dense_rank")
    values = {
        "rerank_score": float(case["rerank_score"]),
        "rerank_margin": float(case["rerank_margin"]),
        "dense_score": float(case["dense_score"]),
        "fused_score": float(case["fused_score"]),
        "lexical_hit": 0.0 if lexical_rank is None else 1.0,
        "reciprocal_lexical_rank": 0.0
        if lexical_rank is None
        else 1.0 / float(lexical_rank),
        "reciprocal_dense_rank": 0.0 if dense_rank is None else 1.0 / float(dense_rank),
    }
    return [values[name] for name in feature_set.feature_names]


def _features(cases: list[dict[str, Any]], feature_set: FeatureSet) -> np.ndarray:
    return np.asarray(
        [_feature_row(case, feature_set) for case in cases], dtype=np.float64
    )


def _labels(cases: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([bool(case["safe_to_release"]) for case in cases], dtype=np.int64)


def _pipeline() -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    solver="lbfgs",
                    max_iter=2000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def _best_empirical_operating_point(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for threshold in sorted({float(value) for value in probabilities}, reverse=True):
        released = probabilities >= threshold
        tp = int(np.sum(released & (labels == 1)))
        fp = int(np.sum(released & (labels == 0)))
        if tp + fp == 0:
            continue
        precision = tp / (tp + fp)
        recall = tp / int(np.sum(labels == 1))
        candidates.append(
            {
                "threshold": threshold,
                "released_cases": int(np.sum(released)),
                "tp": tp,
                "fp": fp,
                "precision": precision,
                "recall": recall,
            }
        )
    valid = [
        item for item in candidates if item["precision"] >= TARGET_EMPIRICAL_PRECISION
    ]
    if not valid:
        return {
            "found": False,
            "target_empirical_precision": TARGET_EMPIRICAL_PRECISION,
            "best": None,
        }
    best = max(
        valid, key=lambda item: (item["recall"], item["precision"], item["threshold"])
    )
    return {
        "found": True,
        "target_empirical_precision": TARGET_EMPIRICAL_PRECISION,
        "best": {
            key: round(value, 6) if isinstance(value, float) else value
            for key, value in best.items()
        },
    }


def _evaluate(cases: list[dict[str, Any]], feature_set: FeatureSet) -> dict[str, Any]:
    X = _features(cases, feature_set)
    y = _labels(cases)
    cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    probabilities = cross_val_predict(
        _pipeline(),
        X,
        y,
        cv=cv,
        method="predict_proba",
        n_jobs=None,
    )[:, 1]
    result = {
        "feature_names": list(feature_set.feature_names),
        "oof_protocol": {
            "folds": N_SPLITS,
            "shuffle": True,
            "random_state": RANDOM_STATE,
            "training_row_scores_used": False,
        },
        "roc_auc": round(float(roc_auc_score(y, probabilities)), 6),
        "average_precision": round(float(average_precision_score(y, probabilities)), 6),
        "empirical_operating_point": _best_empirical_operating_point(probabilities, y),
    }
    return result


def _run(path: Path) -> dict[str, Any]:
    cases = _load_cases(path)
    by_split = {
        split: [case for case in cases if case["split"] == split]
        for split in ("calibration", "validation")
    }
    if len(by_split["calibration"]) != 192 or len(by_split["validation"]) != 128:
        raise RuntimeError("unexpected retired corpus split sizes")

    evaluations = {
        feature_set.name: _evaluate(cases, feature_set)
        for feature_set in (SCORE_MARGIN, FULL_EVIDENCE)
    }
    baseline = evaluations[SCORE_MARGIN.name]
    challenger = evaluations[FULL_EVIDENCE.name]
    recommendation = (
        "full_retrieval_evidence"
        if (
            challenger["roc_auc"] > baseline["roc_auc"]
            and challenger["average_precision"] > baseline["average_precision"]
            and challenger["empirical_operating_point"]["found"]
        )
        else "no_learned_feature_gate_selection"
    )
    return {
        "status": "PASS_DEVELOPMENT_DIAGNOSTIC",
        "final_acceptance_eligible": False,
        "source": {
            "path": str(path),
            "cases": len(cases),
            "note": "All 320 source cases are exposed/retired development evidence.",
        },
        "target": "safe_to_release",
        "excluded_inputs": ["language", "category", "case_id", "expected_memory_id"],
        "evaluations": evaluations,
        "development_recommendation": recommendation,
        "next_step_if_selected": (
            "Freeze the low-capacity feature model on retired development data, then use a new "
            "untouched corpus for independent MAPIE threshold calibration and held-out validation."
        ),
        "next_step_if_not_selected": (
            "Benchmark an independent multilingual entailment/answerability verifier before "
            "changing the production release architecture."
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
        "--output",
        default=".step4-phase45d-feature-gate-diagnostic.json",
        help="Development-only result JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = _run(Path(args.input))
    path = Path(args.output)
    path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {path}")
    print("STATUS:", output["status"])
    for name, metrics in output["evaluations"].items():
        print(name, json.dumps(metrics))
    print("RECOMMENDATION:", output["development_recommendation"])


if __name__ == "__main__":
    main()
