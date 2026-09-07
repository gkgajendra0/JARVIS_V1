"""Zero-training multilingual question-role bake-off for Phase 4.5D."""

from __future__ import annotations

import argparse
import gc
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import step4_phase45d_question_role_cases as cases

OUTPUT_DEFAULT = Path(".step4-phase45d-question-role-bakeoff-v1.json")
FROZEN_PAYLOAD_SHA256: Final = (
    "bb09a6a6b7c6f9248c48f35a39e5f4f8002f678a471d4752152c6a6b26cd4c21"
)
GLICLASS_PACKAGE_VERSION: Final = "0.1.20"
MAX_LENGTH: Final = 256
BATCH_SIZE: Final = 8

CANDIDATES: Final = (
    {
        "key": "gliclass_multilang_mini",
        "model_id": "knowledgator/gliclass-multilang-mini",
        "revision": "0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b",
    },
    {
        "key": "gliclass_multilang_ultra",
        "model_id": "knowledgator/gliclass-multilang-ultra",
        "revision": "9d6ca10258a3bddcf05b88c89cb8a8390e87e90c",
    },
)

ROLE_LABELS: Final = {
    "current_value": "current value lookup — asks for one present recorded value",
    "current_value_comparison": (
        "current value comparison — asks yes or no whether a present recorded value "
        "equals or does not equal a mentioned value"
    ),
    "reason_explanation": (
        "reason or explanation — asks why a value was chosen, set, or changed"
    ),
    "provenance_actor": (
        "person or provenance — asks who chose, recommended, approved, or supplied a value"
    ),
    "replacement_successor": (
        "replacement or successor — asks what replaced, succeeded, or came after another value"
    ),
    "related_record": (
        "related record or event — asks for a linked ticket, approval, event, document, "
        "or separate record"
    ),
    "historical_value": (
        "historical value — asks for an old, previous, former, past, or earlier value"
    ),
    "external_source": (
        "external source — asks what an email, web page, file, rumor, or other source says"
    ),
    "broad_recall": (
        "broad memory recall — asks for many memories, everything known, or a list of facts"
    ),
    "advice_or_other": (
        "advice or other — asks what should be done, what is better, or something not "
        "answered by one current fact"
    ),
}
LABEL_TO_ROLE: Final = {label: role for role, label in ROLE_LABELS.items()}
LABEL_TEXTS: Final = tuple(ROLE_LABELS[role] for role in cases.ROLES)
TASK_PROMPT: Final = (
    "Classify only the type of answer the user is requesting from personal memory. "
    "Choose exactly one answer role. Do not decide whether a mentioned value is true. "
    "A yes/no or negated question about whether the present value is X is a current "
    "value comparison. Questions asking why, who, what replaced it, a linked record, "
    "past state, an external source, broad recall, or advice are not current-value lookups."
)

ALLOW_RECALL_FLOOR: Final = 0.90
ALLOW_ROLE_RECALL_FLOOR: Final = 0.90
LANGUAGE_ALLOW_RECALL_FLOOR: Final = 0.85


@dataclass(frozen=True, slots=True)
class RolePrediction:
    case_id: str
    language: str
    expected_role: str
    predicted_role: str

    @property
    def expected_allow(self) -> bool:
        return self.expected_role in cases.ALLOW_ROLES

    @property
    def predicted_allow(self) -> bool:
        return self.predicted_role in cases.ALLOW_ROLES


def _assert_frozen_payload() -> dict[str, object]:
    payload = cases.build_payload()
    actual = cases.payload_sha256(payload)
    if actual != FROZEN_PAYLOAD_SHA256:
        raise RuntimeError(
            f"question-role corpus SHA mismatch: {actual} != {FROZEN_PAYLOAD_SHA256}"
        )
    return payload


def _assert_no_retired_query_overlap(payload: dict[str, object]) -> None:
    import step4_phase45d_answerability_cases as v1
    import step4_phase45d_final_composite_cases as v4
    import step4_phase45d_task_specific_guard_cases as v2

    retired: set[str] = set()

    v1_payload = v1.build_payload()
    for row in v1_payload["qa_cases"]:
        retired.add(cases.normalized_query(str(row["question"])))
    for row in v1_payload["nli_cases"]:
        retired.add(cases.normalized_query(str(row["question"])))

    v2_payload = v2.build_payload()
    for row in list(v2_payload["train"]) + list(v2_payload["holdout"]):
        retired.add(cases.normalized_query(str(row["query"])))

    v4_payload = v4.build_payload()
    for row in v4_payload["queries"]:
        retired.add(cases.normalized_query(str(row["query"])))

    rows = payload["cases"]
    if not isinstance(rows, list):
        raise TypeError("question-role cases must be a list")
    fresh = {cases.normalized_query(str(row["query"])) for row in rows}
    overlap = sorted(retired.intersection(fresh))
    if overlap:
        raise RuntimeError(f"question-role corpus overlaps retired queries: {overlap[:3]}")


def _macro_f1(predictions: list[RolePrediction]) -> float:
    scores: list[float] = []
    for role in cases.ROLES:
        tp = sum(
            row.expected_role == role and row.predicted_role == role
            for row in predictions
        )
        fp = sum(
            row.expected_role != role and row.predicted_role == role
            for row in predictions
        )
        fn = sum(
            row.expected_role == role and row.predicted_role != role
            for row in predictions
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        scores.append(f1)
    return sum(scores) / len(scores)


def summarize(predictions: list[RolePrediction]) -> dict[str, Any]:
    allow_rows = [row for row in predictions if row.expected_allow]
    veto_rows = [row for row in predictions if not row.expected_allow]
    exact_allow = [
        row for row in allow_rows if row.predicted_role == row.expected_role
    ]
    false_approvals = [row for row in veto_rows if row.predicted_allow]
    wrong_allow_mode = [
        row
        for row in allow_rows
        if row.predicted_allow and row.predicted_role != row.expected_role
    ]
    false_vetoes = [row for row in allow_rows if not row.predicted_allow]
    exact = [row for row in predictions if row.predicted_role == row.expected_role]

    by_language: dict[str, dict[str, float | int]] = {}
    for language in cases.LANGUAGES:
        targets = [row for row in allow_rows if row.language == language]
        correct = [row for row in targets if row.predicted_role == row.expected_role]
        by_language[language] = {
            "allow_cases": len(targets),
            "exact_allow_cases": len(correct),
            "allow_recall": round(len(correct) / len(targets), 6),
        }

    by_role: dict[str, dict[str, float | int]] = {}
    for role in cases.ROLES:
        targets = [row for row in predictions if row.expected_role == role]
        correct = [row for row in targets if row.predicted_role == role]
        predicted = [row for row in predictions if row.predicted_role == role]
        precision = len(correct) / len(predicted) if predicted else 0.0
        recall = len(correct) / len(targets) if targets else 0.0
        by_role[role] = {
            "cases": len(targets),
            "predicted": len(predicted),
            "exact": len(correct),
            "precision": round(precision, 6),
            "recall": round(recall, 6),
        }

    allow_recall = len(exact_allow) / len(allow_rows)
    checks = {
        "zero_unsafe_false_approvals": not false_approvals,
        "zero_wrong_allow_modes": not wrong_allow_mode,
        "overall_allow_recall_at_least_0_90": allow_recall >= ALLOW_RECALL_FLOOR,
        "each_allow_role_recall_at_least_0_90": all(
            float(by_role[role]["recall"]) >= ALLOW_ROLE_RECALL_FLOOR
            for role in cases.ALLOW_ROLES
        ),
        "each_language_allow_recall_at_least_0_85": all(
            float(metrics["allow_recall"]) >= LANGUAGE_ALLOW_RECALL_FLOOR
            for metrics in by_language.values()
        ),
        "single_label_argmax_no_threshold": True,
        "cloud_provider_calls_zero": True,
    }
    confusion = Counter(
        (row.expected_role, row.predicted_role) for row in predictions
    )
    return {
        "cases": len(predictions),
        "allow_cases": len(allow_rows),
        "veto_cases": len(veto_rows),
        "unsafe_false_approval_cases": len(false_approvals),
        "wrong_allow_mode_cases": len(wrong_allow_mode),
        "false_veto_cases": len(false_vetoes),
        "allow_recall": round(allow_recall, 6),
        "exact_role_accuracy": round(len(exact) / len(predictions), 6),
        "macro_f1": round(_macro_f1(predictions), 6),
        "by_language": by_language,
        "by_role": by_role,
        "unsafe_false_approval_case_ids": [row.case_id for row in false_approvals],
        "wrong_allow_mode_case_ids": [row.case_id for row in wrong_allow_mode],
        "false_veto_case_ids": [row.case_id for row in false_vetoes],
        "confusion": {
            f"{expected}->{predicted}": count
            for (expected, predicted), count in sorted(confusion.items())
        },
        "continuation_checks": checks,
        "passes_development_gate": all(checks.values()),
    }


def _rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload["cases"]
    if not isinstance(rows, list):
        raise TypeError("question-role cases must be a list")
    return rows


def _rss_bytes() -> int:
    import psutil

    return int(psutil.Process().memory_info().rss)


def _resource_rejection(candidate: dict[str, str], error: str) -> dict[str, Any]:
    return {
        "key": candidate["key"],
        "model_id": candidate["model_id"],
        "revision": candidate["revision"],
        "status": "RESOURCE_REJECTED",
        "error": error,
        "summary": {"passes_development_gate": False},
        "resources": {
            "inference_ms_per_case": float("inf"),
            "cuda_delta_peak_allocated_bytes": float("inf"),
        },
    }


def _run_candidate(
    candidate: dict[str, str],
    rows: list[dict[str, object]],
) -> dict[str, Any]:
    import torch
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from transformers import AutoTokenizer

    model = None
    tokenizer = None
    classifier = None
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    cuda_baseline = int(torch.cuda.memory_allocated())
    rss_baseline = _rss_bytes()
    rss_samples = [rss_baseline]

    try:
        load_started = time.perf_counter()
        model = GLiClassModel.from_pretrained(
            candidate["model_id"],
            revision=candidate["revision"],
            use_safetensors=True,
            trust_remote_code=False,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            candidate["model_id"],
            revision=candidate["revision"],
            trust_remote_code=False,
        )
        classifier = ZeroShotClassificationPipeline(
            model,
            tokenizer,
            max_classes=len(LABEL_TEXTS),
            max_length=MAX_LENGTH,
            classification_type="single-label",
            device="cuda:0",
            progress_bar=False,
        )
        torch.cuda.synchronize()
        load_seconds = time.perf_counter() - load_started
        rss_samples.append(_rss_bytes())

        parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
        parameter_bytes = sum(
            int(parameter.numel() * parameter.element_size())
            for parameter in model.parameters()
        )

        started = time.perf_counter()
        outputs = classifier(
            [str(row["query"]) for row in rows],
            list(LABEL_TEXTS),
            batch_size=BATCH_SIZE,
            classification_type="single-label",
            prompt=TASK_PROMPT,
        )
        torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - started
        rss_samples.append(_rss_bytes())
    except torch.cuda.OutOfMemoryError as exc:
        return _resource_rejection(candidate, f"{type(exc).__name__}: {exc}")
    finally:
        if "outputs" not in locals():
            if classifier is not None:
                del classifier
            if model is not None:
                del model
            if tokenizer is not None:
                del tokenizer
            gc.collect()
            torch.cuda.empty_cache()

    if not isinstance(outputs, list) or len(outputs) != len(rows):
        raise TypeError("GLiClass returned an unexpected batch output")

    predictions: list[RolePrediction] = []
    for row, output in zip(rows, outputs, strict=True):
        if not isinstance(output, list) or len(output) != 1:
            raise TypeError("single-label GLiClass output must contain exactly one label")
        item = output[0]
        if not isinstance(item, dict):
            raise TypeError("GLiClass prediction must be a mapping")
        label = str(item.get("label", ""))
        predicted_role = LABEL_TO_ROLE.get(label)
        if predicted_role is None:
            raise RuntimeError(f"GLiClass returned unknown role label: {label!r}")
        predictions.append(
            RolePrediction(
                case_id=str(row["case_id"]),
                language=str(row["language"]),
                expected_role=str(row["role"]),
                predicted_role=predicted_role,
            )
        )

    summary = summarize(predictions)
    cuda_peak = int(torch.cuda.max_memory_allocated())
    rss_peak = max(rss_samples)
    result = {
        "key": candidate["key"],
        "model_id": candidate["model_id"],
        "revision": candidate["revision"],
        "status": "COMPLETE",
        "decision_contract": {
            "task": "multilingual_zero_shot_question_role_classification",
            "classification_type": "single-label",
            "decision": "softmax_argmax",
            "threshold_used_for_decision": False,
            "few_shot_examples": 0,
            "max_length": MAX_LENGTH,
            "batch_size": BATCH_SIZE,
            "task_prompt": TASK_PROMPT,
            "labels": ROLE_LABELS,
            "weights": "safetensors_only",
            "trust_remote_code": False,
        },
        "summary": summary,
        "resources": {
            "model_load_seconds": round(load_seconds, 4),
            "inference_seconds": round(inference_seconds, 4),
            "inference_ms_per_case": round(
                inference_seconds * 1000.0 / len(rows), 4
            ),
            "parameter_count": parameter_count,
            "parameter_bytes": parameter_bytes,
            "rss_baseline_bytes": rss_baseline,
            "rss_peak_sampled_bytes": rss_peak,
            "rss_delta_peak_sampled_bytes": max(0, rss_peak - rss_baseline),
            "cuda_baseline_allocated_bytes": cuda_baseline,
            "cuda_peak_allocated_bytes": cuda_peak,
            "cuda_delta_peak_allocated_bytes": max(0, cuda_peak - cuda_baseline),
        },
    }

    del outputs, classifier, model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return result


def select_candidate(results: list[dict[str, Any]]) -> str | None:
    passing = [
        row
        for row in results
        if row.get("status") == "COMPLETE"
        and bool(row["summary"]["passes_development_gate"])
    ]
    if not passing:
        return None

    def key(row: dict[str, Any]) -> tuple[float, ...]:
        summary = row["summary"]
        resources = row["resources"]
        language_floor = min(
            float(metrics["allow_recall"])
            for metrics in summary["by_language"].values()
        )
        return (
            float(summary["unsafe_false_approval_cases"]),
            float(summary["wrong_allow_mode_cases"]),
            -float(summary["allow_recall"]),
            -language_floor,
            -float(summary["exact_role_accuracy"]),
            -float(summary["macro_f1"]),
            float(resources["inference_ms_per_case"]),
            float(resources["cuda_delta_peak_allocated_bytes"]),
        )

    return str(min(passing, key=key)["key"])


def run() -> dict[str, Any]:
    import gliclass
    import torch
    import transformers

    if not torch.cuda.is_available():
        raise RuntimeError("question-role bake-off requires the owner CUDA path")
    if getattr(gliclass, "__version__", None) != GLICLASS_PACKAGE_VERSION:
        raise RuntimeError(
            "unexpected GLiClass version: "
            f"{getattr(gliclass, '__version__', None)!r} != "
            f"{GLICLASS_PACKAGE_VERSION!r}"
        )

    payload = _assert_frozen_payload()
    _assert_no_retired_query_overlap(payload)
    rows = _rows(payload)
    results = [_run_candidate(candidate, rows) for candidate in CANDIDATES]
    selected = select_candidate(results)

    return {
        "status": "DEVELOPMENT_QUESTION_ROLE_BAKEOFF_V1_COMPLETE",
        "phase45d": "ACTIVE",
        "phase45e_authorized": False,
        "cloud_provider_calls": 0,
        "corpus": {
            **cases.public_summary(),
            "retired_exact_query_overlap": 0,
            "retired_corpora_used_for_training": False,
            "retired_corpora_used_for_scoring": False,
        },
        "environment": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "gliclass": gliclass.__version__,
            "gpu": torch.cuda.get_device_name(0),
        },
        "candidates": results,
        "decision": {
            "selected_candidate": selected,
            "candidate_selected": selected is not None,
            "production_change_authorized": False,
            "fresh_composite_integration_test_authorized": selected is not None,
            "fresh_final_acceptance_authorized": False,
            "phase45e_authorized": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = Path(args.output)
    if output.exists():
        raise RuntimeError(f"refusing to overwrite question-role evidence: {output}")

    result = run()
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output}")
    print("STATUS:", result["status"])
    print(
        "ROLE_SUMMARY:",
        json.dumps(
            {
                row["key"]: {
                    "status": row["status"],
                    "unsafe_false_approval_cases": row["summary"].get(
                        "unsafe_false_approval_cases"
                    ),
                    "wrong_allow_mode_cases": row["summary"].get(
                        "wrong_allow_mode_cases"
                    ),
                    "false_veto_cases": row["summary"].get("false_veto_cases"),
                    "allow_recall": row["summary"].get("allow_recall"),
                    "exact_role_accuracy": row["summary"].get(
                        "exact_role_accuracy"
                    ),
                    "macro_f1": row["summary"].get("macro_f1"),
                    "by_language": row["summary"].get("by_language"),
                    "by_role": row["summary"].get("by_role"),
                    "passes_development_gate": row["summary"][
                        "passes_development_gate"
                    ],
                    "inference_ms_per_case": row["resources"][
                        "inference_ms_per_case"
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
