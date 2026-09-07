"""Development-only end-to-end task-guard fine-tuning bake-off for Phase 4.5D."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import step4_phase45d_task_guard_finetune_v3_cases as cases

OUTPUT_DEFAULT = Path(".step4-phase45d-task-guard-finetune-v3.json")
ARTIFACT_DIR_DEFAULT = Path(".step4-phase45d-task-guard-finetune-v3-artifacts")
FROZEN_CASE_SOURCE_GIT_BLOB: Final = "77f614d34b94e44277f4bf4bdaffa5da22989268"
RANDOM_STATE: Final = 45
MAX_LENGTH: Final = 128
NUM_TRAIN_EPOCHS: Final = 5.0
TRAIN_BATCH_SIZE: Final = 8
GRADIENT_ACCUMULATION_STEPS: Final = 2
EVAL_BATCH_SIZE: Final = 64
LEARNING_RATE: Final = 2e-5
WEIGHT_DECAY: Final = 0.01
WARMUP_RATIO: Final = 0.10

CANDIDATES: Final = (
    {
        "key": "mmbert_small",
        "model_id": "jhu-clsp/mmBERT-small",
        "revision": "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a",
        "family": "modernbert",
    },
    {
        "key": "mmbert_base",
        "model_id": "jhu-clsp/mmBERT-base",
        "revision": "eaee9e8f76c40fd045034538248ad9d59f380aac",
        "family": "modernbert",
    },
    {
        "key": "xlm_roberta_base",
        "model_id": "FacebookAI/xlm-roberta-base",
        "revision": "42f548f32366559214515ec137cdd16002968bf6",
        "family": "xlm-roberta",
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


def _git_blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    header = f"blob {len(raw)}\0".encode()
    return hashlib.sha1(header + raw).hexdigest()


def _assert_frozen_corpus() -> dict[str, object]:
    source_path = Path(cases.__file__).resolve()
    source_blob = _git_blob_sha(source_path)
    if source_blob != FROZEN_CASE_SOURCE_GIT_BLOB:
        raise RuntimeError(
            "task-guard V3 case-source Git blob mismatch: "
            f"{source_blob} != {FROZEN_CASE_SOURCE_GIT_BLOB}"
        )
    return cases.build_payload()


def _assert_no_retired_query_overlap(payload: dict[str, object]) -> None:
    import step4_phase45d_final_composite_cases as v4
    import step4_phase45d_task_specific_guard_cases as v2_guard

    retired_queries: set[str] = set()
    v4_payload = v4.build_payload()
    retired_queries.update(
        cases.normalized_query(str(row["query"])) for row in v4_payload["queries"]
    )
    v2_payload = v2_guard.build_payload()
    retired_queries.update(
        cases.normalized_query(str(row["query"]))
        for row in list(v2_payload["train"]) + list(v2_payload["holdout"])
    )
    new_queries = {
        cases.normalized_query(str(row["query"]))
        for row in list(payload["train"]) + list(payload["holdout"])
    }
    overlap = sorted(retired_queries.intersection(new_queries))
    if overlap:
        raise RuntimeError(f"task-guard V3 overlaps retired queries: {overlap[:3]}")


def _rows(payload: dict[str, object], split: str) -> list[dict[str, object]]:
    raw = payload[split]
    if not isinstance(raw, list):
        raise TypeError(f"{split} corpus must be a list")
    return raw


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
    inference_seconds: float,
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
        "retired_corpora_not_used_for_training_or_scoring": True,
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
        "train_seconds": round(train_seconds, 4),
        "inference_seconds": round(inference_seconds, 4),
        "inference_ms_per_query": round(
            (inference_seconds * 1000.0) / len(predictions),
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
        resources = row["resources"]
        return (
            float(summary["false_allow_cases"]),
            float(len(summary["negation_false_allow_case_ids"])),
            -float(summary["comparison_allow_recall"]),
            -float(summary["overall_allow_recall"]),
            -float(summary["macro_f1"]),
            float(summary["inference_ms_per_query"]),
            float(resources["parameter_bytes"]),
        )

    return str(min(passing, key=key)["key"])


def _rss_bytes() -> int:
    import psutil

    return int(psutil.Process().memory_info().rss)


def _tokenize_rows(tokenizer: Any, rows: list[dict[str, object]]) -> dict[str, Any]:
    texts = [str(row["query"]) for row in rows]
    return tokenizer(
        texts,
        truncation=True,
        max_length=MAX_LENGTH,
        padding=False,
    )


def _predict(
    model: Any,
    tokenizer: Any,
    rows: list[dict[str, object]],
    *,
    device: str,
) -> tuple[list[str], float]:
    import torch

    predicted: list[str] = []
    model.eval()
    started = time.perf_counter()
    for offset in range(0, len(rows), EVAL_BATCH_SIZE):
        batch_rows = rows[offset : offset + EVAL_BATCH_SIZE]
        encoded = tokenizer(
            [str(row["query"]) for row in batch_rows],
            truncation=True,
            max_length=MAX_LENGTH,
            padding=True,
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with (
            torch.inference_mode(),
            torch.autocast(
                device_type="cuda",
                dtype=torch.bfloat16,
                enabled=device == "cuda",
            ),
        ):
            logits = model(**encoded).logits
        indices = logits.argmax(dim=-1).detach().cpu().tolist()
        predicted.extend(str(model.config.id2label[int(index)]) for index in indices)
    if device == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    return predicted, elapsed


def _run_candidate(
    candidate: dict[str, object],
    *,
    train_rows: list[dict[str, object]],
    holdout_rows: list[dict[str, object]],
    device: str,
    artifact_root: Path,
) -> dict[str, Any]:
    import torch
    from datasets import Dataset
    from sklearn.metrics import accuracy_score, f1_score
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    if device != "cuda":
        raise RuntimeError("V3 is frozen for the owner CUDA path only")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")

    set_seed(RANDOM_STATE)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    cuda_baseline = int(torch.cuda.memory_allocated())
    rss_baseline = _rss_bytes()
    rss_samples = [rss_baseline]

    label2id = {label: index for index, label in enumerate(cases.LABELS)}
    id2label = {index: label for label, index in label2id.items()}

    print(
        f"Loading {candidate['key']}: {candidate['model_id']}@{candidate['revision']}"
    )
    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        str(candidate["model_id"]),
        revision=str(candidate["revision"]),
        trust_remote_code=False,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        str(candidate["model_id"]),
        revision=str(candidate["revision"]),
        num_labels=len(cases.LABELS),
        id2label=id2label,
        label2id=label2id,
        trust_remote_code=False,
        use_safetensors=True,
    )
    model_load_seconds = time.perf_counter() - load_started
    rss_samples.append(_rss_bytes())

    parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
    parameter_bytes = sum(
        int(parameter.numel() * parameter.element_size())
        for parameter in model.parameters()
    )

    train_payload = {
        "text": [str(row["query"]) for row in train_rows],
        "labels": [label2id[str(row["label"])] for row in train_rows],
    }
    train_dataset = Dataset.from_dict(train_payload)

    def tokenize_batch(batch: dict[str, list[Any]]) -> dict[str, Any]:
        return tokenizer(
            [str(value) for value in batch["text"]],
            truncation=True,
            max_length=MAX_LENGTH,
        )

    train_dataset = train_dataset.map(
        tokenize_batch,
        batched=True,
        remove_columns=["text"],
        load_from_cache_file=False,
    )
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer, pad_to_multiple_of=8)

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-v3-") as output_dir:
        training_args = TrainingArguments(
            output_dir=output_dir,
            overwrite_output_dir=True,
            eval_strategy="no",
            save_strategy="no",
            logging_strategy="no",
            report_to="none",
            num_train_epochs=NUM_TRAIN_EPOCHS,
            per_device_train_batch_size=TRAIN_BATCH_SIZE,
            gradient_accumulation_steps=GRADIENT_ACCUMULATION_STEPS,
            per_device_eval_batch_size=EVAL_BATCH_SIZE,
            learning_rate=LEARNING_RATE,
            weight_decay=WEIGHT_DECAY,
            warmup_ratio=WARMUP_RATIO,
            lr_scheduler_type="linear",
            bf16=True,
            fp16=False,
            tf32=False,
            seed=RANDOM_STATE,
            data_seed=RANDOM_STATE,
            dataloader_num_workers=0,
            dataloader_pin_memory=True,
            gradient_checkpointing=True,
            save_safetensors=True,
            disable_tqdm=True,
        )
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            processing_class=tokenizer,
            data_collator=data_collator,
        )
        train_started = time.perf_counter()
        trainer.train()
        if device == "cuda":
            torch.cuda.synchronize()
        train_seconds = time.perf_counter() - train_started
        rss_samples.append(_rss_bytes())
        del trainer

    predicted, inference_seconds = _predict(
        model,
        tokenizer,
        holdout_rows,
        device=device,
    )
    rss_samples.append(_rss_bytes())
    expected = [str(row["label"]) for row in holdout_rows]
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
    summary = summarize_predictions(
        _prediction_rows(holdout_rows, predicted),
        macro_f1=macro_f1,
        accuracy=accuracy,
        train_seconds=train_seconds,
        inference_seconds=inference_seconds,
    )

    artifact_path: str | None = None
    if bool(summary["passes_development_gate"]):
        candidate_dir = artifact_root / str(candidate["key"])
        candidate_dir.mkdir(parents=True, exist_ok=False)
        model.save_pretrained(candidate_dir, safe_serialization=True)
        tokenizer.save_pretrained(candidate_dir)
        artifact_path = str(candidate_dir)

    cuda_peak = int(torch.cuda.max_memory_allocated())
    rss_peak = max(rss_samples)
    result = {
        "key": candidate["key"],
        "model_id": candidate["model_id"],
        "revision": candidate["revision"],
        "family": candidate["family"],
        "training": {
            "task": "eight_class_sequence_classification",
            "max_length": MAX_LENGTH,
            "num_train_epochs": NUM_TRAIN_EPOCHS,
            "per_device_train_batch_size": TRAIN_BATCH_SIZE,
            "gradient_accumulation_steps": GRADIENT_ACCUMULATION_STEPS,
            "effective_train_batch_size": (
                TRAIN_BATCH_SIZE * GRADIENT_ACCUMULATION_STEPS
            ),
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "warmup_ratio": WARMUP_RATIO,
            "bf16": True,
            "gradient_checkpointing": True,
            "seed": RANDOM_STATE,
            "probability_threshold": None,
        },
        "resources": {
            "model_load_seconds": round(model_load_seconds, 4),
            "parameter_count": parameter_count,
            "parameter_bytes": parameter_bytes,
            "rss_baseline_bytes": rss_baseline,
            "rss_peak_sampled_bytes": rss_peak,
            "rss_delta_peak_sampled_bytes": max(0, rss_peak - rss_baseline),
            "cuda_baseline_allocated_bytes": cuda_baseline,
            "cuda_peak_allocated_bytes": cuda_peak,
            "cuda_delta_peak_allocated_bytes": max(0, cuda_peak - cuda_baseline),
        },
        "summary": summary,
        "artifact_path": artifact_path,
    }

    del model, tokenizer, train_dataset
    gc.collect()
    torch.cuda.empty_cache()
    return result


def run(*, device: str, artifact_root: Path) -> dict[str, Any]:
    payload = _assert_frozen_corpus()
    _assert_no_retired_query_overlap(payload)
    train_rows = _rows(payload, "train")
    holdout_rows = _rows(payload, "holdout")
    results = [
        _run_candidate(
            candidate,
            train_rows=train_rows,
            holdout_rows=holdout_rows,
            device=device,
            artifact_root=artifact_root,
        )
        for candidate in CANDIDATES
    ]
    selected = select_candidate(results)

    if selected is None:
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
    else:
        for row in results:
            key = str(row["key"])
            if key != selected and row["artifact_path"]:
                shutil.rmtree(Path(str(row["artifact_path"])))
                row["artifact_path"] = None

    return {
        "status": "DEVELOPMENT_TASK_GUARD_FINETUNE_V3_COMPLETE",
        "phase45d": "ACTIVE",
        "phase45e_authorized": False,
        "cloud_provider_calls": 0,
        "corpus": {
            **cases.public_summary(),
            "source_git_blob": FROZEN_CASE_SOURCE_GIT_BLOB,
            "retired_exact_query_overlap": 0,
            "retired_corpora_used_for_training": False,
            "retired_corpora_used_for_scoring": False,
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
            "fresh_final_acceptance_authorized": False,
            "phase45e_authorized": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda",), default="cuda")
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--artifact-dir", default=str(ARTIFACT_DIR_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = Path(args.output)
    artifact_root = Path(args.artifact_dir)
    if output.exists():
        raise RuntimeError(f"refusing to overwrite V3 evidence: {output}")
    if artifact_root.exists():
        raise RuntimeError(f"refusing to reuse V3 artifact directory: {artifact_root}")
    result = run(device=str(args.device), artifact_root=artifact_root)
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
                    "train_seconds": row["summary"]["train_seconds"],
                    "inference_ms_per_query": row["summary"]["inference_ms_per_query"],
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
