"""Three-call maximum synthetic Gemini smoke test for Step-4 contextual memory.

This is a *model-detection smoke*, not a new Qwen/retrieval benchmark or
blind accuracy acceptance. It exercises existing contextual Gemini
Interactions structured-output adapter with a small fixed synthetic corpus.

Default: zero requests. Live execution requires BOTH
  --allow-three-calls --confirmed-free-tier
and GOOGLE_API_KEY set to a verified **Free** Gemini API project.

NO owner memory, user file, database, service, LangMem, Hindsight, JEV,
token log, paid fallback, retry, model switch or admission of any kind.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
)
from jarvis.memory.contextual_extractors import ContextualGeminiMemoryExtractor

MODEL_ID = "gemini-3.5-flash-lite"
MAX_PROVIDER_CALLS = 3
DELAY_BETWEEN_CALLS_SECONDS = 65


@dataclass(frozen=True, slots=True)
class SyntheticCase:
    case_id: str
    language: str
    current_turn: str
    previous_user_turns: tuple[str, ...]
    verified_memories: tuple[tuple[str, str], ...]
    expected_intent: MemoryExtractionIntent | None
    expected_type: MemoryCandidateType | None
    expected_predicate: str | None
    required_value_fragments: tuple[str, ...] = ()


# Only fictional project/workshop facts; unrelated to the owner's actual work
# and different from the previously exposed 18-case development fixture.
SYNTHETIC_CASES = (
    SyntheticCase(
        case_id="synth-en-correction",
        language="en",
        previous_user_turns=(
            "For my fictional Atlas workshop, I told you my weekly recap format is video.",
        ),
        current_turn=(
            "I was mistaken about the Atlas workshop recap format. "
            "It should be a written checklist, not a video."
        ),
        verified_memories=(("weekly_workshop_recap_format", "video"),),
        expected_intent=MemoryExtractionIntent.CORRECTION,
        expected_type=MemoryCandidateType.FACT_CORRECTION,
        expected_predicate="weekly_workshop_recap_format",
        required_value_fragments=("checklist",),
    ),
    SyntheticCase(
        case_id="synth-hi-historical-change",
        language="hi",
        previous_user_turns=(
            "मेरी काल्पनिक नील परियोजना की साप्ताहिक रिपोर्ट सोमवार को जाती थी।",
        ),
        current_turn=(
            "पहले मैं नील परियोजना की रिपोर्ट सोमवार को भेजता था, अब उसे गुरुवार को भेजता हूँ।"
        ),
        verified_memories=(("weekly_project_report_day", "Monday"),),
        expected_intent=MemoryExtractionIntent.HISTORICAL_CHANGE,
        expected_type=MemoryCandidateType.FACT_CHANGE,
        expected_predicate="weekly_project_report_day",
        required_value_fragments=("गुरुवार", "thursday"),
    ),
    SyntheticCase(
        case_id="synth-hinglish-ambiguous",
        language="hinglish",
        previous_user_turns=(
            "Kal fictional workshop ka day Saturday bataya tha.",
            "Workshop room bhi hall B bataya tha.",
        ),
        current_turn=(
            "Kal workshop ke baare mein jo bola tha woh galat tha, "
            "lekin abhi naya detail final nahi hua."
        ),
        verified_memories=(
            ("workshop_day", "Saturday"),
            ("workshop_room", "Hall B"),
        ),
        expected_intent=None,
        expected_type=None,
        expected_predicate=None,
    ),
)
assert len(SYNTHETIC_CASES) == MAX_PROVIDER_CALLS


def _case_context(case: SyntheticCase) -> str:
    return json.dumps(
        {
            "recent_accepted_owner_turns": case.previous_user_turns,
            "verified_current_memory_candidates": [
                {"predicate": predicate, "current_value": value}
                for predicate, value in case.verified_memories
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _score(case: SyntheticCase, proposal: MemoryExtractionProposal) -> dict[str, Any]:
    # Only emit classification, booleans and reason codes; never extracted values.
    if case.expected_intent is None:
        abstained = proposal.intent in {
            MemoryExtractionIntent.NONE,
            MemoryExtractionIntent.TRANSIENT,
        }
        # A bare reference to "that" is not proof of any target. A typed
        # unresolved correction is also acceptable *only* if no predicate or
        # corrected value is invented.
        unresolved = (
            proposal.intent is MemoryExtractionIntent.CORRECTION
            and not proposal.predicate
            and not proposal.value
        )
        passed = abstained or unresolved
        return {
            "case_id": case.case_id,
            "language": case.language,
            "predicted_intent": proposal.intent.value,
            "predicted_type": proposal.candidate_type.value,
            "safe_ambiguity_handling": passed,
            "pass": passed,
        }

    correct_intent = proposal.intent is case.expected_intent
    correct_type = proposal.candidate_type is case.expected_type
    correct_target = proposal.predicate == case.expected_predicate
    value_text = (proposal.value or "").casefold()
    value_supported = any(
        fragment.casefold() in value_text for fragment in case.required_value_fragments
    )
    passed = correct_intent and correct_type and correct_target and value_supported
    return {
        "case_id": case.case_id,
        "language": case.language,
        "predicted_intent": proposal.intent.value,
        "predicted_type": proposal.candidate_type.value,
        "intent_matched": correct_intent,
        "type_matched": correct_type,
        "target_matched": correct_target,
        "value_grounded": value_supported,
        "pass": passed,
    }


async def run_smoke(
    extractor: Any,
    *,
    cases: Sequence[SyntheticCase] = SYNTHETIC_CASES,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    """Sequential, no retry or fallback. Abort after *any* provider failure."""

    if len(cases) != MAX_PROVIDER_CALLS or tuple(cases) != SYNTHETIC_CASES:
        raise ValueError("only the three pinned synthetic cases are permitted")
    results: list[dict[str, Any]] = []
    invoked = 0
    for i, case in enumerate(cases):
        if i:
            await sleep(DELAY_BETWEEN_CALLS_SECONDS)
        # Increment BEFORE the request: errors still consume an attempt.
        invoked += 1
        try:
            proposal = await extractor.extract_contextual(
                text=case.current_turn,
                context=_case_context(case),
            )
            if not isinstance(proposal, MemoryExtractionProposal):
                raise TypeError("invalid structured proposal")
        except Exception as exc:  # noqa: BLE001 - sanitize any provider error
            results.append(
                {
                    "case_id": case.case_id,
                    "language": case.language,
                    "status": "provider_failure_stop",
                    "error_class": type(exc).__name__,
                }
            )
            break
        results.append({"status": "completed", **_score(case, proposal)})

    return {
        "schema_version": 1,
        "model": MODEL_ID,
        "synthetic_only": True,
        "development_smoke_only": True,
        "provider_calls_attempted": invoked,
        "provider_calls_max": MAX_PROVIDER_CALLS,
        "no_retries": True,
        "no_durable_writes": True,
        "cases": results,
    }


async def _run_live() -> dict[str, Any]:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key or not key.strip():
        raise RuntimeError("GOOGLE_API_KEY environment variable is required")

    # This must be an SDK instance against an already VERIFIED FREE-TIER key.
    # We never discover/pay for a billing tier or silently switch models.
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    try:
        extractor = ContextualGeminiMemoryExtractor(client=client, model=MODEL_ID)
        return await run_smoke(extractor)
    finally:
        try:
            await client.aio.aclose()
        finally:
            client.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-three-calls", action="store_true")
    parser.add_argument("--confirmed-free-tier", action="store_true")
    args = parser.parse_args(argv)

    if not args.allow_three_calls:
        print(
            json.dumps(
                {
                    "status": "dry_run_no_provider_calls",
                    "model": MODEL_ID,
                    "pinned_synthetic_cases": [
                        {"case_id": c.case_id, "language": c.language}
                        for c in SYNTHETIC_CASES
                    ],
                    "max_calls": MAX_PROVIDER_CALLS,
                },
                sort_keys=True,
                indent=2,
            )
        )
        return
    if not args.confirmed_free_tier:
        parser.error(
            "Verify that this API key's project shows Free on the Google "
            "AI Studio Projects page, then pass --confirmed-free-tier. "
            "Do not use a key linked to a paid project."
        )
    if not os.environ.get("GOOGLE_API_KEY"):
        parser.error("GOOGLE_API_KEY must be set privately in the process environment")
    result = asyncio.run(_run_live())
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
