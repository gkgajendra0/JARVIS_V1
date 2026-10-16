"""Local-only locked-label scorer for independent memory-quality evaluation.

No data is uploaded and no models run. Labels must have been independently
collected and kept separate from model development. A matching SHA-256 for the
complete frozen predictions file is required. This cannot prove independent
label creation or production-safe answer effects; use external governance.

Example:
  python tools/research/step4_memory_blind_scorer.py \\
      --predictions model_outputs.json \\
      --predictions-sha256 <prior_recorded_digest> \\
      --labels sealed_holdout_labels.json

Never commit private labels or user-memory values to Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

LANGS = frozenset({"en", "hi", "hinglish"})
UTILITY = frozenset(
    {"essential", "helpful", "unnecessary", "steering_risk", "unknown"}
)
CANDIDATE = frozenset({"skip", "review", "conflict_review", "duplicate"})
SELECTED = frozenset({"essential", "helpful"})
POSITIVE = frozenset({"essential", "helpful"})
NEGATIVE = frozenset({"unnecessary", "steering_risk"})


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("expected schema_version=1 object")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_labels(labels: dict[str, Any]) -> list[dict[str, Any]]:
    if labels.get("purpose") != "independent_holdout":
        raise ValueError("labels must have independent_holdout purpose")
    cases = labels.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("labels must contain cases")
    seen: set[str] = set()
    for c in cases:
        if not isinstance(c, dict):
            raise TypeError("holdout case must be an object")
        ident = c.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("invalid or duplicate case ID")
        seen.add(ident)
        if c.get("language") not in LANGS:
            raise ValueError("invalid holdout language")
        kind = c.get("kind")
        expected = c.get("expected")
        if kind == "context" and expected in UTILITY - {"unknown"}:
            continue
        if kind == "candidate" and expected in CANDIDATE:
            continue
        raise ValueError("unsupported case kind or expected label")
    return cases


def _validate_predictions(
    cases: list[dict[str, Any]], predictions: dict[str, Any]
) -> None:
    if not isinstance(predictions.get("name"), str) or not (
        predictions["name"].strip()
    ):
        raise ValueError("predictions require named challenger")
    expected_candidate = {c["id"] for c in cases if c["kind"] == "candidate"}
    expected_context = {c["id"] for c in cases if c["kind"] == "context"}
    pred_candidate = predictions.get("candidate_predictions", {})
    pred_context = predictions.get("context_signals", {})
    if not isinstance(pred_candidate, dict) or not isinstance(pred_context, dict):
        raise TypeError("predictions must be keyed dictionaries")
    if set(pred_candidate) != expected_candidate or set(pred_context) != (
        expected_context
    ):
        raise ValueError("full case-ID coverage is required before opening labels")
    if any(label not in CANDIDATE for label in pred_candidate.values()):
        raise ValueError("invalid candidate prediction")
    if any(label not in UTILITY for label in pred_context.values()):
        raise ValueError("invalid context prediction")


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def score_locked(
    *,
    predictions: dict[str, Any],
    labels: dict[str, Any],
    frozen_predictions_sha256: str,
) -> dict[str, Any]:
    """Score label decisions only; never claim downstream answer acceptance."""

    cases = _validate_labels(labels)
    _validate_predictions(cases, predictions)
    by_lang = {language: Counter() for language in sorted(LANGS)}
    counts: Counter[str] = Counter()
    for case in cases:
        lang = case["language"]
        expected = case["expected"]
        kind = case["kind"]
        ident = case["id"]
        row = by_lang[lang]
        row["cases"] += 1
        if kind == "candidate":
            result = predictions["candidate_predictions"][ident]
            row["candidate_total"] += 1
            row["candidate_correct"] += int(result == expected)
            row["false_candidate_review"] += int(
                expected == "skip" and result != "skip"
            )
        else:
            result = predictions["context_signals"][ident]
            selected = result in SELECTED
            row["context_total"] += 1
            row["negative_context_total"] += int(expected in NEGATIVE)
            row["useful_total"] += int(expected in POSITIVE)
            row["useful_captured"] += int(expected in POSITIVE and selected)
            row["unsafe_steering_selections"] += int(
                expected == "steering_risk" and selected
            )
            row["unnecessary_selections"] += int(
                expected == "unnecessary" and selected
            )
        counts[kind] += 1

    sum_counts = Counter()
    for row in by_lang.values():
        sum_counts.update(row)
    negative_total = sum_counts["negative_context_total"]
    useful_total = sum_counts["useful_total"]
    unsafe = sum_counts["unsafe_steering_selections"]
    # The exact one-sided 95% binomial upper confidence bound only when
    # zero bad selections were observed; nonzero counts are a blocked gate.
    zero_fail_upper_bound = (
        round(1 - math.pow(0.05, 1 / negative_total), 6)
        if negative_total and unsafe == 0
        else None
    )
    preregistered_coverage = all(
        by_lang[lang]["negative_context_total"] >= 100
        and by_lang[lang]["useful_total"] >= 30
        for lang in LANGS
    )
    recall_ok = (
        useful_total > 0
        and sum_counts["useful_captured"] / useful_total >= 0.8
        and all(
            by_lang[lang]["useful_total"] > 0
            and by_lang[lang]["useful_captured"] / by_lang[lang]["useful_total"]
            >= 0.7
            for lang in LANGS
        )
    )
    per_language = {
        lang: {
            **dict(row),
            "useful_recall": _rate(row["useful_captured"], row["useful_total"]),
            "candidate_accuracy": _rate(
                row["candidate_correct"], row["candidate_total"]
            ),
        }
        for lang, row in by_lang.items()
    }
    return {
        "mode": "LOCAL_ONLY_LOCKED_LABEL_SCORING",
        "frozen_predictions_sha256": frozen_predictions_sha256,
        "production_acceptance": False,
        "answer_quality_verified": False,
        "owner_machine_accepted": False,
        "counts": dict(counts),
        "per_language": per_language,
        "overall": {
            **dict(sum_counts),
            "useful_recall": _rate(
                sum_counts["useful_captured"], useful_total
            ),
            "unsafe_zero_observed_upper_95": zero_fail_upper_bound,
        },
        "preliminary_label_gate": bool(
            preregistered_coverage
            and recall_ok
            and unsafe == 0
            and sum_counts["unnecessary_selections"] == 0
        ),
        "limitations": (
            "Only offline classification is scored. Source authority, sensitive "
            "data exclusion, actual downstream answer change, model latency and "
            "owner-machine acceptance require independent tests."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--predictions-sha256", required=True)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    predictions, actual_digest = _load_json(args.predictions)
    if actual_digest != args.predictions_sha256:
        parser.error("predictions changed after the recorded frozen digest")
    labels, _ = _load_json(args.labels)
    report = score_locked(
        predictions=predictions,
        labels=labels,
        frozen_predictions_sha256=actual_digest,
    )
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
