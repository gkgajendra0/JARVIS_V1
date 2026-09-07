"""Zero-training answerability component bake-off for Phase 4.5D."""

from __future__ import annotations

import argparse
import gc
import json
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import step4_phase45d_answerability_cases as cases

OUTPUT_DEFAULT = Path(".step4-phase45d-answerability-bakeoff-v1.json")
FROZEN_PAYLOAD_SHA256: Final = (
    "3e2bd6830df3d08b3ea4ce8e045ee78cf562c228c5b0d2e5e094ffa42b6b44a3"
)
MAX_ANSWER_LENGTH: Final = 16
QA_MAX_SEQUENCE_LENGTH: Final = 256
NLI_MAX_LENGTH: Final = 256
NLI_BATCH_SIZE: Final = 32

QA_CANDIDATES: Final = (
    {
        "key": "xlm_roberta_base_squad2",
        "model_id": "deepset/xlm-roberta-base-squad2",
        "revision": "a5fab9908c8d856e8c583fd41ba6d92444e46477",
    },
    {
        "key": "mdeberta_v3_base_squad2",
        "model_id": "timpal0l/mdeberta-v3-base-squad2",
        "revision": "08d6e89c7a6557f967db2e1021f7f640483400ed",
    },
)
NLI_CANDIDATE: Final = {
    "key": "mdeberta_native_nli",
    "model_id": "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
    "revision": "b5113eb38ab63efdd7f280f8c144ea8b13f978ce",
}

QA_ANSWERABLE_RECALL_FLOOR: Final = 0.90
QA_LANGUAGE_RECALL_FLOOR: Final = 0.85
NLI_COMPARISON_RECALL_FLOOR: Final = 0.90
NLI_LANGUAGE_RECALL_FLOOR: Final = 0.85


@dataclass(frozen=True, slots=True)
class QAPrediction:
    case_id: str
    language: str
    kind: str
    expected_answerable: bool
    expected_answer: str
    answer: str
    score: float


@dataclass(frozen=True, slots=True)
class NLIPrediction:
    case_id: str
    language: str
    kind: str
    expected_label: str
    predicted_label: str


def _normalized_answer(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    return normalized.strip(" \t\r\n.,;:!?\"'“”‘’()[]{}")


def _assert_frozen_payload() -> dict[str, object]:
    payload = cases.build_payload()
    actual = cases.payload_sha256(payload)
    if actual != FROZEN_PAYLOAD_SHA256:
        raise RuntimeError(
            f"answerability corpus SHA mismatch: {actual} != {FROZEN_PAYLOAD_SHA256}"
        )
    return payload


def _assert_no_retired_query_overlap(payload: dict[str, object]) -> None:
    import step4_phase45d_final_composite_cases as v4
    import step4_phase45d_task_specific_guard_cases as method_v2

    retired: set[str] = set()

    v4_payload = v4.build_payload()
    retired.update(
        cases.normalized_query(str(row["query"])) for row in v4_payload["queries"]
    )

    v2_payload = method_v2.build_payload()
    retired.update(
        cases.normalized_query(str(row["query"]))
        for row in list(v2_payload["train"]) + list(v2_payload["holdout"])
    )

    fresh_questions: set[str] = set()
    for row in payload["qa_cases"]:
        fresh_questions.add(cases.normalized_query(str(row["question"])))
    for row in payload["nli_cases"]:
        fresh_questions.add(cases.normalized_query(str(row["question"])))

    overlap = sorted(retired.intersection(fresh_questions))
    if overlap:
        raise RuntimeError(
            f"answerability corpus overlaps retired queries: {overlap[:3]}"
        )


def summarize_qa(predictions: list[QAPrediction]) -> dict[str, Any]:
    answerable = [row for row in predictions if row.expected_answerable]
    null_cases = [row for row in predictions if not row.expected_answerable]
    correct_answers = [
        row
        for row in answerable
        if _normalized_answer(row.answer) == _normalized_answer(row.expected_answer)
    ]
    false_vetoes = [row for row in answerable if not _normalized_answer(row.answer)]
    wrong_evidence = [
        row
        for row in answerable
        if _normalized_answer(row.answer)
        and _normalized_answer(row.answer) != _normalized_answer(row.expected_answer)
    ]
    unauthorized = [row for row in null_cases if _normalized_answer(row.answer)]
    correct_nulls = [row for row in null_cases if not _normalized_answer(row.answer)]

    by_language: dict[str, dict[str, float | int]] = {}
    for language in cases.LANGUAGES:
        targets = [row for row in answerable if row.language == language]
        exact = [
            row
            for row in targets
            if _normalized_answer(row.answer) == _normalized_answer(row.expected_answer)
        ]
        by_language[language] = {
            "answerable_cases": len(targets),
            "exact_answers": len(exact),
            "answerable_recall": round(len(exact) / len(targets), 6),
        }

    by_kind: dict[str, dict[str, float | int]] = {}
    for kind in cases.QA_ANSWERABLE_KINDS + cases.QA_NULL_KINDS:
        rows = [row for row in predictions if row.kind == kind]
        correct = [
            row
            for row in rows
            if _normalized_answer(row.answer) == _normalized_answer(row.expected_answer)
        ]
        by_kind[kind] = {
            "cases": len(rows),
            "correct": len(correct),
            "exact_rate": round(len(correct) / len(rows), 6),
        }

    answerable_recall = len(correct_answers) / len(answerable)
    null_recall = len(correct_nulls) / len(null_cases)
    checks = {
        "zero_unauthorized_releases": not unauthorized,
        "zero_wrong_evidence_releases": not wrong_evidence,
        "answerable_recall_at_least_0_90": (
            answerable_recall >= QA_ANSWERABLE_RECALL_FLOOR
        ),
        "each_language_answerable_recall_at_least_0_85": all(
            float(metrics["answerable_recall"]) >= QA_LANGUAGE_RECALL_FLOOR
            for metrics in by_language.values()
        ),
        "native_no_answer_decision_no_fitted_threshold": True,
        "cloud_provider_calls_zero": True,
    }
    return {
        "cases": len(predictions),
        "answerable_cases": len(answerable),
        "null_cases": len(null_cases),
        "exact_answers": len(correct_answers),
        "correct_nulls": len(correct_nulls),
        "false_veto_cases": len(false_vetoes),
        "wrong_evidence_release_cases": len(wrong_evidence),
        "unauthorized_release_cases": len(unauthorized),
        "answerable_recall": round(answerable_recall, 6),
        "null_recall": round(null_recall, 6),
        "by_language": by_language,
        "by_kind": by_kind,
        "false_veto_case_ids": [row.case_id for row in false_vetoes],
        "wrong_evidence_release_case_ids": [row.case_id for row in wrong_evidence],
        "unauthorized_release_case_ids": [row.case_id for row in unauthorized],
        "unauthorized_by_kind": dict(
            sorted(Counter(row.kind for row in unauthorized).items())
        ),
        "continuation_checks": checks,
        "passes_development_gate": all(checks.values()),
    }


def summarize_nli(predictions: list[NLIPrediction]) -> dict[str, Any]:
    answerable = [row for row in predictions if row.expected_label != "neutral"]
    unknown = [row for row in predictions if row.expected_label == "neutral"]
    exact = [row for row in predictions if row.predicted_label == row.expected_label]
    answerable_exact = [
        row for row in answerable if row.predicted_label == row.expected_label
    ]
    false_vetoes = [row for row in answerable if row.predicted_label == "neutral"]
    wrong_boolean = [
        row
        for row in answerable
        if row.predicted_label not in {row.expected_label, "neutral"}
    ]
    unauthorized = [row for row in unknown if row.predicted_label != "neutral"]

    by_language: dict[str, dict[str, float | int]] = {}
    for language in cases.LANGUAGES:
        targets = [row for row in answerable if row.language == language]
        correct = [row for row in targets if row.predicted_label == row.expected_label]
        by_language[language] = {
            "comparison_cases": len(targets),
            "exact": len(correct),
            "comparison_recall": round(len(correct) / len(targets), 6),
        }

    by_kind: dict[str, dict[str, float | int]] = {}
    for kind in cases.NLI_KINDS:
        rows = [row for row in predictions if row.kind == kind]
        correct = [row for row in rows if row.predicted_label == row.expected_label]
        by_kind[kind] = {
            "cases": len(rows),
            "exact": len(correct),
            "exact_rate": round(len(correct) / len(rows), 6),
        }

    comparison_recall = len(answerable_exact) / len(answerable)
    accuracy = len(exact) / len(predictions)
    checks = {
        "zero_unauthorized_boolean_releases": not unauthorized,
        "zero_wrong_boolean_verdicts": not wrong_boolean,
        "comparison_recall_at_least_0_90": (
            comparison_recall >= NLI_COMPARISON_RECALL_FLOOR
        ),
        "each_language_comparison_recall_at_least_0_85": all(
            float(metrics["comparison_recall"]) >= NLI_LANGUAGE_RECALL_FLOOR
            for metrics in by_language.values()
        ),
        "native_argmax_no_probability_threshold": True,
        "cloud_provider_calls_zero": True,
    }
    return {
        "cases": len(predictions),
        "answerable_comparison_cases": len(answerable),
        "unknown_cases": len(unknown),
        "exact_cases": len(exact),
        "false_veto_cases": len(false_vetoes),
        "wrong_boolean_verdict_cases": len(wrong_boolean),
        "unauthorized_boolean_release_cases": len(unauthorized),
        "comparison_recall": round(comparison_recall, 6),
        "accuracy": round(accuracy, 6),
        "by_language": by_language,
        "by_kind": by_kind,
        "false_veto_case_ids": [row.case_id for row in false_vetoes],
        "wrong_boolean_verdict_case_ids": [row.case_id for row in wrong_boolean],
        "unauthorized_boolean_release_case_ids": [row.case_id for row in unauthorized],
        "continuation_checks": checks,
        "passes_development_gate": all(checks.values()),
    }


def select_qa_candidate(results: list[dict[str, Any]]) -> str | None:
    passing = [
        row for row in results if bool(row["summary"]["passes_development_gate"])
    ]
    if not passing:
        return None

    def key(row: dict[str, Any]) -> tuple[float, ...]:
        summary = row["summary"]
        resources = row["resources"]
        language_floor = min(
            float(metrics["answerable_recall"])
            for metrics in summary["by_language"].values()
        )
        return (
            float(summary["unauthorized_release_cases"]),
            float(summary["wrong_evidence_release_cases"]),
            -float(summary["answerable_recall"]),
            -language_floor,
            float(resources["inference_ms_per_case"]),
            float(resources["cuda_delta_peak_allocated_bytes"]),
        )

    return str(min(passing, key=key)["key"])


def _rss_bytes() -> int:
    import psutil

    return int(psutil.Process().memory_info().rss)


def _qa_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload["qa_cases"]
    if not isinstance(rows, list):
        raise TypeError("qa_cases must be a list")
    return rows


def _nli_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload["nli_cases"]
    if not isinstance(rows, list):
        raise TypeError("nli_cases must be a list")
    return rows


def _select_qa_answer(
    *,
    context: str,
    input_ids: list[int],
    sequence_ids: list[int | None],
    offset_mapping: list[list[int]],
    start_logits: list[float],
    end_logits: list[float],
    cls_token_id: int,
    max_answer_len: int = MAX_ANSWER_LENGTH,
) -> tuple[str, float]:
    size = len(input_ids)
    if not (
        len(sequence_ids)
        == len(offset_mapping)
        == len(start_logits)
        == len(end_logits)
        == size
    ):
        raise ValueError("QA selector inputs must have identical token lengths")

    try:
        cls_index = input_ids.index(cls_token_id)
    except ValueError as exc:
        raise RuntimeError(
            "QA tokenizer output does not contain its CLS token"
        ) from exc

    context_indices = [
        index
        for index, sequence_id in enumerate(sequence_ids)
        if sequence_id == 1 and offset_mapping[index][1] > offset_mapping[index][0]
    ]
    null_score = float(start_logits[cls_index] + end_logits[cls_index])
    if not context_indices:
        return "", null_score

    best_start: int | None = None
    best_end: int | None = None
    best_score = float("-inf")
    context_index_set = set(context_indices)

    for start in context_indices:
        max_end = start + max_answer_len - 1
        for end in range(start, min(max_end, size - 1) + 1):
            if end not in context_index_set:
                continue
            score = float(start_logits[start] + end_logits[end])
            if score > best_score:
                best_start = start
                best_end = end
                best_score = score

    if best_start is None or best_end is None or null_score > best_score:
        return "", null_score

    start_char = int(offset_mapping[best_start][0])
    end_char = int(offset_mapping[best_end][1])
    if start_char < 0 or end_char <= start_char or end_char > len(context):
        raise RuntimeError(
            f"QA tokenizer returned invalid context offsets: {start_char}:{end_char}"
        )
    return context[start_char:end_char], best_score


def _run_qa_candidate(
    candidate: dict[str, str],
    rows: list[dict[str, object]],
) -> dict[str, Any]:
    import torch
    from transformers import AutoModelForQuestionAnswering, AutoTokenizer

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    cuda_baseline = int(torch.cuda.memory_allocated())
    rss_baseline = _rss_bytes()
    rss_samples = [rss_baseline]

    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        candidate["model_id"],
        revision=candidate["revision"],
        trust_remote_code=False,
    )
    model = AutoModelForQuestionAnswering.from_pretrained(
        candidate["model_id"],
        revision=candidate["revision"],
        trust_remote_code=False,
        use_safetensors=True,
    )
    model.to("cuda")
    model.eval()
    if tokenizer.cls_token_id is None:
        raise RuntimeError("QA tokenizer must define a CLS token for no-answer scoring")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started
    rss_samples.append(_rss_bytes())

    parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
    parameter_bytes = sum(
        int(parameter.numel() * parameter.element_size())
        for parameter in model.parameters()
    )

    predictions: list[QAPrediction] = []
    started = time.perf_counter()
    for row in rows:
        context = str(row["context"])
        encoded = tokenizer(
            str(row["question"]),
            context,
            return_tensors="pt",
            return_offsets_mapping=True,
            truncation="only_second",
            max_length=QA_MAX_SEQUENCE_LENGTH,
        )
        sequence_ids = list(encoded.sequence_ids(0))
        offset_mapping = encoded.pop("offset_mapping")[0].tolist()
        input_ids = encoded["input_ids"][0].tolist()
        device_inputs = {name: value.to("cuda") for name, value in encoded.items()}
        with torch.inference_mode():
            output = model(**device_inputs)
        answer, score = _select_qa_answer(
            context=context,
            input_ids=input_ids,
            sequence_ids=sequence_ids,
            offset_mapping=offset_mapping,
            start_logits=output.start_logits[0].detach().float().cpu().tolist(),
            end_logits=output.end_logits[0].detach().float().cpu().tolist(),
            cls_token_id=int(tokenizer.cls_token_id),
        )
        predictions.append(
            QAPrediction(
                case_id=str(row["case_id"]),
                language=str(row["language"]),
                kind=str(row["kind"]),
                expected_answerable=bool(row["expected_answerable"]),
                expected_answer=str(row["expected_answer"]),
                answer=answer,
                score=score,
            )
        )
    torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    rss_samples.append(_rss_bytes())

    summary = summarize_qa(predictions)
    cuda_peak = int(torch.cuda.max_memory_allocated())
    rss_peak = max(rss_samples)

    result = {
        "key": candidate["key"],
        "model_id": candidate["model_id"],
        "revision": candidate["revision"],
        "decision_contract": {
            "task": "extractive_question_answering_with_no_answer",
            "adapter": "transformers_v5_native_qa_logits",
            "null_candidate": "cls_start_plus_end_logit",
            "span_candidate": "best_valid_context_start_plus_end_logit",
            "null_wins_only_when_strictly_greater": True,
            "max_sequence_length": QA_MAX_SEQUENCE_LENGTH,
            "max_answer_length": MAX_ANSWER_LENGTH,
            "fitted_probability_threshold": None,
            "weights": "safetensors_only",
            "trust_remote_code": False,
        },
        "summary": summary,
        "resources": {
            "model_load_seconds": round(load_seconds, 4),
            "inference_seconds": round(inference_seconds, 4),
            "inference_ms_per_case": round(inference_seconds * 1000.0 / len(rows), 4),
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

    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return result


def _run_nli_candidate(
    candidate: dict[str, str],
    rows: list[dict[str, object]],
) -> dict[str, Any]:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    cuda_baseline = int(torch.cuda.memory_allocated())
    rss_baseline = _rss_bytes()
    rss_samples = [rss_baseline]

    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        candidate["model_id"],
        revision=candidate["revision"],
        trust_remote_code=False,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        candidate["model_id"],
        revision=candidate["revision"],
        trust_remote_code=False,
        use_safetensors=True,
    )
    model.to("cuda")
    model.eval()
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started
    rss_samples.append(_rss_bytes())

    expected_labels = {"entailment", "neutral", "contradiction"}
    actual_labels = {str(label).casefold() for label in model.config.id2label.values()}
    if actual_labels != expected_labels:
        raise RuntimeError(
            f"native NLI label contract changed: {actual_labels} != {expected_labels}"
        )

    parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
    parameter_bytes = sum(
        int(parameter.numel() * parameter.element_size())
        for parameter in model.parameters()
    )

    predictions: list[NLIPrediction] = []
    started = time.perf_counter()
    for offset in range(0, len(rows), NLI_BATCH_SIZE):
        batch = rows[offset : offset + NLI_BATCH_SIZE]
        encoded = tokenizer(
            [str(row["premise"]) for row in batch],
            [str(row["hypothesis"]) for row in batch],
            padding=True,
            truncation=True,
            max_length=NLI_MAX_LENGTH,
            return_tensors="pt",
        )
        encoded = {name: value.to("cuda") for name, value in encoded.items()}
        with torch.inference_mode():
            logits = model(**encoded).logits
        indices = logits.argmax(dim=-1).detach().cpu().tolist()
        for row, index in zip(batch, indices, strict=True):
            predicted_label = str(model.config.id2label[int(index)]).casefold()
            predictions.append(
                NLIPrediction(
                    case_id=str(row["case_id"]),
                    language=str(row["language"]),
                    kind=str(row["kind"]),
                    expected_label=str(row["expected_label"]),
                    predicted_label=predicted_label,
                )
            )
    torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    rss_samples.append(_rss_bytes())

    summary = summarize_nli(predictions)
    cuda_peak = int(torch.cuda.max_memory_allocated())
    rss_peak = max(rss_samples)

    result = {
        "key": candidate["key"],
        "model_id": candidate["model_id"],
        "revision": candidate["revision"],
        "decision_contract": {
            "task": "native_multilingual_nli",
            "labels": ["entailment", "neutral", "contradiction"],
            "max_length": NLI_MAX_LENGTH,
            "batch_size": NLI_BATCH_SIZE,
            "decision": "argmax",
            "fitted_probability_threshold": None,
            "weights": "safetensors_only",
            "trust_remote_code": False,
        },
        "summary": summary,
        "resources": {
            "model_load_seconds": round(load_seconds, 4),
            "inference_seconds": round(inference_seconds, 4),
            "inference_ms_per_case": round(inference_seconds * 1000.0 / len(rows), 4),
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

    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return result


def run() -> dict[str, Any]:
    import torch
    import transformers

    if not torch.cuda.is_available():
        raise RuntimeError("answerability bake-off requires the owner CUDA path")

    payload = _assert_frozen_payload()
    _assert_no_retired_query_overlap(payload)
    qa_rows = _qa_rows(payload)
    nli_rows = _nli_rows(payload)

    qa_results = [_run_qa_candidate(candidate, qa_rows) for candidate in QA_CANDIDATES]
    nli_result = _run_nli_candidate(NLI_CANDIDATE, nli_rows)
    selected_qa = select_qa_candidate(qa_results)
    nli_passes = bool(nli_result["summary"]["passes_development_gate"])

    return {
        "status": "DEVELOPMENT_ANSWERABILITY_BAKEOFF_V1_COMPLETE",
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
            "gpu": torch.cuda.get_device_name(0),
        },
        "qa_candidates": qa_results,
        "nli_candidate": nli_result,
        "decision": {
            "selected_qa_candidate": selected_qa,
            "qa_candidate_selected": selected_qa is not None,
            "nli_native_task_passes": nli_passes,
            "composite_development_pass": selected_qa is not None and nli_passes,
            "production_change_authorized": False,
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
        raise RuntimeError(f"refusing to overwrite answerability evidence: {output}")

    result = run()
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output}")
    print("STATUS:", result["status"])
    print(
        "QA_SUMMARY:",
        json.dumps(
            {
                row["key"]: {
                    "unauthorized_release_cases": row["summary"][
                        "unauthorized_release_cases"
                    ],
                    "wrong_evidence_release_cases": row["summary"][
                        "wrong_evidence_release_cases"
                    ],
                    "answerable_recall": row["summary"]["answerable_recall"],
                    "null_recall": row["summary"]["null_recall"],
                    "by_language": row["summary"]["by_language"],
                    "passes_development_gate": row["summary"][
                        "passes_development_gate"
                    ],
                    "inference_ms_per_case": row["resources"]["inference_ms_per_case"],
                    "cuda_delta_peak_allocated_bytes": row["resources"][
                        "cuda_delta_peak_allocated_bytes"
                    ],
                }
                for row in result["qa_candidates"]
            },
            ensure_ascii=False,
        ),
    )
    print(
        "NLI_SUMMARY:",
        json.dumps(
            {
                "unauthorized_boolean_release_cases": result["nli_candidate"][
                    "summary"
                ]["unauthorized_boolean_release_cases"],
                "wrong_boolean_verdict_cases": result["nli_candidate"]["summary"][
                    "wrong_boolean_verdict_cases"
                ],
                "comparison_recall": result["nli_candidate"]["summary"][
                    "comparison_recall"
                ],
                "accuracy": result["nli_candidate"]["summary"]["accuracy"],
                "by_language": result["nli_candidate"]["summary"]["by_language"],
                "passes_development_gate": result["nli_candidate"]["summary"][
                    "passes_development_gate"
                ],
                "inference_ms_per_case": result["nli_candidate"]["resources"][
                    "inference_ms_per_case"
                ],
                "cuda_delta_peak_allocated_bytes": result["nli_candidate"]["resources"][
                    "cuda_delta_peak_allocated_bytes"
                ],
            },
            ensure_ascii=False,
        ),
    )
    print("DECISION:", json.dumps(result["decision"], ensure_ascii=False))


if __name__ == "__main__":
    main()
