"""Development-only multilingual zero-shot answer-type diagnostic for Phase 4.5D."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import step4_phase45d_final_v2_cases as v2_cases
import step4_phase45d_structured_query_planner_diagnostic as planner_diag

MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
MODEL_REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
OUTPUT_DEFAULT = Path(".step4-phase45d-v2-zero-shot-answer-type-diagnostic-v1.json")
RESULT_STATUS = "DEVELOPMENT_ZERO_SHOT_ANSWER_TYPE_DIAGNOSTIC_COMPLETE"
MAX_LENGTH = 256
BATCH_SIZE = 32

ANSWER_TYPES: tuple[tuple[str, str], ...] = (
    ("current_value", "the current recorded value of a known property"),
    (
        "current_value_comparison",
        "whether a supplied value matches the current recorded value of a known property",
    ),
    ("reason_explanation", "the reason why a recorded value was chosen or used"),
    (
        "provenance_actor",
        "who recommended, supplied, selected, or originated a recorded value",
    ),
    (
        "replacement_successor",
        "the value that replaced a rejected, previous, or superseded value",
    ),
    (
        "related_record",
        "a separate related record or linked object rather than the recorded property value itself",
    ),
    (
        "other_or_advice",
        "advice, another preference, or information not represented by the recorded property value itself",
    ),
)
ANSWER_TYPE_KEYS = tuple(key for key, _ in ANSWER_TYPES)
ANSWER_TYPE_DESCRIPTIONS = dict(ANSWER_TYPES)
ALLOW_TYPES = frozenset({"current_value", "current_value_comparison"})
HYPOTHESIS_TEMPLATE = "This question asks for {description}."
SECURITY_CATEGORIES = frozenset(v2_cases.SECURITY_BOUNDARY_CATEGORIES)
EXPECTED_CASES = 30
EXPECTED_ALLOW_TARGETS = 12
EXPECTED_VETO_TARGETS = 18

EXPECTED_BY_CATEGORY = {
    "direct": "current_value",
    "cross_lingual": "current_value",
    "relation_mismatch": "current_value_comparison",
    "near_miss": "reason_explanation",
    "unsupported_source": "provenance_actor",
    "negation": "replacement_successor",
    "adversarial_lexical": "related_record",
    "absent": "related_record",
    "ambiguous": "other_or_advice",
}


@dataclass(frozen=True, slots=True)
class AnswerTypeCase:
    case_id: str
    language: str
    category: str
    expected_answer_type: str
    expected_allow: bool
    top_answer_type: str
    top_probability: float
    probabilities: dict[str, float]
    guard_allow: bool
    exact_answer_type_match: bool


def select_cases() -> list[dict[str, Any]]:
    payload = v2_cases.build_payload()
    selected = planner_diag.select_diagnostic_cases(payload)
    semantic = [
        item for item in selected if str(item["category"]) not in SECURITY_CATEGORIES
    ]
    if len(semantic) != EXPECTED_CASES:
        raise RuntimeError(
            f"expected {EXPECTED_CASES} semantic cases, got {len(semantic)}"
        )
    case_ids = [str(item["case_id"]) for item in semantic]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("zero-shot diagnostic case IDs must be unique")

    allow_targets = sum(_expected_allow(item) for item in semantic)
    if allow_targets != EXPECTED_ALLOW_TARGETS:
        raise RuntimeError(
            f"expected {EXPECTED_ALLOW_TARGETS} allow targets, got {allow_targets}"
        )
    if len(semantic) - allow_targets != EXPECTED_VETO_TARGETS:
        raise RuntimeError("zero-shot diagnostic veto-target count changed")
    return semantic


def _expected_answer_type(item: dict[str, Any]) -> str:
    category = str(item["category"])
    expected = EXPECTED_BY_CATEGORY.get(category)
    if expected is None:
        raise RuntimeError(f"unsupported zero-shot category: {category}")
    return expected


def _expected_allow(item: dict[str, Any]) -> bool:
    return _expected_answer_type(item) in ALLOW_TYPES


def _query_by_case_id() -> dict[str, str]:
    payload = v2_cases.build_payload()
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise TypeError("V2 queries must be a list")
    result: dict[str, str] = {}
    for item in queries:
        case_id = str(item["case_id"])
        if case_id in result:
            raise RuntimeError(f"duplicate V2 case ID: {case_id}")
        result[case_id] = str(item["query"])
    return result


def build_pairs(cases: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    query_map = _query_by_case_id()
    pairs: list[tuple[str, str, str]] = []
    for item in cases:
        case_id = str(item["case_id"])
        query = query_map.get(case_id)
        if query is None:
            raise RuntimeError(f"missing frozen V2 query: {case_id}")
        for key, description in ANSWER_TYPES:
            pairs.append(
                (
                    case_id,
                    query,
                    HYPOTHESIS_TEMPLATE.format(description=description),
                )
            )
    expected_pairs = len(cases) * len(ANSWER_TYPES)
    if len(pairs) != expected_pairs:
        raise RuntimeError("zero-shot inference-pair count changed")
    return pairs


def score_pairs(
    pairs: list[tuple[str, str, str]],
    *,
    device: str,
) -> tuple[dict[str, dict[str, float]], float]:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    normalized_device = device.strip().lower()
    if normalized_device not in {"cuda", "cpu"}:
        raise ValueError("device must be 'cuda' or 'cpu'")
    if normalized_device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=False,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=False,
        use_safetensors=True,
    )
    label2id = {
        str(key).casefold(): int(value) for key, value in model.config.label2id.items()
    }
    expected_labels = {"entailment": 0, "neutral": 1, "contradiction": 2}
    if label2id != expected_labels:
        raise RuntimeError(f"unexpected pinned NLI label mapping: {label2id!r}")

    target = torch.device(normalized_device)
    model = model.to(device=target, dtype=torch.float32)
    model.eval()

    entailment_logits: dict[str, list[float]] = {}
    for start in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[start : start + BATCH_SIZE]
        encoded = tokenizer(
            [query for _, query, _ in batch],
            [hypothesis for _, _, hypothesis in batch],
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        encoded = {name: value.to(target) for name, value in encoded.items()}
        with torch.inference_mode():
            logits = model(**encoded).logits.float().cpu()
        for (case_id, _, _), row in zip(batch, logits.tolist(), strict=True):
            if len(row) != 3:
                raise RuntimeError("pinned model must return exactly three NLI logits")
            entailment_logits.setdefault(case_id, []).append(float(row[0]))

    results: dict[str, dict[str, float]] = {}
    for case_id, logits in entailment_logits.items():
        if len(logits) != len(ANSWER_TYPES):
            raise RuntimeError(
                f"zero-shot label count changed for {case_id}: {len(logits)}"
            )
        tensor = torch.tensor(logits, dtype=torch.float32)
        probabilities = torch.softmax(tensor, dim=0).tolist()
        results[case_id] = {
            key: float(probability)
            for (key, _), probability in zip(ANSWER_TYPES, probabilities, strict=True)
        }

    if len(results) * len(ANSWER_TYPES) != len(pairs):
        raise RuntimeError("zero-shot scoring output count changed")
    return results, time.perf_counter() - started


def evaluate(
    cases: list[dict[str, Any]],
    scores: dict[str, dict[str, float]],
) -> list[AnswerTypeCase]:
    results: list[AnswerTypeCase] = []
    for item in cases:
        case_id = str(item["case_id"])
        probabilities = scores.get(case_id)
        if probabilities is None:
            raise RuntimeError(f"missing zero-shot scores for {case_id}")
        if set(probabilities) != set(ANSWER_TYPE_KEYS):
            raise RuntimeError(f"zero-shot label set changed for {case_id}")
        top_answer_type = max(probabilities, key=probabilities.__getitem__)
        expected_answer_type = _expected_answer_type(item)
        expected_allow = expected_answer_type in ALLOW_TYPES
        results.append(
            AnswerTypeCase(
                case_id=case_id,
                language=str(item["language"]),
                category=str(item["category"]),
                expected_answer_type=expected_answer_type,
                expected_allow=expected_allow,
                top_answer_type=top_answer_type,
                top_probability=round(probabilities[top_answer_type], 8),
                probabilities={
                    key: round(float(probabilities[key]), 8) for key in ANSWER_TYPE_KEYS
                },
                guard_allow=top_answer_type in ALLOW_TYPES,
                exact_answer_type_match=top_answer_type == expected_answer_type,
            )
        )
    return results


def summarize(results: list[AnswerTypeCase]) -> dict[str, Any]:
    allow_targets = [result for result in results if result.expected_allow]
    veto_targets = [result for result in results if not result.expected_allow]
    allowed_targets = [result for result in allow_targets if result.guard_allow]
    false_allows = [result for result in veto_targets if result.guard_allow]
    false_vetoes = [result for result in allow_targets if not result.guard_allow]
    direct_targets = [
        result
        for result in allow_targets
        if result.category in {"direct", "cross_lingual"}
    ]
    relation_targets = [
        result for result in allow_targets if result.category == "relation_mismatch"
    ]

    if len(allow_targets) != EXPECTED_ALLOW_TARGETS:
        raise RuntimeError("answer-type allow-target count changed")
    if len(veto_targets) != EXPECTED_VETO_TARGETS:
        raise RuntimeError("answer-type veto-target count changed")

    by_language: dict[str, dict[str, int | float]] = {}
    for language in v2_cases.LANGUAGES:
        rows = [result for result in allow_targets if result.language == language]
        allowed = sum(result.guard_allow for result in rows)
        if len(rows) != 4:
            raise RuntimeError(f"expected four allow targets for {language}")
        by_language[language] = {
            "allow_targets": len(rows),
            "allowed": allowed,
            "allow_recall": round(allowed / len(rows), 6),
        }

    exact_matches = sum(result.exact_answer_type_match for result in results)
    continuation_checks = {
        "zero_false_allows": not false_allows,
        "allow_at_least_10_of_12_targets": len(allowed_targets) >= 10,
        "direct_allow_at_least_8_of_9": sum(
            result.guard_allow for result in direct_targets
        )
        >= 8,
        "relation_comparison_allow_3_of_3": sum(
            result.guard_allow for result in relation_targets
        )
        == 3,
        "each_language_allow_at_least_3_of_4": all(
            metrics["allowed"] >= 3 for metrics in by_language.values()
        ),
        "zero_gemini_calls": True,
        "zero_qwen_calls": True,
        "no_threshold_fitting": True,
        "guard_is_veto_only": True,
    }

    top_probabilities = [result.top_probability for result in results]
    return {
        "cases": len(results),
        "allow_targets": len(allow_targets),
        "veto_targets": len(veto_targets),
        "allowed_target_cases": len(allowed_targets),
        "false_allow_cases": len(false_allows),
        "false_veto_cases": len(false_vetoes),
        "allow_target_recall": round(len(allowed_targets) / len(allow_targets), 6),
        "veto_target_specificity": round(
            (len(veto_targets) - len(false_allows)) / len(veto_targets), 6
        ),
        "exact_answer_type_matches": exact_matches,
        "exact_answer_type_accuracy": round(exact_matches / len(results), 6),
        "direct_allowed": sum(result.guard_allow for result in direct_targets),
        "relation_comparison_allowed": sum(
            result.guard_allow for result in relation_targets
        ),
        "by_language": by_language,
        "false_allow_case_ids": [result.case_id for result in false_allows],
        "false_veto_case_ids": [result.case_id for result in false_vetoes],
        "false_allows_by_category": dict(
            sorted(Counter(result.category for result in false_allows).items())
        ),
        "false_allows_by_language": dict(
            sorted(Counter(result.language for result in false_allows).items())
        ),
        "top_answer_types": dict(
            sorted(Counter(result.top_answer_type for result in results).items())
        ),
        "top_probability": {
            "min": round(min(top_probabilities), 8) if top_probabilities else None,
            "median": (
                round(statistics.median(top_probabilities), 8)
                if top_probabilities
                else None
            ),
            "max": round(max(top_probabilities), 8) if top_probabilities else None,
        },
        "continuation_checks": continuation_checks,
        "promising_for_architecture_review": all(continuation_checks.values()),
    }


def _public_case(result: AnswerTypeCase) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "language": result.language,
        "category": result.category,
        "expected_answer_type": result.expected_answer_type,
        "expected_allow": result.expected_allow,
        "top_answer_type": result.top_answer_type,
        "top_probability": result.top_probability,
        "probabilities": result.probabilities,
        "guard_allow": result.guard_allow,
        "exact_answer_type_match": result.exact_answer_type_match,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(f"refusing to overwrite existing diagnostic: {output_path}")

    cases = select_cases()
    pairs = build_pairs(cases)
    scores, inference_seconds = score_pairs(pairs, device=args.device)
    results = evaluate(cases, scores)
    summary = summarize(results)

    output = {
        "status": RESULT_STATUS,
        "development_only": True,
        "acceptance_evidence": False,
        "phase45e_authorized": False,
        "model": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "device": args.device,
            "mode": "multilingual_zero_shot_answer_type_classification",
            "max_length": MAX_LENGTH,
            "batch_size": BATCH_SIZE,
            "gemini_calls": 0,
            "qwen_calls": 0,
            "threshold_fitted": False,
        },
        "taxonomy": {
            "hypothesis_template": HYPOTHESIS_TEMPLATE,
            "answer_types": [
                {"key": key, "description": description}
                for key, description in ANSWER_TYPES
            ],
            "allow_types": sorted(ALLOW_TYPES),
        },
        "corpus": {
            "source": "exposed_retired_v2_semantic_current_queries",
            "cases": EXPECTED_CASES,
            "allow_targets": EXPECTED_ALLOW_TARGETS,
            "veto_targets": EXPECTED_VETO_TARGETS,
            "query_text_persisted": False,
            "canonical_memory_value_persisted": False,
        },
        "inference_seconds": round(inference_seconds, 6),
        "summary": summary,
        "cases": [_public_case(result) for result in results],
    }
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print("SUMMARY:", json.dumps(summary, ensure_ascii=False))
    print(
        "DECISION:",
        json.dumps(
            {
                "promising_for_architecture_review": summary[
                    "promising_for_architecture_review"
                ],
                "phase45e_authorized": False,
            }
        ),
    )


if __name__ == "__main__":
    main()
