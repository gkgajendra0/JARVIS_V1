"""Opt-in live model extraction bake-off for JARVIS vs LangMem.

This is a *development-only* CLI. No database writes, no memory injection.
All LLM calls require an explicit flag, use synthetic corpus only and may
consume a configured provider's quota/billing. Output contains classifications,
timings and case IDs, NEVER extracted memory values.

Examples (in isolated benchmark venv, with legitimate provider API credentials):
  python tools/research/step4_memory_model_comparators.py --backend jarvis \
      --provider gemini --model gemini-3.5-flash-lite \
      --allow-model-calls --max-cases 3
  python tools/research/step4_memory_model_comparators.py --backend langmem \
      --model google_genai:gemini-3.5-flash-lite \
      --allow-model-calls --max-cases 3

The LangMem adapter uses stateless create_memory_manager, not its store
manager. This measures extraction, NOT cross-session consolidation or full
Hindsight recall/reflect utility. Both remain unaccepted until separately run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from jarvis.memory.candidates import (
    MemoryCandidateDisposition,
    MemoryCandidatePolicy,
    MemoryExtractionProposal,
)
from jarvis.memory.decision_shadow import (
    CandidateReviewDisposition,
    CandidateShadowInput,
    assess_candidate_shadow,
)
from jarvis.memory.explicit import (
    MemorySecretRejectedError,
    is_explicit_memory_control_text,
    reject_prohibited_secret,
)
from jarvis.memory.types import MemorySourceClass
from tools.research.step4_memory_shadow_benchmark import load_cases

DEFAULT_CASES = ROOT / "tools/research/step4_memory_shadow_development_cases_v1.json"
_VALID_PREDICTIONS = frozenset(x.value for x in CandidateReviewDisposition)


def eligible_raw_turn(case: dict[str, Any]) -> bool:
    """Independent pre-provider gates; never consult case gold/proposal."""

    if case.get("kind") != "candidate":
        return False
    if not case.get("accepted_user_turn", True):
        return False
    if case.get("source_class", "owner_direct") != "owner_direct":
        return False
    utterance = case.get("utterance")
    if not isinstance(utterance, str) or not utterance.strip():
        return False
    if is_explicit_memory_control_text(utterance):
        return False
    try:
        reject_prohibited_secret(predicate="candidate_extraction", value=utterance)
    except MemorySecretRejectedError:
        return False
    return True


def project_proposal(
    proposal: MemoryExtractionProposal, case: dict[str, Any]
) -> str:
    """Projection of *actual* JARVIS model output, never an authorized write."""

    if MemoryCandidatePolicy().evaluate(proposal).disposition is (
        MemoryCandidateDisposition.DROP
    ):
        return CandidateReviewDisposition.SKIP.value
    return assess_candidate_shadow(
        CandidateShadowInput(
            proposal=proposal,
            source_class=MemorySourceClass.OWNER_DIRECT,
            accepted_user_turn=True,
            current_exact_value=case.get("current_exact_value"),
        )
    ).disposition.value


def project_triples(triples: list[tuple[str, str, str]], case: dict[str, Any]) -> str:
    """Coarse LangMem extraction proxy; cannot verify temporal correctness.

    It intentionally has no power to approve writes. Any existing-value change
    must go to conflict review; all other extracted facts go to owner review.
    """

    if not triples:
        return "skip"
    existing = case.get("current_exact_value")
    if isinstance(existing, str):
        normalized = existing.strip().casefold()
        if len(triples) == 1 and triples[0][2].strip().casefold() == normalized:
            return "duplicate"
        return "conflict_review"
    return "review"


def score_raw_candidate_predictions(
    cases: list[dict[str, Any]],
    infer: Callable[[str, dict[str, Any]], str],
) -> dict[str, Any]:
    """Run a supplied actual model adapter; no fixture-gold in model inputs."""

    predictions: dict[str, str] = {}
    timings_ms: list[float] = []
    failures: list[str] = []
    skipped = 0
    for case in cases:
        if not eligible_raw_turn(case):
            predictions[case["id"]] = "skip"
            skipped += 1
            continue
        start = time.monotonic()
        try:
            predicted = infer(case["utterance"], case)
            if predicted not in _VALID_PREDICTIONS:
                raise ValueError("adapter supplied invalid prediction")
            predictions[case["id"]] = predicted
        except Exception:
            # No provider exception text, which can contain prompt/credentials.
            failures.append(case["id"])
        else:
            timings_ms.append((time.monotonic() - start) * 1000.0)
    return {
        "candidate_predictions": predictions,
        "attempted_model_calls": len(cases) - skipped,
        "skipped_pre_provider": skipped,
        "provider_failures": len(failures),
        "failed_case_ids": failures,
        "model_call_latency_p50_ms": (
            round(statistics.median(timings_ms), 2) if timings_ms else None
        ),
        "completed_model_calls": len(timings_ms),
    }


def jarvis_model_adapter(provider: str, model: str) -> Callable:
    """Wrap already-implemented real provider extractor; never write memory."""

    from jarvis.memory.extractors import build_memory_candidate_extractor

    extractor = build_memory_candidate_extractor(provider=provider, model=model)

    def infer(text: str, case: dict[str, Any]) -> str:
        proposal = asyncio.run(extractor.extract(text=text))
        return project_proposal(proposal, case)

    return infer


def langmem_model_adapter(model: str) -> Callable:
    """Invoke the actual LangMem stateless manager, never create_store_manager."""

    from langmem import create_memory_manager
    from pydantic import BaseModel

    class Triple(BaseModel):
        subject: str
        predicate: str
        value: str

    manager = create_memory_manager(
        model,
        schemas=[Triple],
        instructions=(
            "Extract only durable, directly asserted owner facts or established "
            "preferences. Avoid speculative, transient, secret, sensitive and "
            "quoted claims. Output zero facts when nothing is suitable. "
            "Proposals are research evidence, not storage authorization."
        ),
        enable_inserts=True,
        enable_updates=False,
        enable_deletes=False,
    )

    def infer(text: str, case: dict[str, Any]) -> str:
        results = manager.invoke({"messages": [{"role": "user", "content": text}]})
        if not isinstance(results, list):
            raise TypeError("LangMem returned non-list result")
        triples = []
        for item in results:
            content = getattr(item, "content", None)
            if not isinstance(content, Triple):
                # Tool outputs without a recognized schema cannot be allowed.
                continue
            if not content.subject or not content.predicate or not content.value:
                continue
            triples.append((content.subject, content.predicate, content.value))
        return project_triples(triples, case)

    return infer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["jarvis", "langmem"], required=True)
    parser.add_argument("--provider", choices=["gemini", "openai"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--allow-model-calls", action="store_true")
    parser.add_argument("--max-cases", type=int, default=3)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()

    if not args.allow_model_calls:
        parser.error("explicit --allow-model-calls approval is required")
    if not 1 <= args.max_cases <= 100:
        parser.error("--max-cases must be 1..100")
    if args.backend == "jarvis" and not args.provider:
        parser.error("--provider is required for Jarvis adapter")
    corpus, digest = load_cases(args.cases)
    selected = [c for c in corpus["cases"] if c["kind"] == "candidate"][
        : args.max_cases
    ]
    adapter = (
        jarvis_model_adapter(args.provider, args.model)
        if args.backend == "jarvis"
        else langmem_model_adapter(args.model)
    )
    scored = score_raw_candidate_predictions(selected, adapter)
    output = {
        "schema_version": 1,
        "name": f"{args.backend}_model_extraction",
        "backend": args.backend,
        "model": args.model,
        "development_only": True,
        "no_durable_write": True,
        "corpus_sha256": digest,
        **scored,
    }
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
