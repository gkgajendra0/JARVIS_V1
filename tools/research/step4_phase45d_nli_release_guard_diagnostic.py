"""Development-only multilingual NLI release-guard diagnostic for Phase 4.5D.

The harness consumes the completed structured-query planner artifact and evaluates
only rows that the existing exact-facet path released. It reconstructs exposed V2
query text transiently, builds one fixed policy hypothesis from the selected canonical
facet metadata, and asks a pinned multilingual NLI model whether that policy statement
is entailed.

This is development evidence only. The guard is veto-only, does not rerun Gemini or
Qwen, does not fit a threshold, and cannot authorize Phase 4.5E.
"""

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

MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
MODEL_REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
SOURCE_DEFAULT = Path(".step4-phase45d-v2-structured-query-planner-diagnostic-v1.json")
OUTPUT_DEFAULT = Path(".step4-phase45d-v2-nli-release-guard-diagnostic-v1.json")
SOURCE_STATUS = "DEVELOPMENT_STRUCTURED_QUERY_PLANNER_DIAGNOSTIC_COMPLETE"
RESULT_STATUS = "DEVELOPMENT_NLI_RELEASE_GUARD_DIAGNOSTIC_COMPLETE"
EXPECTED_SOURCE_CASES = 45
EXPECTED_SOURCE_RELEASES = 16
EXPECTED_SOURCE_CORRECT_RELEASES = 10
EXPECTED_SOURCE_FALSE_RELEASES = 6
EXPECTED_TARGET_RELEASES = 12
EXPECTED_TARGET_ABSTAINS = 33
MAX_LENGTH = 256
BATCH_SIZE = 16
LABELS = ("entailment", "neutral", "contradiction")
POLICY_HYPOTHESIS_TEMPLATE = (
    "The user's question can be answered solely by the current recorded "
    "{relation} for {subject}."
)


@dataclass(frozen=True, slots=True)
class NliGuardCase:
    case_id: str
    language: str
    category: str
    source_correct_release: bool
    proposed_subject: str
    proposed_predicate: str
    top_label: str
    entailment: float
    neutral: float
    contradiction: float
    guard_allow: bool


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return payload


def _require_int(mapping: dict[str, Any], key: str, expected: int) -> None:
    actual = mapping.get(key)
    if actual != expected:
        raise RuntimeError(f"source {key} changed: {actual!r} != {expected}")


def select_source_releases(source: dict[str, Any]) -> list[dict[str, Any]]:
    if source.get("status") != SOURCE_STATUS:
        raise RuntimeError(
            f"unexpected source status: {source.get('status')!r} != {SOURCE_STATUS!r}"
        )
    if source.get("development_only") is not True:
        raise RuntimeError("source artifact must remain development-only")
    if source.get("acceptance_evidence") is not False:
        raise RuntimeError("source artifact must not be acceptance evidence")
    if source.get("phase45e_authorized") is not False:
        raise RuntimeError("source artifact must not authorize Phase 4.5E")

    summary = source.get("summary")
    if not isinstance(summary, dict):
        raise TypeError("source summary must be an object")
    _require_int(summary, "cases", EXPECTED_SOURCE_CASES)
    _require_int(summary, "released_cases", EXPECTED_SOURCE_RELEASES)
    _require_int(summary, "tp_exact_release", EXPECTED_SOURCE_CORRECT_RELEASES)
    _require_int(summary, "fp_or_wrong_release", EXPECTED_SOURCE_FALSE_RELEASES)
    _require_int(summary, "target_release_cases", EXPECTED_TARGET_RELEASES)
    _require_int(summary, "target_abstain_cases", EXPECTED_TARGET_ABSTAINS)

    cases = source.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_SOURCE_CASES:
        raise RuntimeError("source cases must contain the frozen 45 diagnostic rows")
    releases = [
        item
        for item in cases
        if isinstance(item, dict) and item.get("final_disposition") == "release"
    ]
    if len(releases) != EXPECTED_SOURCE_RELEASES:
        raise RuntimeError(
            "source released-row count changed: "
            f"{len(releases)} != {EXPECTED_SOURCE_RELEASES}"
        )

    correct = sum(_source_release_is_correct(item) for item in releases)
    if correct != EXPECTED_SOURCE_CORRECT_RELEASES:
        raise RuntimeError(
            "source correct-release count changed: "
            f"{correct} != {EXPECTED_SOURCE_CORRECT_RELEASES}"
        )
    if len(releases) - correct != EXPECTED_SOURCE_FALSE_RELEASES:
        raise RuntimeError("source false-release count changed")

    case_ids = [str(item.get("case_id")) for item in releases]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("source released case IDs must be unique")
    return sorted(releases, key=lambda item: str(item["case_id"]))


def _source_release_is_correct(item: dict[str, Any]) -> bool:
    return (
        item.get("target_label") == "release"
        and item.get("expected_memory_id") is not None
        and item.get("released_memory_id") == item.get("expected_memory_id")
    )


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


def _relation_by_predicate() -> dict[str, str]:
    values: dict[str, set[str]] = {}
    for fact in v2_cases.CURRENT_FACTS:
        values.setdefault(fact.predicate, set()).add(fact.relation_en)
    result: dict[str, str] = {}
    for predicate, relations in values.items():
        if len(relations) != 1:
            raise RuntimeError(
                f"V2 predicate must map to one relation surface: {predicate}"
            )
        result[predicate] = next(iter(relations))
    return result


def policy_hypothesis(*, subject: str, predicate: str) -> str:
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be non-empty")
    if not isinstance(predicate, str) or not predicate.strip():
        raise ValueError("predicate must be non-empty")
    relation = _relation_by_predicate().get(predicate.strip())
    if relation is None:
        raise RuntimeError(f"selected predicate is not a frozen V2 current fact: {predicate}")
    return POLICY_HYPOTHESIS_TEMPLATE.format(
        relation=relation,
        subject=subject.strip(),
    )


def build_inference_pairs(
    releases: list[dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    query_map = _query_by_case_id()
    pairs: list[tuple[str, str, dict[str, Any]]] = []
    for item in releases:
        case_id = str(item["case_id"])
        query = query_map.get(case_id)
        if query is None:
            raise RuntimeError(f"source case absent from frozen V2 corpus: {case_id}")
        subject = item.get("proposed_subject")
        predicate = item.get("proposed_predicate")
        if not isinstance(subject, str) or not subject.strip():
            raise RuntimeError(f"released case lacks proposed subject: {case_id}")
        if not isinstance(predicate, str) or not predicate.strip():
            raise RuntimeError(f"released case lacks proposed predicate: {case_id}")
        hypothesis = policy_hypothesis(subject=subject, predicate=predicate)
        pairs.append((query, hypothesis, item))
    return pairs


def _score_pairs(
    pairs: list[tuple[str, str, dict[str, Any]]],
    *,
    device: str,
) -> list[tuple[float, float, float]]:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    normalized_device = device.strip().lower()
    if normalized_device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    if normalized_device not in {"cuda", "cpu"}:
        raise ValueError("device must be 'cuda' or 'cpu'")

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
    label2id = {str(key).casefold(): int(value) for key, value in model.config.label2id.items()}
    expected = {"entailment": 0, "neutral": 1, "contradiction": 2}
    if label2id != expected:
        raise RuntimeError(f"unexpected pinned NLI label mapping: {label2id!r}")

    target = torch.device(normalized_device)
    model = model.to(device=target, dtype=torch.float32)
    model.eval()

    scores: list[tuple[float, float, float]] = []
    for start in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[start : start + BATCH_SIZE]
        encoded = tokenizer(
            [query for query, _, _ in batch],
            [hypothesis for _, hypothesis, _ in batch],
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        encoded = {name: value.to(target) for name, value in encoded.items()}
        with torch.inference_mode():
            logits = model(**encoded).logits.float().cpu()
        probabilities = torch.softmax(logits, dim=-1).tolist()
        for probability in probabilities:
            if len(probability) != 3:
                raise RuntimeError("pinned NLI model must return exactly three labels")
            scores.append(
                (
                    float(probability[0]),
                    float(probability[1]),
                    float(probability[2]),
                )
            )
    if len(scores) != len(pairs):
        raise RuntimeError("NLI score count does not match inference pair count")
    return scores


def evaluate(
    releases: list[dict[str, Any]],
    scores: list[tuple[float, float, float]],
) -> list[NliGuardCase]:
    if len(releases) != len(scores):
        raise ValueError("release rows and NLI scores must have equal length")
    results: list[NliGuardCase] = []
    for item, score in zip(releases, scores, strict=True):
        entailment, neutral, contradiction = score
        top_index = max(range(3), key=lambda index: score[index])
        top_label = LABELS[top_index]
        results.append(
            NliGuardCase(
                case_id=str(item["case_id"]),
                language=str(item["language"]),
                category=str(item["category"]),
                source_correct_release=_source_release_is_correct(item),
                proposed_subject=str(item["proposed_subject"]),
                proposed_predicate=str(item["proposed_predicate"]),
                top_label=top_label,
                entailment=round(entailment, 8),
                neutral=round(neutral, 8),
                contradiction=round(contradiction, 8),
                guard_allow=top_label == "entailment",
            )
        )
    return results


def _score_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": round(min(values), 8),
        "median": round(statistics.median(values), 8),
        "max": round(max(values), 8),
    }


def summarize(results: list[NliGuardCase]) -> dict[str, Any]:
    source_correct = [result for result in results if result.source_correct_release]
    source_false = [result for result in results if not result.source_correct_release]
    retained_correct = [result for result in source_correct if result.guard_allow]
    blocked_correct = [result for result in source_correct if not result.guard_allow]
    surviving_false = [result for result in source_false if result.guard_allow]
    blocked_false = [result for result in source_false if not result.guard_allow]
    guarded = [result for result in results if result.guard_allow]

    if len(source_correct) != EXPECTED_SOURCE_CORRECT_RELEASES:
        raise RuntimeError("evaluated source-correct release count changed")
    if len(source_false) != EXPECTED_SOURCE_FALSE_RELEASES:
        raise RuntimeError("evaluated source-false release count changed")

    by_language: dict[str, dict[str, int | float]] = {}
    frozen_expected = {"en": 4, "hi": 3, "hinglish": 3}
    for language, expected_total in frozen_expected.items():
        rows = [result for result in source_correct if result.language == language]
        retained = sum(result.guard_allow for result in rows)
        if len(rows) != expected_total:
            raise RuntimeError(
                f"source-correct language count changed for {language}: "
                f"{len(rows)} != {expected_total}"
            )
        by_language[language] = {
            "source_correct_releases": len(rows),
            "retained_correct_releases": retained,
            "retention": round(retained / len(rows), 6),
        }

    guarded_precision = (
        len(retained_correct) / len(guarded) if guarded else 1.0
    )
    correct_retention = len(retained_correct) / len(source_correct)
    continuation_checks = {
        "zero_surviving_false_releases": not surviving_false,
        "retain_at_least_8_of_10_correct": len(retained_correct) >= 8,
        "english_retain_at_least_3_of_4": (
            by_language["en"]["retained_correct_releases"] >= 3
        ),
        "hindi_retain_at_least_2_of_3": (
            by_language["hi"]["retained_correct_releases"] >= 2
        ),
        "hinglish_retain_at_least_2_of_3": (
            by_language["hinglish"]["retained_correct_releases"] >= 2
        ),
        "guard_is_veto_only": True,
        "query_hypothesis_and_values_not_persisted": True,
    }

    return {
        "source_release_rows": len(results),
        "source_correct_releases": len(source_correct),
        "source_false_releases": len(source_false),
        "guarded_releases": len(guarded),
        "retained_correct_releases": len(retained_correct),
        "blocked_correct_releases": len(blocked_correct),
        "surviving_false_releases": len(surviving_false),
        "blocked_false_releases": len(blocked_false),
        "guarded_precision": round(guarded_precision, 6),
        "correct_release_retention": round(correct_retention, 6),
        "by_language": by_language,
        "surviving_false_release_case_ids": [
            result.case_id for result in surviving_false
        ],
        "blocked_correct_release_case_ids": [
            result.case_id for result in blocked_correct
        ],
        "surviving_false_by_category": dict(
            sorted(Counter(result.category for result in surviving_false).items())
        ),
        "surviving_false_by_language": dict(
            sorted(Counter(result.language for result in surviving_false).items())
        ),
        "top_labels_source_correct": dict(
            sorted(Counter(result.top_label for result in source_correct).items())
        ),
        "top_labels_source_false": dict(
            sorted(Counter(result.top_label for result in source_false).items())
        ),
        "entailment_scores_source_correct": _score_summary(
            [result.entailment for result in source_correct]
        ),
        "entailment_scores_source_false": _score_summary(
            [result.entailment for result in source_false]
        ),
        "continuation_checks": continuation_checks,
        "promising_for_architecture_review": all(continuation_checks.values()),
    }


def _public_case(result: NliGuardCase) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "language": result.language,
        "category": result.category,
        "source_correct_release": result.source_correct_release,
        "proposed_subject": result.proposed_subject,
        "proposed_predicate": result.proposed_predicate,
        "top_label": result.top_label,
        "entailment": result.entailment,
        "neutral": result.neutral,
        "contradiction": result.contradiction,
        "guard_allow": result.guard_allow,
    }


def _run(*, source_path: Path, device: str) -> dict[str, Any]:
    source = _load_json(source_path)
    releases = select_source_releases(source)
    pairs = build_inference_pairs(releases)
    started = time.perf_counter()
    scores = _score_pairs(pairs, device=device)
    model_seconds = time.perf_counter() - started
    results = evaluate(releases, scores)
    summary = summarize(results)
    return {
        "status": RESULT_STATUS,
        "purpose": (
            "Evaluate a veto-only multilingual NLI question-focus guard over exact "
            "canonical memory releases already proposed by the structured planner"
        ),
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "phase45e_authorized": False,
        "source": {
            "artifact": source_path.name,
            "status": SOURCE_STATUS,
            "evaluated_population": "source rows with final_disposition=release",
            "expected_release_rows": EXPECTED_SOURCE_RELEASES,
        },
        "model": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "task": "multilingual_natural_language_inference",
            "device": device,
            "dtype": "float32",
            "max_length": MAX_LENGTH,
            "batch_size": BATCH_SIZE,
            "label_order": list(LABELS),
            "decision_rule": "argmax_is_entailment",
            "threshold_fitted": False,
            "model_inference_seconds": round(model_seconds, 6),
        },
        "guard_contract": {
            "veto_only": True,
            "can_select_memory": False,
            "can_create_truth": False,
            "can_modify_eligibility": False,
            "canonical_memory_value_injected": False,
            "query_text_persisted": False,
            "hypothesis_text_persisted": False,
            "gemini_rerun": False,
            "qwen_invoked": False,
        },
        "summary": summary,
        "cases": [_public_case(result) for result in results],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE_DEFAULT))
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source_path = Path(args.source)
    output_path = Path(args.output)
    if not source_path.exists():
        raise RuntimeError(f"required planner diagnostic artifact is missing: {source_path}")
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing development diagnostic: {output_path}"
        )

    result = _run(source_path=source_path, device=str(args.device))
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", result["status"])
    print("SUMMARY:", json.dumps(result["summary"], ensure_ascii=False))
    print(
        "DECISION:",
        json.dumps(
            {
                "promising_for_architecture_review": result["summary"][
                    "promising_for_architecture_review"
                ],
                "phase45e_authorized": False,
            }
        ),
    )


if __name__ == "__main__":
    main()
