"""Offline development benchmark for *shadow-only* Step-4 memory decisions.

No providers, model downloads, database connection, mutation or context injection.
The included authored examples are development fixtures, NOT a blind or
independently labelled acceptance corpus. Challenger outputs are optional and
must be generated separately; the harness never pretends to run LangMem/JEV.
Run: python tools/research/step4_memory_shadow_benchmark.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jarvis.memory.candidates import (  # noqa: E402
    MemoryCandidateDisposition,
    MemoryCandidatePolicy,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.decision_shadow import (  # noqa: E402
    CandidateShadowInput,
    ContextShadowEvidence,
    ContextShadowDisposition,
    ContextUtilitySignal,
    assess_candidate_shadow,
    assess_context_shadow,
)
from jarvis.memory.types import (  # noqa: E402
    AssertionState,
    AuthorityClass,
    MemorySourceClass,
    Sensitivity,
)

DEFAULT_CASES = ROOT / "tools/research/step4_memory_shadow_development_cases_v1.json"
LANGUAGES = frozenset({"en", "hi", "hinglish"})
CANDIDATE_LABELS = frozenset(
    {"skip", "review", "conflict_review", "duplicate"}
)
UTILITY_LABELS = frozenset(
    {"essential", "helpful", "unnecessary", "steering_risk"}
)


def load_cases(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("expected schema_version=1 corpus object")
    if data.get("purpose") != "development_only":
        raise ValueError("acceptance or unlabelled corpora must not use this harness")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("each case needs an id")
        case_id = case["id"]
        if not case_id or case_id in seen:
            raise ValueError("empty or duplicate case id")
        seen.add(case_id)
        if case.get("language") not in LANGUAGES:
            raise ValueError(f"{case_id}: invalid language")
        if case.get("kind") == "candidate":
            if case.get("expected") not in CANDIDATE_LABELS:
                raise ValueError(f"{case_id}: unknown candidate label")
            if not isinstance(case.get("proposal"), dict):
                raise ValueError(f"{case_id}: missing candidate proposal")
        elif case.get("kind") == "context":
            if case.get("expected") not in UTILITY_LABELS:
                raise ValueError(f"{case_id}: unknown utility label")
            if not isinstance(case.get("metadata"), dict):
                raise ValueError(f"{case_id}: missing context metadata")
        else:
            raise ValueError(f"{case_id}: invalid kind")
    return data, hashlib.sha256(raw).hexdigest()


def load_challenger(
    path: Path, corpus: dict[str, Any]
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Read already-produced labels without invoking any provider."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("challenger needs schema_version=1")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("challenger needs a name")
    if name in {"incumbent_policy", "shadow_review", "no_memory", "scope_probe"}:
        raise ValueError("reserved challenger name")
    candidate_predictions = data.get("candidate_predictions", {})
    context_signals = data.get("context_signals", {})
    if not isinstance(candidate_predictions, dict) or not isinstance(
        context_signals, dict
    ):
        raise ValueError("challenger outputs must be keyed objects")
    kinds = {c["id"]: c["kind"] for c in corpus["cases"]}
    for case_id, result in candidate_predictions.items():
        if kinds.get(case_id) != "candidate" or result not in CANDIDATE_LABELS:
            raise ValueError("invalid challenger candidate output")
    for case_id, result in context_signals.items():
        if kinds.get(case_id) != "context" or result not in (
            {v.value for v in ContextUtilitySignal}
        ):
            raise ValueError("invalid challenger context output")
    return name, candidate_predictions, context_signals


def _candidate_input(case: dict[str, Any]) -> CandidateShadowInput:
    return CandidateShadowInput(
        proposal=MemoryExtractionProposal.model_validate(case["proposal"]),
        source_class=MemorySourceClass(
            case.get("source_class", MemorySourceClass.OWNER_DIRECT.value)
        ),
        accepted_user_turn=case.get("accepted_user_turn", True),
        current_exact_value=case.get("current_exact_value"),
    )


def _incumbent_candidate(evidence: CandidateShadowInput) -> str:
    """Approximate existing *post-extraction* quarantine policy, not extraction.

    The production coordinator already blocks non-owner sources and known
    secrets before provider extraction; it never performs an automatic write.
    """

    if not evidence.accepted_user_turn or evidence.source_class is not (
        MemorySourceClass.OWNER_DIRECT
    ):
        return "skip"
    proposal = evidence.proposal
    if proposal.sensitivity is MemoryExtractionSensitivity.SECRET:
        return "skip"
    decision = MemoryCandidatePolicy().evaluate(proposal)
    return (
        "review"
        if decision.disposition is MemoryCandidateDisposition.QUARANTINE
        else "skip"
    )


def _context_input(
    case: dict[str, Any], signal: ContextUtilitySignal
) -> ContextShadowEvidence:
    m = case["metadata"]
    return ContextShadowEvidence(
        authority=AuthorityClass(m["authority"]),
        source=MemorySourceClass(m["source"]),
        sensitivity=Sensitivity(m["sensitivity"]),
        state=AssertionState(m["state"]),
        canonical_source_ref=m.get("canonical_source_ref"),
        memory_scope=m.get("memory_scope"),
        current_task_scope=m.get("current_task_scope"),
        task_grounded_in_current_turn=m["task_grounded_in_current_turn"],
        conflicts_with_current_turn=m["conflicts_with_current_turn"],
        utility_signal=signal,
    )


def _score_candidate(gold: str, predicted: str) -> dict[str, int]:
    return {
        "correct": int(gold == predicted),
        "over_review": int(gold == "skip" and predicted != "skip"),
        "missed_review": int(gold != "skip" and predicted == "skip"),
    }


def _score_context(gold: str, measured: bool) -> dict[str, int]:
    beneficial = gold in {"essential", "helpful"}
    return {
        "true_useful": int(beneficial and measured),
        "missed_useful": int(beneficial and not measured),
        "unnecessary_influence": int(gold == "unnecessary" and measured),
        "unsafe_steering_influence": int(gold == "steering_risk" and measured),
    }


def evaluate(
    corpus: dict[str, Any],
    challenger: tuple[str, dict[str, str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Deterministic offline scoring, with no user-memory value in output."""

    candidate_scores: dict[str, Counter[str]] = {
        "incumbent_policy": Counter(),
        "shadow_review": Counter(),
    }
    context_scores: dict[str, Counter[str]] = {
        "no_memory": Counter(),
        "scope_probe": Counter(),
    }
    if challenger:
        candidate_scores[challenger[0]] = Counter()
        context_scores[challenger[0]] = Counter()
    counts: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    for case in corpus["cases"]:
        counts[case["kind"]] += 1
        languages[case["language"]] += 1
        gold = case["expected"]
        if case["kind"] == "candidate":
            evidence = _candidate_input(case)
            predictions = {
                "incumbent_policy": _incumbent_candidate(evidence),
                "shadow_review": assess_candidate_shadow(evidence).disposition.value,
            }
            if challenger:
                predicted = challenger[1].get(case["id"])
                if predicted is not None:
                    predictions[challenger[0]] = predicted
            for name, predicted in predictions.items():
                candidate_scores[name].update(_score_candidate(gold, predicted))
                candidate_scores[name]["evaluated"] += 1
        else:
            candidates = {"no_memory": False}
            # Deliberately optimistic stress probe; HELPFUL is NOT inferred or
            # proven, and this method is never approved to inject any memory.
            candidate = _context_input(case, ContextUtilitySignal.HELPFUL)
            candidates["scope_probe"] = (
                assess_context_shadow(candidate).disposition
                is ContextShadowDisposition.MEASURE_ONLY
            )
            if challenger:
                signal = challenger[2].get(case["id"])
                if signal is not None:
                    candidates[challenger[0]] = (
                        assess_context_shadow(
                            _context_input(case, ContextUtilitySignal(signal))
                        ).disposition
                        is ContextShadowDisposition.MEASURE_ONLY
                    )
            for name, measured in candidates.items():
                context_scores[name].update(_score_context(gold, measured))
                context_scores[name]["evaluated"] += 1
    return {
        "acceptance_status": "NOT_ACCEPTANCE_DEVELOPMENT_FIXTURES",
        "benchmark_scope": (
            "Post-extraction candidate policy and metadata-only context "
            "eligibility; not live model extraction, end-to-end answer utility, "
            "independently labelled blind accuracy, or protected-main promotion"
        ),
        "counts": dict(counts),
        "language_counts": dict(languages),
        "candidate_results": {
            key: dict(scores) for key, scores in candidate_scores.items()
        },
        "context_results": {
            key: dict(scores) for key, scores in context_scores.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--unlabeled-view",
        action="store_true",
        help="Export case input without gold labels for offline challenger scoring.",
    )
    parser.add_argument(
        "--challenger",
        type=Path,
        default=None,
        help="Offline JSON containing external predictions; no model is called.",
    )
    args = parser.parse_args()
    cases, digest = load_cases(args.cases)
    if args.unlabeled_view:
        if args.challenger is not None:
            parser.error("--unlabeled-view cannot be combined with --challenger")
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "corpus_sha256": digest,
                    "cases": [
                        {key: value for key, value in case.items() if key != "expected"}
                        for case in cases["cases"]
                    ],
                },
                sort_keys=True,
                indent=2,
            )
        )
        return
    challenger = load_challenger(args.challenger, cases) if args.challenger else None
    report = evaluate(cases, challenger)
    report["corpus_sha256"] = digest
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
