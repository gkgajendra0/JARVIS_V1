"""Research-only Step 4 production-contract memory extraction bake-off.

The provider side of this harness intentionally exercises the same Pydantic
``MemoryExtractionProposal`` schema and the same system prompt used by the
production Phase-4.4 extractor adapters. The corpus is partitioned through the
same deterministic gates that run before production extraction:

1. only canonical direct-user content is eligible;
2. Phase-4.3 explicit memory controls are handled before extraction;
3. locally recognizable credentials/secrets are rejected before extraction;
4. only the remaining accepted USER utterances reach the provider.

Non-user corpus entries remain adversarial evidence, but they are validated at
the deterministic pre-provider boundary rather than asking an LLM to decide
whether assistant/web/email/file content is trustworthy.

This harness never writes canonical memory. API requests use ``store=False``.

Suggested isolated environment::

    py -3.11 -m venv .step4-extraction-venv
    .\\.step4-extraction-venv\\Scripts\\python.exe -m pip install -U pip
    .\\.step4-extraction-venv\\Scripts\\python.exe -m pip install \
        -r tools\\research\\requirements-step4-extraction.txt

Run one provider at a time if desired::

    .\\.step4-extraction-venv\\Scripts\\python.exe \
        tools\\research\\step4_memory_extraction_bakeoff.py --providers openai

    .\\.step4-extraction-venv\\Scripts\\python.exe \
        tools\\research\\step4_memory_extraction_bakeoff.py --providers gemini

Environment variables:

* ``OPENAI_API_KEY``
* ``GEMINI_API_KEY`` (``GOOGLE_API_KEY`` is accepted as a fallback)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from jarvis.memory.candidates import (  # noqa: E402
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.explicit import (  # noqa: E402
    MemorySecretRejectedError,
    is_explicit_memory_control_text,
    reject_prohibited_secret,
)
from jarvis.memory.extractors import MEMORY_EXTRACTION_SYSTEM_PROMPT  # noqa: E402

DIRECT_USER_SOURCE = "direct_user"
NON_USER_EXPECTED_INTENT = MemoryExtractionIntent.UNTRUSTED.value
NON_USER_EXPECTED_TYPE = MemoryCandidateType.NONE.value


class ProviderCall(BaseModel):
    extraction: MemoryExtractionProposal | None = None
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CorpusPartition:
    provider_cases: tuple[dict[str, Any], ...]
    non_user_case_ids: tuple[str, ...]
    explicit_control_case_ids: tuple[str, ...]
    local_secret_case_ids: tuple[str, ...]


def _load_cases(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise TypeError("case corpus must be a JSON list")
    return value


def _validate_corpus_taxonomy(cases: list[dict[str, Any]]) -> None:
    """Fail closed when the research corpus drifts from production taxonomy."""

    valid_intents = {item.value for item in MemoryExtractionIntent}
    valid_types = {item.value for item in MemoryCandidateType}
    problems: list[str] = []

    for case in cases:
        case_id = str(case.get("id", "<missing-id>"))
        expected = case.get("expected")
        if not isinstance(expected, dict):
            problems.append(f"{case_id}: expected must be an object")
            continue

        intent = expected.get("intent")
        candidate_type = expected.get("candidate_type")
        durable = expected.get("durable_candidate")
        if intent not in valid_intents:
            problems.append(f"{case_id}: unsupported intent {intent!r}")
        if candidate_type not in valid_types:
            problems.append(f"{case_id}: unsupported candidate_type {candidate_type!r}")
        if not isinstance(durable, bool):
            problems.append(f"{case_id}: durable_candidate must be boolean")

        if case.get("source_class") == DIRECT_USER_SOURCE:
            continue
        if (
            intent != NON_USER_EXPECTED_INTENT
            or candidate_type != NON_USER_EXPECTED_TYPE
            or durable is not False
        ):
            problems.append(
                f"{case_id}: non-user source must be expected as "
                "untrusted/none/non-durable"
            )

    if problems:
        raise ValueError("; ".join(problems))


def _partition_cases(cases: list[dict[str, Any]]) -> CorpusPartition:
    """Mirror the deterministic gates before MemoryCandidateExtractor.extract()."""

    provider_cases: list[dict[str, Any]] = []
    non_user: list[str] = []
    explicit_controls: list[str] = []
    local_secrets: list[str] = []

    for case in cases:
        case_id = str(case["id"])
        if case.get("source_class") != DIRECT_USER_SOURCE:
            non_user.append(case_id)
            continue

        text = str(case["input"])
        if is_explicit_memory_control_text(text):
            explicit_controls.append(case_id)
            continue

        try:
            reject_prohibited_secret(
                predicate="candidate_extraction",
                value=text,
            )
        except MemorySecretRejectedError:
            local_secrets.append(case_id)
            continue

        provider_cases.append(case)

    return CorpusPartition(
        provider_cases=tuple(provider_cases),
        non_user_case_ids=tuple(non_user),
        explicit_control_case_ids=tuple(explicit_controls),
        local_secret_case_ids=tuple(local_secrets),
    )


def _extract_openai_parsed(response: Any) -> MemoryExtractionProposal:
    direct = getattr(response, "output_parsed", None)
    if isinstance(direct, MemoryExtractionProposal):
        return direct

    for output in getattr(response, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for item in getattr(output, "content", []) or []:
            parsed = getattr(item, "parsed", None)
            if isinstance(parsed, MemoryExtractionProposal):
                return parsed

    raise RuntimeError("OpenAI response contained no parsed MemoryExtractionProposal")


def _call_openai(client: Any, model: str, case: dict[str, Any]) -> ProviderCall:
    started = time.perf_counter_ns()
    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": MEMORY_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": case["input"]},
            ],
            text_format=MemoryExtractionProposal,
            store=False,
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        extraction = _extract_openai_parsed(response)
        usage = getattr(response, "usage", None)
        return ProviderCall(
            extraction=extraction,
            latency_ms=elapsed,
            input_tokens=(
                int(getattr(usage, "input_tokens", 0) or 0) if usage else None
            ),
            output_tokens=(
                int(getattr(usage, "output_tokens", 0) or 0) if usage else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 - provider failures are bake-off evidence
        return ProviderCall(
            latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            error=f"{type(exc).__name__}: {exc}",
        )


def _call_gemini(client: Any, model: str, case: dict[str, Any]) -> ProviderCall:
    started = time.perf_counter_ns()
    try:
        interaction = client.interactions.create(
            model=model,
            input=case["input"],
            system_instruction=MEMORY_EXTRACTION_SYSTEM_PROMPT,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": MemoryExtractionProposal.model_json_schema(),
            },
            store=False,
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        extraction = MemoryExtractionProposal.model_validate_json(
            interaction.output_text
        )
        usage = getattr(interaction, "usage", None)
        return ProviderCall(
            extraction=extraction,
            latency_ms=elapsed,
            input_tokens=(
                int(getattr(usage, "total_input_tokens", 0) or 0) if usage else None
            ),
            output_tokens=(
                int(getattr(usage, "total_output_tokens", 0) or 0) if usage else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 - provider failures are bake-off evidence
        return ProviderCall(
            latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            error=f"{type(exc).__name__}: {exc}",
        )


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().replace("_", " ").replace(".", " ").split())


def _hint_match(actual: str | None, hint: str | None) -> bool | None:
    if hint is None:
        return None
    left, right = _norm(actual), _norm(hint)
    return bool(left and right and (left in right or right in left))


def _percentile(samples: list[float], fraction: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _score_provider(
    provider: str,
    model: str,
    cases: list[dict[str, Any]],
    calls: list[ProviderCall],
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    valid_pairs: list[tuple[dict[str, Any], MemoryExtractionProposal]] = []
    latency = [call.latency_ms for call in calls]

    total_input_tokens = 0
    total_output_tokens = 0
    token_usage_complete = True

    for case, call in zip(cases, calls, strict=True):
        expected = case["expected"]
        extraction = call.extraction
        if call.input_tokens is None or call.output_tokens is None:
            token_usage_complete = False
        else:
            total_input_tokens += call.input_tokens
            total_output_tokens += call.output_tokens

        if extraction is None:
            records[case["id"]] = {
                "language": case["language"],
                "expected": expected,
                "schema_valid": False,
                "error": call.error,
                "latency_ms": round(call.latency_ms, 4),
            }
            continue

        valid_pairs.append((case, extraction))
        actual = extraction.model_dump(mode="json")
        intent_ok = extraction.intent.value == expected["intent"]
        type_ok = extraction.candidate_type.value == expected["candidate_type"]
        durable_ok = extraction.durable_candidate == expected["durable_candidate"]

        hint_checks = {
            "subject": _hint_match(extraction.subject, expected.get("subject")),
            "predicate": _hint_match(
                extraction.predicate, expected.get("predicate_hint")
            ),
            "value": _hint_match(extraction.value, expected.get("value_hint")),
        }

        records[case["id"]] = {
            "language": case["language"],
            "expected": expected,
            "actual": actual,
            "schema_valid": True,
            "intent_match": intent_ok,
            "candidate_type_match": type_ok,
            "durable_match": durable_ok,
            "core_exact": intent_ok and type_ok and durable_ok,
            "hint_matches": hint_checks,
            "latency_ms": round(call.latency_ms, 4),
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
        }

    def count(predicate: Any) -> int:
        return sum(1 for case, ext in valid_pairs if predicate(case, ext))

    case_count = len(cases)
    valid_count = len(valid_pairs)
    intent_matches = count(lambda c, e: e.intent.value == c["expected"]["intent"])
    type_matches = count(
        lambda c, e: e.candidate_type.value == c["expected"]["candidate_type"]
    )
    durable_matches = count(
        lambda c, e: e.durable_candidate == c["expected"]["durable_candidate"]
    )
    core_exact = count(
        lambda c, e: (
            e.intent.value == c["expected"]["intent"]
            and e.candidate_type.value == c["expected"]["candidate_type"]
            and e.durable_candidate == c["expected"]["durable_candidate"]
        )
    )

    expected_non_durable = [
        (case, ext)
        for case, ext in valid_pairs
        if not case["expected"]["durable_candidate"]
    ]
    false_durable_writes = sum(ext.durable_candidate for _, ext in expected_non_durable)

    expected_durable = [
        (case, ext)
        for case, ext in valid_pairs
        if case["expected"]["durable_candidate"]
    ]
    missed_durable = sum(not ext.durable_candidate for _, ext in expected_durable)

    secret = [
        (case, ext)
        for case, ext in valid_pairs
        if case["expected"]["candidate_type"] == MemoryCandidateType.SECRET.value
    ]
    secret_policy_hits = sum(
        ext.intent is MemoryExtractionIntent.SENSITIVE_REJECT
        and ext.candidate_type is MemoryCandidateType.SECRET
        and not ext.durable_candidate
        and ext.sensitivity is MemoryExtractionSensitivity.SECRET
        for _, ext in secret
    )

    language_breakdown: dict[str, Any] = {}
    for language in sorted({case["language"] for case in cases}):
        language_cases = [
            (case, ext) for case, ext in valid_pairs if case["language"] == language
        ]
        matches = sum(
            ext.intent.value == case["expected"]["intent"]
            and ext.candidate_type.value == case["expected"]["candidate_type"]
            and ext.durable_candidate == case["expected"]["durable_candidate"]
            for case, ext in language_cases
        )
        language_breakdown[language] = {
            "valid_cases": len(language_cases),
            "core_exact": matches,
            "core_accuracy": (
                round(matches / len(language_cases), 4) if language_cases else None
            ),
        }

    return {
        "provider": provider,
        "model": model,
        "case_count": case_count,
        "schema_valid_count": valid_count,
        "schema_failures": case_count - valid_count,
        "metrics": {
            "intent_accuracy": round(intent_matches / case_count, 4),
            "candidate_type_accuracy": round(type_matches / case_count, 4),
            "durable_flag_accuracy": round(durable_matches / case_count, 4),
            "core_exact_accuracy": round(core_exact / case_count, 4),
            "false_durable_writes": false_durable_writes,
            "false_durable_rate_among_expected_non_durable": (
                round(false_durable_writes / len(expected_non_durable), 4)
                if expected_non_durable
                else None
            ),
            "missed_durable_candidates": missed_durable,
            "secret_policy_accuracy": (
                round(secret_policy_hits / len(secret), 4) if secret else None
            ),
        },
        "language_breakdown": language_breakdown,
        "latency_ms": {
            "p50": round(statistics.median(latency), 4) if latency else None,
            "p95": round(_percentile(latency, 0.95), 4) if latency else None,
            "max": round(max(latency), 4) if latency else None,
        },
        "usage": {
            "complete": token_usage_complete,
            "input_tokens": total_input_tokens if token_usage_complete else None,
            "output_tokens": total_output_tokens if token_usage_complete else None,
        },
        "cases": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--providers",
        default="openai,gemini",
        help="Comma-separated: openai,gemini (default both)",
    )
    parser.add_argument("--openai-model", default="gpt-5.6-terra")
    parser.add_argument("--gemini-model", default="gemini-3.8-flash")
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("step4_memory_extraction_cases.json")),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Optional post-gate provider smoke-test limit.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=100,
        help="Small delay between provider calls to reduce burst-rate noise.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    providers = [value.strip() for value in args.providers.split(",") if value.strip()]
    invalid = [value for value in providers if value not in {"openai", "gemini"}]
    if invalid:
        raise SystemExit(f"unsupported providers: {invalid}")

    all_cases = _load_cases(Path(args.cases))
    _validate_corpus_taxonomy(all_cases)
    partition = _partition_cases(all_cases)
    cases = list(partition.provider_cases)
    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    if not cases:
        raise SystemExit("no cases remain after production pre-provider gates")

    results: dict[str, Any] = {}

    if "openai" in providers:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            results["openai"] = {
                "provider": "openai",
                "model": args.openai_model,
                "status": "SKIPPED",
                "reason": "OPENAI_API_KEY is not set",
            }
        else:
            from openai import OpenAI

            client = OpenAI(api_key=key)
            calls: list[ProviderCall] = []
            for index, case in enumerate(cases):
                calls.append(_call_openai(client, args.openai_model, case))
                if args.delay_ms and index + 1 < len(cases):
                    time.sleep(args.delay_ms / 1000)
            results["openai"] = _score_provider(
                "openai", args.openai_model, cases, calls
            )

    if "gemini" in providers:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            results["gemini"] = {
                "provider": "gemini",
                "model": args.gemini_model,
                "status": "SKIPPED",
                "reason": "GEMINI_API_KEY/GOOGLE_API_KEY is not set",
            }
        else:
            from google import genai

            client = genai.Client(api_key=key)
            calls = []
            for index, case in enumerate(cases):
                calls.append(_call_gemini(client, args.gemini_model, case))
                if args.delay_ms and index + 1 < len(cases):
                    time.sleep(args.delay_ms / 1000)
            results["gemini"] = _score_provider(
                "gemini", args.gemini_model, cases, calls
            )

    output = {
        "status": "PASS",
        "purpose": "research-only; candidate proposal and quarantine, no durable admission",
        "corpus_case_count": len(all_cases),
        "provider_case_count": len(cases),
        "production_contract": "jarvis.memory.candidates.MemoryExtractionProposal",
        "production_prompt": "jarvis.memory.extractors.MEMORY_EXTRACTION_SYSTEM_PROMPT",
        "requests_store": False,
        "deterministic_pre_provider_gates": {
            "non_user_source_case_ids": partition.non_user_case_ids,
            "explicit_memory_control_case_ids": partition.explicit_control_case_ids,
            "local_secret_rejection_case_ids": partition.local_secret_case_ids,
            "provider_called_for_any_gated_case": False,
        },
        "results": results,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
