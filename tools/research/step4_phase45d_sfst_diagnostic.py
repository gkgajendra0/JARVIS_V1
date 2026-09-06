"""Development-only diagnostic after the first fresh Phase 4.5D acceptance failure.

This script never runs retrieval models and never changes the one-shot evidence artifact.
It reads the existing `.step4-phase45d-final-acceptance.json`, reproduces the
Bonferroni-Holm failure, then evaluates MAPIE Split Fixed Sequence Testing (SFST)
using the exposed validation split only to learn the hypothesis order and the
original calibration split only to test that order.

Because the one-shot held-out labels are now exposed, every result from this script
is development evidence only and is NOT final acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

TARGET_PRECISION = 0.95
CONFIDENCE_LEVEL = 0.95
SCORE_THRESHOLDS = (-2.0, 0.0, 2.0, 4.0, 6.0, 8.0)
MARGIN_THRESHOLDS = (0.0, 4.0, 8.0, 12.0, 16.0)
PREDICT_PARAMS = np.asarray(
    [(score, margin) for score in SCORE_THRESHOLDS for margin in MARGIN_THRESHOLDS],
    dtype=np.float64,
)


def _controller_cls() -> type[Any]:
    try:
        from mapie.risk_control import BinaryClassificationController
    except ImportError as exc:  # pragma: no cover - owner research environment only
        raise RuntimeError(
            "MAPIE is required for the Phase 4.5D SFST diagnostic"
        ) from exc
    return BinaryClassificationController


def _release_predict(
    values: Any,
    score_threshold: float,
    margin_threshold: float,
) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("release features must have shape (n_cases, 2)")
    return (
        (array[:, 0] >= float(score_threshold))
        & (array[:, 1] >= float(margin_threshold))
    ).astype(np.int64)


def _features(cases: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray(
        [(float(case["rerank_score"]), float(case["rerank_margin"])) for case in cases],
        dtype=np.float64,
    )


def _safe_labels(cases: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([bool(case["safe_to_release"]) for case in cases], dtype=np.int64)


def _param_tuple(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.shape != (2,) or not np.all(np.isfinite(array)):
        raise RuntimeError(f"invalid MAPIE prediction parameter: {value!r}")
    return float(array[0]), float(array[1])


def _valid_params(controller: Any) -> list[list[float]]:
    raw = np.asarray(controller.valid_predict_params, dtype=np.float64)
    if raw.size == 0:
        return []
    return raw.reshape(-1, 2).tolist()


def _metrics(
    cases: list[dict[str, Any]],
    params: tuple[float, float] | None,
) -> dict[str, Any]:
    if params is None:
        released = np.zeros(len(cases), dtype=bool)
    else:
        released = _release_predict(_features(cases), *params).astype(bool)
    safe = _safe_labels(cases).astype(bool)
    release_labels = np.asarray(
        [case["label"] == "release" for case in cases], dtype=bool
    )
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
            case["case_id"]
            for case, decision, is_safe in zip(cases, released, safe, strict=True)
            if decision and not is_safe
        ],
    }


def zero_error_power_summary(safe_calibration_cases: int) -> dict[str, Any]:
    """Explain the best-case multiple-testing power using a zero-error candidate."""
    if safe_calibration_cases <= 0:
        raise ValueError("safe_calibration_cases must be positive")
    delta = 1.0 - CONFIDENCE_LEVEL
    tested = len(PREDICT_PARAMS)
    best_case_p = TARGET_PRECISION**safe_calibration_cases
    single_required = math.ceil(math.log(delta) / math.log(TARGET_PRECISION))
    first_holm_required = math.ceil(
        math.log(delta / tested) / math.log(TARGET_PRECISION)
    )
    return {
        "safe_calibration_cases": safe_calibration_cases,
        "zero_error_best_case_p_value": round(best_case_p, 10),
        "single_hypothesis_alpha": round(delta, 10),
        "holm_first_step_alpha": round(delta / tested, 10),
        "zero_error_effective_n_needed_single_hypothesis": single_required,
        "zero_error_effective_n_needed_holm_first_step": first_holm_required,
        "holm_best_case_can_clear_first_step": best_case_p <= delta / tested,
    }


def _load_evidence(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("final_acceptance_eligible") is not True:
        raise RuntimeError(
            "input is not the Phase 4.5D final-acceptance evidence artifact"
        )
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 320:
        raise RuntimeError("expected the frozen 320-case Phase 4.5D evidence artifact")
    return payload


def _run(path: Path) -> dict[str, Any]:
    payload = _load_evidence(path)
    cases = list(payload["cases"])
    calibration = [case for case in cases if case["split"] == "calibration"]
    exposed_validation = [case for case in cases if case["split"] == "validation"]
    if len(calibration) != 192 or len(exposed_validation) != 128:
        raise RuntimeError("unexpected frozen corpus split sizes")

    controller_cls = _controller_cls()

    holm = controller_cls(
        predict_function=_release_predict,
        risk="precision",
        target_level=TARGET_PRECISION,
        confidence_level=CONFIDENCE_LEVEL,
        best_predict_param_choice="recall",
        list_predict_params=PREDICT_PARAMS,
        fwer_method="bonferroni_holm",
    )
    holm.calibrate(_features(calibration), _safe_labels(calibration))

    sfst = controller_cls(
        predict_function=_release_predict,
        risk="precision",
        target_level=TARGET_PRECISION,
        confidence_level=CONFIDENCE_LEVEL,
        best_predict_param_choice="recall",
        list_predict_params=PREDICT_PARAMS,
        fwer_method="split_fixed_sequence",
    )
    sfst.learn_fixed_sequence_order(
        X_learn=_features(exposed_validation),
        y_learn=_safe_labels(exposed_validation),
    )
    sfst.calibrate(_features(calibration), _safe_labels(calibration))

    holm_best = _param_tuple(holm.best_predict_param)
    sfst_best = _param_tuple(sfst.best_predict_param)
    safe_calibration_cases = int(np.sum(_safe_labels(calibration)))

    return {
        "status": "PASS_DEVELOPMENT_DIAGNOSTIC",
        "final_acceptance_eligible": False,
        "source_artifact": {
            "path": str(path),
            "status": payload.get("status"),
            "corpus_sha256": payload.get("corpus", {}).get("sha256"),
            "cases": len(cases),
            "note": (
                "The source corpus is fully exposed and retired. Validation cases are used "
                "only to learn an SFST order for development diagnosis."
            ),
        },
        "theoretical_power": zero_error_power_summary(safe_calibration_cases),
        "bonferroni_holm_reproduction": {
            "valid_predict_param_count": len(_valid_params(holm)),
            "best_predict_param": list(holm_best) if holm_best is not None else None,
            "calibration_metrics": _metrics(calibration, holm_best),
        },
        "split_fixed_sequence_development": {
            "ordering_cases": len(exposed_validation),
            "calibration_cases": len(calibration),
            "valid_predict_params": _valid_params(sfst),
            "valid_predict_param_count": len(_valid_params(sfst)),
            "best_predict_param": list(sfst_best) if sfst_best is not None else None,
            "calibration_metrics": _metrics(calibration, sfst_best),
            "exposed_validation_metrics": _metrics(exposed_validation, sfst_best),
            "all_retired_cases_metrics": _metrics(cases, sfst_best),
        },
        "decision_boundary": {
            "target_precision": TARGET_PRECISION,
            "confidence_level": CONFIDENCE_LEVEL,
            "tested_parameter_pairs": len(PREDICT_PARAMS),
            "next_final_method_if_sfst_is_viable": (
                "Use the retired 320-case artifact only as independent SFST ordering data; "
                "use a newly generated untouched corpus for calibration and held-out validation."
            ),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=".step4-phase45d-final-acceptance.json",
        help="Existing one-shot Phase 4.5D evidence JSON; never modified.",
    )
    parser.add_argument(
        "--output",
        default=".step4-phase45d-sfst-diagnostic.json",
        help="Development-only diagnostic JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = _run(Path(args.input))
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print("THEORETICAL POWER:", json.dumps(output["theoretical_power"]))
    print(
        "HOLM:",
        json.dumps(output["bonferroni_holm_reproduction"]),
    )
    print(
        "SFST:",
        json.dumps(output["split_fixed_sequence_development"]),
    )


if __name__ == "__main__":
    main()
