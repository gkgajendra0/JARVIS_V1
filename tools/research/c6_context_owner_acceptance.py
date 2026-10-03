"""Owner-machine C6 context acceptance and bounded decision replay.

The default mode is zero-model: it reads canonical Work history, builds bounded
ContextPacks, and emits aggregate size/provenance metrics without printing raw Work
payloads. An explicit --decision-replay run may consume a small, bounded amount of the
connected ChatGPT-plan allowance to compare optimized APPLY decisions against durable
legacy SHADOW decision fingerprints. It never executes the selected Work action and
never changes production routing mode.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace

from jarvis.brain_routing.models import BrainRouteKind
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.chatgpt_plan import CHATGPT_PLAN_PROVIDER_ID, ChatGPTPlanSessionManager
from jarvis.hands.provider_adapters import (
    build_chatgpt_plan_structured_output_client,
)
from jarvis.machine_config import configured_text, load_machine_settings
from jarvis.model_routing.models import ResponseContractResult
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.provider_circuit import (
    BackgroundProviderCircuitRegistry,
    provider_circuit_key,
)
from jarvis.work.context import WorkContextAssembler, WorkContextMode
from jarvis.work.context_evaluation import (
    compare_recorded_context_decision,
    reconstruct_recorded_context_request,
)
from jarvis.work.models import WorkType
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.reasoner import (
    _work_input_payload,
    evaluate_structured_work_request,
)
from jarvis.work.store import SQLiteWorkStore, default_work_store_path

_MAX_DECISION_REPLAY_CASES = 5
_MAX_REPLAY_CANDIDATE_SCAN = 25


def _chars(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    )


def _legacy_steps(steps):
    return [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "summary": step.summary,
            "state": step.state.value,
            "input": step.input_data,
            "observation": step.observation,
            "error": step.error,
        }
        for step in steps[-12:]
    ]


def _successful_historical_attempt(
    routing_store: ModelRoutingStore,
    *,
    decision_id: str | None,
):
    """Return the exact provider/model attempt that produced the legacy decision."""

    if decision_id is None:
        return None
    valid = tuple(
        attempt
        for attempt in routing_store.list_attempts(decision_id)
        if attempt.failure_class is None
        and attempt.response_contract_result is ResponseContractResult.VALID
        and attempt.provider_id is not None
        and attempt.model_id is not None
    )
    if not valid:
        return None
    identities = {
        (attempt.target_id, attempt.provider_id, attempt.model_id) for attempt in valid
    }
    if len(identities) != 1:
        return None
    return valid[0]


def _replay_candidates(
    store: SQLiteWorkStore,
    route_store: BrainRouteStore,
    routing_store: ModelRoutingStore,
    *,
    model: str,
    limit: int,
):
    candidates = []
    stats = {
        "model_routes_seen": 0,
        "missing_decision_provenance": 0,
        "missing_context_snapshot": 0,
        "missing_route_contract_lineage": 0,
        "route_snapshot_contract_mismatch": 0,
        "missing_exact_model_lineage": 0,
        "non_chatgpt_plan_lineage": 0,
        "different_model_lineage": 0,
    }
    for work in store.list(limit=500):
        if work.work_type not in {WorkType.DEVELOPMENT, WorkType.RESEARCH}:
            continue
        steps = store.list_steps(work.work_id)
        for route in route_store.list_for_work(work.work_id):
            if route.route_kind is not BrainRouteKind.MODEL:
                continue
            stats["model_routes_seen"] += 1
            if (
                route.goal_complete is None
                or route.needs_owner is None
                or route.parameters_digest is None
            ):
                stats["missing_decision_provenance"] += 1
                continue
            snapshot = route_store.get_context_snapshot(route.route_request_id)
            if snapshot is None:
                stats["missing_context_snapshot"] += 1
                continue
            if route.reasoner_contract_digest is None:
                stats["missing_route_contract_lineage"] += 1
                continue
            snapshot_contract = (
                str(snapshot.get("reasoner_contract_digest") or "").strip().casefold()
            )
            if route.reasoner_contract_digest != snapshot_contract:
                stats["route_snapshot_contract_mismatch"] += 1
                continue
            attempt = _successful_historical_attempt(
                routing_store,
                decision_id=route.model_decision_id,
            )
            if attempt is None:
                stats["missing_exact_model_lineage"] += 1
                continue
            if attempt.provider_id != CHATGPT_PLAN_PROVIDER_ID:
                stats["non_chatgpt_plan_lineage"] += 1
                continue
            if attempt.model_id != model:
                stats["different_model_lineage"] += 1
                continue
            candidates.append(
                (
                    route.created_at_epoch,
                    work,
                    steps,
                    route,
                    snapshot,
                    attempt,
                )
            )
    candidates.sort(key=lambda item: (-float(item[0]), item[3].route_request_id))
    return tuple(candidates[:limit]), stats


async def _run_decision_replay(
    *,
    store: SQLiteWorkStore,
    route_store: BrainRouteStore,
    model: str,
    max_cases: int,
    min_equivalent_cases: int,
) -> dict[str, object]:
    routing_store = ModelRoutingStore(store)
    candidates, candidate_stats = _replay_candidates(
        store,
        route_store,
        routing_store,
        model=model,
        limit=_MAX_REPLAY_CANDIDATE_SCAN,
    )

    prepared = []
    context_drift_cases = 0
    non_reducing_cases = 0
    for (
        _created_at,
        work,
        steps,
        recorded,
        snapshot,
        historical_attempt,
    ) in candidates:
        try:
            replay = reconstruct_recorded_context_request(
                snapshot=snapshot,
                work=work,
                steps=steps,
            )
        except (TypeError, ValueError):
            context_drift_cases += 1
            continue

        legacy_payload = _work_input_payload(
            replace(replay, context_mode=WorkContextMode.SHADOW)
        )
        optimized_payload = _work_input_payload(replay)
        legacy_chars = _chars(legacy_payload)
        optimized_chars = _chars(optimized_payload)
        if optimized_chars >= legacy_chars:
            non_reducing_cases += 1
            continue

        prepared.append(
            (
                work,
                recorded,
                historical_attempt,
                replay,
                legacy_chars,
                optimized_chars,
            )
        )

    ready_by_type = {
        work_type.value: sum(1 for item in prepared if item[0].work_type is work_type)
        for work_type in (WorkType.RESEARCH, WorkType.DEVELOPMENT)
    }
    selected = []
    selected_ids: set[int] = set()

    # First guarantee cross-stage coverage when the corpus contains both phases.
    for required_type in (WorkType.RESEARCH, WorkType.DEVELOPMENT):
        for index, item in enumerate(prepared):
            if index in selected_ids or item[0].work_type is not required_type:
                continue
            selected.append(item)
            selected_ids.add(index)
            break

    # Prefer additional distinct WorkItems before taking another cycle from the same one.
    selected_work_ids = {item[0].work_id for item in selected}
    for index, item in enumerate(prepared):
        if len(selected) >= max_cases:
            break
        if index in selected_ids or item[0].work_id in selected_work_ids:
            continue
        selected.append(item)
        selected_ids.add(index)
        selected_work_ids.add(item[0].work_id)

    for index, item in enumerate(prepared):
        if len(selected) >= max_cases:
            break
        if index in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(index)

    prepared = selected[:max_cases]
    selected_types = {item[0].work_type for item in prepared}
    distinct_work_items = len({item[0].work_id for item in prepared})
    representative_corpus = (
        WorkType.RESEARCH in selected_types
        and WorkType.DEVELOPMENT in selected_types
        and distinct_work_items >= 2
    )

    candidate_stats = {
        **candidate_stats,
        "same_model_candidates": len(candidates),
        "context_drift_cases": context_drift_cases,
        "non_reducing_cases": non_reducing_cases,
        "replay_ready_by_work_type": ready_by_type,
        "selected_replay_cases": len(prepared),
        "selected_distinct_work_items": distinct_work_items,
        "representative_corpus_covered": representative_corpus,
    }
    if len(prepared) < min_equivalent_cases or not representative_corpus:
        return {
            "model": model,
            "requested_max_cases": max_cases,
            "minimum_equivalent_cases": min_equivalent_cases,
            "replayed_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_replayed_cases_equivalent": False,
            "all_replayed_cases_reduced": False,
            "representative_corpus_covered": representative_corpus,
            "c6_apply_decision_equivalence_proven": False,
            "production_routing_mutated": False,
            "actions_executed": False,
            "paid_fallback_enabled": False,
            "provider_circuit_updated": False,
            "candidate_stats": candidate_stats,
            "cases": [],
        }

    circuit = BackgroundProviderCircuitRegistry().circuit(
        provider_circuit_key(provider=CHATGPT_PLAN_PROVIDER_ID, model=model)
    )
    if not circuit.allow_request():
        raise RuntimeError(
            "ChatGPT-plan provider circuit is cooling down; "
            f"retry after about {int(circuit.remaining_seconds)} seconds"
        )

    plan = ChatGPTPlanSessionManager()
    if not plan.is_connected():
        raise RuntimeError("ChatGPT-plan connection is unavailable")
    visible = {item.slug for item in plan.list_models()}
    if model not in visible:
        raise RuntimeError(
            f"C6 replay model {model!r} is not visible to the connected ChatGPT plan"
        )
    client = build_chatgpt_plan_structured_output_client(
        model=model,
        session_manager=plan,
        provider_retries=False,
    )

    cases: list[dict[str, object]] = []
    for (
        work,
        recorded,
        historical_attempt,
        replay,
        legacy_chars,
        optimized_chars,
    ) in prepared:
        optimized, telemetry = await evaluate_structured_work_request(client, replay)

        comparison = compare_recorded_context_decision(recorded, optimized)
        if comparison is None:
            raise RuntimeError(
                "C6 replay candidate lost its durable decision provenance"
            )
        reduction = (legacy_chars - optimized_chars) * 100.0 / legacy_chars
        cases.append(
            {
                "route_request_id": recorded.route_request_id,
                "work_id": work.work_id,
                "work_type": work.work_type.value,
                "historical_decision_id": historical_attempt.decision_id,
                "historical_target_id": historical_attempt.target_id,
                "historical_provider_id": historical_attempt.provider_id,
                "historical_model_id": historical_attempt.model_id,
                "equivalent": comparison.equivalent,
                "action_equal": comparison.action_equal,
                "goal_complete_equal": comparison.goal_complete_equal,
                "needs_owner_equal": comparison.needs_owner_equal,
                "owner_question_equal": comparison.owner_question_equal,
                "parameters_equal": comparison.parameters_equal,
                "legacy_chars": legacy_chars,
                "optimized_chars": optimized_chars,
                "context_reduced": True,
                "reduction_percent": round(reduction, 2),
                "usage": dict(telemetry.usage),
                "usage_observed": telemetry.usage_observed,
                "latency_ms": round(telemetry.latency_ms, 2),
            }
        )
        if not comparison.equivalent:
            break

    equivalent_count = sum(bool(item["equivalent"]) for item in cases)
    mismatch_count = len(cases) - equivalent_count
    all_reduced = bool(cases) and all(bool(item["context_reduced"]) for item in cases)
    apply_equivalence_proven = (
        len(cases) >= min_equivalent_cases
        and mismatch_count == 0
        and all_reduced
        and representative_corpus
    )
    return {
        "model": model,
        "requested_max_cases": max_cases,
        "minimum_equivalent_cases": min_equivalent_cases,
        "replayed_cases": len(cases),
        "equivalent_cases": equivalent_count,
        "mismatch_cases": mismatch_count,
        "all_replayed_cases_equivalent": bool(cases) and mismatch_count == 0,
        "all_replayed_cases_reduced": all_reduced,
        "representative_corpus_covered": representative_corpus,
        "c6_apply_decision_equivalence_proven": apply_equivalence_proven,
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        "candidate_stats": candidate_stats,
        "cases": cases,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure C6 context reduction and optionally replay optimized decisions."
    )
    parser.add_argument(
        "--decision-replay",
        action="store_true",
        help=(
            "Explicitly consume bounded ChatGPT-plan inference to compare optimized "
            "APPLY decisions with durable legacy SHADOW decisions."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Optional ChatGPT-plan model override for --decision-replay. "
            "Defaults to the persisted JARVIS_CHATGPT_PLAN_MODEL."
        ),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=3,
        help="Maximum number of sequential decision replay calls.",
    )
    parser.add_argument(
        "--min-equivalent-cases",
        type=int,
        default=3,
        help="Minimum equivalent replay cases required to mark decision equivalence proven.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.max_cases <= 0:
        print("ERROR: --max-cases must be positive.", file=sys.stderr)
        return 2
    if args.max_cases > _MAX_DECISION_REPLAY_CASES:
        print(
            "ERROR: --max-cases cannot exceed "
            f"{_MAX_DECISION_REPLAY_CASES} for the bounded owner replay.",
            file=sys.stderr,
        )
        return 2
    if args.min_equivalent_cases <= 0:
        print("ERROR: --min-equivalent-cases must be positive.", file=sys.stderr)
        return 2
    if args.min_equivalent_cases > args.max_cases:
        print(
            "ERROR: --min-equivalent-cases cannot exceed --max-cases.",
            file=sys.stderr,
        )
        return 2

    path = default_work_store_path()
    store = SQLiteWorkStore(
        path,
        payload_codec=build_default_work_payload_codec(path),
    )
    assembler = WorkContextAssembler()
    route_store = BrainRouteStore(store)
    rows: list[dict[str, object]] = []

    for work in store.list(limit=500):
        steps = store.list_steps(work.work_id)
        if len(steps) < 4:
            continue
        pack = assembler.build(work=work, steps=steps)
        legacy = {"recent_steps": _legacy_steps(steps), "evidence": []}
        optimized = {
            "recent_steps": pack.recent_steps_payload(),
            "evidence": list(pack.evidence),
            "history_manifest": pack.history_manifest_payload(),
        }
        legacy_chars = _chars(legacy)
        optimized_chars = _chars(optimized)
        selected_ids = {step.step_id for step in pack.selected_steps}
        latest_retained = steps[-1].step_id in selected_ids
        reduction = (
            (legacy_chars - optimized_chars) * 100.0 / legacy_chars
            if legacy_chars
            else 0.0
        )
        routes = route_store.list_for_work(work.work_id)
        model_routes = tuple(
            route for route in routes if route.route_kind is BrainRouteKind.MODEL
        )
        comparable_routes = tuple(
            route
            for route in model_routes
            if route.goal_complete is not None
            and route.needs_owner is not None
            and route.parameters_digest is not None
        )
        rows.append(
            {
                "work_id": work.work_id,
                "work_type": work.work_type.value,
                "history_steps": len(steps),
                "legacy_chars": legacy_chars,
                "optimized_chars": optimized_chars,
                "reduction_percent": round(reduction, 2),
                "selected_steps": len(pack.selected_steps),
                "omitted_steps": pack.omitted_step_count,
                "latest_step_retained": latest_retained,
                "model_route_count": len(model_routes),
                "c6_comparable_model_routes": len(comparable_routes),
            }
        )

    rows.sort(
        key=lambda item: (
            -int(item["history_steps"]),
            str(item["work_id"]),
        )
    )
    evaluated = rows[:50]
    failures = [row for row in evaluated if not bool(row["latest_step_retained"])]
    reductions = [
        float(row["reduction_percent"])
        for row in evaluated
        if int(row["history_steps"]) > 12
    ]
    model_route_count = sum(int(row["model_route_count"]) for row in evaluated)
    comparable_route_count = sum(
        int(row["c6_comparable_model_routes"]) for row in evaluated
    )
    result = {
        "status": "PASS" if evaluated and not failures else "INCOMPLETE",
        "model_api_called": False,
        "production_routing_mutated": False,
        "work_store": str(path),
        "evaluated_work_items": len(evaluated),
        "long_history_items": len(reductions),
        "long_history_mean_reduction_percent": (
            round(sum(reductions) / len(reductions), 2) if reductions else None
        ),
        "latest_step_retention_failures": len(failures),
        "model_route_count": model_route_count,
        "c6_comparable_model_routes": comparable_route_count,
        "c6_decision_provenance_coverage_percent": (
            None
            if model_route_count == 0
            else round(comparable_route_count * 100.0 / model_route_count, 2)
        ),
        "c6_apply_decision_equivalence_proven": False,
        "c6_apply_note": (
            "This zero-model harness measures context reduction and durable legacy "
            "decision provenance only. APPLY still requires optimized decision replay "
            "with full safety-field equivalence."
        ),
        "items": evaluated,
    }
    if args.decision_replay:
        settings = load_machine_settings()
        model = str(
            args.model
            or configured_text("JARVIS_CHATGPT_PLAN_MODEL", settings, "")
            or ""
        ).strip()
        if not model:
            print(
                "ERROR: --model or JARVIS_CHATGPT_PLAN_MODEL is required "
                "for --decision-replay.",
                file=sys.stderr,
            )
            return 2
        try:
            replay = asyncio.run(
                _run_decision_replay(
                    store=store,
                    route_store=route_store,
                    model=model,
                    max_cases=args.max_cases,
                    min_equivalent_cases=args.min_equivalent_cases,
                )
            )
        except Exception as exc:  # noqa: BLE001 - explicit benchmark boundary
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        result["model_api_called"] = bool(replay["replayed_cases"])
        result["decision_replay"] = replay
        result["c6_apply_decision_equivalence_proven"] = replay[
            "c6_apply_decision_equivalence_proven"
        ]
        result["c6_apply_note"] = (
            "Decision equivalence is benchmark evidence only. Production remains "
            "unchanged until JARVIS_WORK_CONTEXT_MODE is explicitly promoted."
        )
        if replay["c6_apply_decision_equivalence_proven"] is not True:
            result["status"] = "INCOMPLETE"

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
