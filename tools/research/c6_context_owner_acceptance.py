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
from importlib import metadata
import sys
from dataclasses import replace

if __package__:
    from tools.research.c6_benchmark_corpus import build_c6_benchmark_cases
else:
    from c6_benchmark_corpus import build_c6_benchmark_cases

from jarvis.brain_routing.models import BrainRouteKind
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.chatgpt_plan import CHATGPT_PLAN_PROVIDER_ID, ChatGPTPlanSessionManager
from jarvis.engineering_substrate.canonical import canonical_digest
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
    compare_context_decisions,
    compare_recorded_context_decision,
    reconstruct_recorded_context_request,
)
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.prompt_compression import (
    DEFAULT_LLMLINGUA2_MODEL,
    DEFAULT_LLMLINGUA2_REVISION,
    REVIEWED_LLMLINGUA_LIBRARY_REVISION,
    LLMLingua2WorkPayloadCompressor,
)
from jarvis.work.reasoner import (
    _work_full_history_input_payload,
    _work_input_payload,
    evaluate_structured_work_request,
    work_reasoning_contract_digest,
)
from jarvis.work.store import SQLiteWorkStore, default_work_store_path

_MAX_DECISION_REPLAY_CASES = 5
_MAX_PAIRED_BENCHMARK_CASES = 3
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


def _paired_benchmark_candidates(
    store: SQLiteWorkStore,
    route_store: BrainRouteStore,
    *,
    limit: int,
):
    """Return successful model-route snapshots usable for fresh legacy/APPLY A/B."""

    candidates = []
    stats = {
        "model_routes_seen": 0,
        "missing_context_snapshot": 0,
        "missing_route_contract_lineage": 0,
        "route_snapshot_contract_mismatch": 0,
        "non_selected_model_routes": 0,
    }
    for work in store.list(limit=500):
        steps = store.list_steps(work.work_id)
        for route in route_store.list_for_work(work.work_id):
            if route.route_kind is not BrainRouteKind.MODEL:
                continue
            stats["model_routes_seen"] += 1
            if route.outcome_code != "selected" or route.selected_action is None:
                stats["non_selected_model_routes"] += 1
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
            candidates.append(
                (
                    route.created_at_epoch,
                    work,
                    steps,
                    route,
                    snapshot,
                )
            )
    candidates.sort(key=lambda item: (-float(item[0]), item[3].route_request_id))
    return tuple(candidates[:limit]), stats


def _prepare_paired_benchmark(
    *,
    store: SQLiteWorkStore,
    route_store: BrainRouteStore,
    max_cases: int,
) -> tuple[list[tuple], dict[str, object]]:
    candidates, candidate_stats = _paired_benchmark_candidates(
        store,
        route_store,
        limit=_MAX_REPLAY_CANDIDATE_SCAN,
    )

    prepared = []
    context_drift_cases = 0
    non_reducing_cases = 0
    for _created_at, work, steps, route, snapshot in candidates:
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
                route,
                replay,
                legacy_chars,
                optimized_chars,
            )
        )

    ready_types = tuple(
        sorted({item[0].work_type for item in prepared}, key=lambda value: value.value)
    )
    ready_by_type = {
        work_type.value: sum(1 for item in prepared if item[0].work_type is work_type)
        for work_type in ready_types
    }

    selected = []
    selected_ids: set[int] = set()
    for required_type in ready_types:
        if len(selected) >= max_cases:
            break
        for index, item in enumerate(prepared):
            if index in selected_ids or item[0].work_type is not required_type:
                continue
            selected.append(item)
            selected_ids.add(index)
            break

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

    selected = selected[:max_cases]
    selected_types = {item[0].work_type for item in selected}
    distinct_work_items = len({item[0].work_id for item in selected})
    representative_corpus = len(selected_types) >= 2 and distinct_work_items >= 2

    return selected, {
        **candidate_stats,
        "snapshot_candidates": len(candidates),
        "context_drift_cases": context_drift_cases,
        "non_reducing_cases": non_reducing_cases,
        "paired_ready_by_work_type": ready_by_type,
        "paired_ready_work_types": [item.value for item in ready_types],
        "selected_paired_cases": len(selected),
        "selected_work_types": sorted(item.value for item in selected_types),
        "selected_distinct_work_items": distinct_work_items,
        "representative_corpus_covered": representative_corpus,
    }


async def _run_paired_decision_benchmark(
    *,
    store: SQLiteWorkStore,
    route_store: BrainRouteStore,
    model: str,
    max_cases: int,
    min_equivalent_cases: int,
    preflight_only: bool = False,
) -> dict[str, object]:
    prepared, candidate_stats = _prepare_paired_benchmark(
        store=store,
        route_store=route_store,
        max_cases=max_cases,
    )
    representative_corpus = bool(candidate_stats["representative_corpus_covered"])
    ready = len(prepared) >= min_equivalent_cases and representative_corpus

    common = {
        "model": model,
        "requested_max_cases": max_cases,
        "minimum_equivalent_cases": min_equivalent_cases,
        "paired_preflight_only": bool(preflight_only),
        "paired_preflight_ready": ready,
        "representative_corpus_covered": representative_corpus,
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        "candidate_stats": candidate_stats,
    }
    if not ready:
        return {
            **common,
            "paired_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_paired_cases_equivalent": False,
            "all_paired_cases_reduced": False,
            "c6_apply_decision_equivalence_proven": False,
            "planned_cases": [],
            "cases": [],
        }

    planned_cases = [
        {
            "route_request_id": route.route_request_id,
            "work_id": work.work_id,
            "work_type": work.work_type.value,
            "legacy_chars": legacy_chars,
            "optimized_chars": optimized_chars,
            "reduction_percent": round(
                (legacy_chars - optimized_chars) * 100.0 / legacy_chars,
                2,
            ),
        }
        for work, route, _replay, legacy_chars, optimized_chars in prepared
    ]
    if preflight_only:
        return {
            **common,
            "paired_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_paired_cases_equivalent": False,
            "all_paired_cases_reduced": True,
            "c6_apply_decision_equivalence_proven": False,
            "planned_cases": planned_cases,
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
            f"C6 paired benchmark model {model!r} is not visible to the connected "
            "ChatGPT plan"
        )
    client = build_chatgpt_plan_structured_output_client(
        model=model,
        session_manager=plan,
        provider_retries=False,
    )

    cases: list[dict[str, object]] = []
    for work, route, replay, legacy_chars, optimized_chars in prepared:
        legacy_request = replace(replay, context_mode=WorkContextMode.SHADOW)
        legacy, legacy_telemetry = await evaluate_structured_work_request(
            client,
            legacy_request,
        )
        optimized, optimized_telemetry = await evaluate_structured_work_request(
            client,
            replay,
        )
        comparison = compare_context_decisions(legacy, optimized)
        reduction = (legacy_chars - optimized_chars) * 100.0 / legacy_chars
        cases.append(
            {
                "route_request_id": route.route_request_id,
                "work_id": work.work_id,
                "work_type": work.work_type.value,
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
                "legacy_usage": dict(legacy_telemetry.usage),
                "legacy_usage_observed": legacy_telemetry.usage_observed,
                "legacy_latency_ms": round(legacy_telemetry.latency_ms, 2),
                "optimized_usage": dict(optimized_telemetry.usage),
                "optimized_usage_observed": optimized_telemetry.usage_observed,
                "optimized_latency_ms": round(optimized_telemetry.latency_ms, 2),
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
        **common,
        "paired_preflight_only": False,
        "paired_cases": len(cases),
        "equivalent_cases": equivalent_count,
        "mismatch_cases": mismatch_count,
        "all_paired_cases_equivalent": bool(cases) and mismatch_count == 0,
        "all_paired_cases_reduced": all_reduced,
        "c6_apply_decision_equivalence_proven": apply_equivalence_proven,
        "planned_cases": planned_cases,
        "cases": cases,
    }


def _prepare_fixture_benchmark(
    *,
    max_cases: int,
) -> tuple[list[tuple], dict[str, object]]:
    """Prepare the checked-in descriptor-only C6 benchmark corpus."""

    cases = build_c6_benchmark_cases()
    prepared = []
    non_reducing_cases = 0
    for case in cases:
        legacy_request = replace(case.request, context_mode=WorkContextMode.SHADOW)
        legacy_chars = _chars(_work_input_payload(legacy_request))
        optimized_chars = _chars(_work_input_payload(case.request))
        if optimized_chars >= legacy_chars:
            non_reducing_cases += 1
            continue
        prepared.append(
            (
                case,
                legacy_chars,
                optimized_chars,
            )
        )

    ready_types = tuple(
        sorted(
            {item[0].request.work.work_type for item in prepared},
            key=lambda value: value.value,
        )
    )
    selected = []
    selected_ids: set[int] = set()
    for required_type in ready_types:
        if len(selected) >= max_cases:
            break
        for index, item in enumerate(prepared):
            if (
                index in selected_ids
                or item[0].request.work.work_type is not required_type
            ):
                continue
            selected.append(item)
            selected_ids.add(index)
            break
    for index, item in enumerate(prepared):
        if len(selected) >= max_cases:
            break
        if index in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(index)

    selected = selected[:max_cases]
    selected_types = {item[0].request.work.work_type for item in selected}
    representative = len(selected_types) >= 2 and len(selected) >= 3
    return selected, {
        "fixture_cases_total": len(cases),
        "fixture_cases_reducing": len(prepared),
        "non_reducing_cases": non_reducing_cases,
        "selected_fixture_cases": len(selected),
        "selected_work_types": sorted(item.value for item in selected_types),
        "representative_corpus_covered": representative,
        "case_ids": [item[0].case_id for item in selected],
    }


async def _run_fixture_stability_benchmark(
    *,
    model: str,
    preflight_only: bool = False,
) -> dict[str, object]:
    """Measure exact same-context decision stability with at most two model calls."""

    prepared, candidate_stats = _prepare_fixture_benchmark(
        max_cases=_MAX_PAIRED_BENCHMARK_CASES
    )
    selected = next(
        (
            item
            for item in prepared
            if item[0].case_id == "development_repair_after_failure"
        ),
        None,
    )
    ready = selected is not None
    common: dict[str, object] = {
        "corpus_source": "checked_in_descriptor_fixture",
        "model": model,
        "fixture_stability_preflight_only": bool(preflight_only),
        "fixture_stability_ready": ready,
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        "c6_apply_decision_equivalence_proven": False,
        "candidate_stats": candidate_stats,
    }
    if selected is None:
        return {
            **common,
            "model_calls": 0,
            "same_context_stable": None,
            "case": None,
        }

    case, legacy_chars, optimized_chars = selected
    legacy_request = replace(case.request, context_mode=WorkContextMode.SHADOW)
    legacy_payload = _work_input_payload(legacy_request)
    request_digest = canonical_digest(legacy_payload)
    case_common = {
        "case_id": case.case_id,
        "work_id": case.request.work.work_id,
        "work_type": case.request.work.work_type.value,
        "legacy_chars": legacy_chars,
        "optimized_chars": optimized_chars,
        "same_context_request_digest": request_digest,
        "reasoning_contract_digest": work_reasoning_contract_digest(),
    }
    if preflight_only:
        return {
            **common,
            "model_calls": 0,
            "same_context_stable": None,
            "case": case_common,
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
            f"C6 fixture stability model {model!r} is not visible to the connected "
            "ChatGPT plan"
        )
    client = build_chatgpt_plan_structured_output_client(
        model=model,
        session_manager=plan,
        provider_retries=False,
    )

    first, first_telemetry = await evaluate_structured_work_request(
        client,
        legacy_request,
    )
    # Deliberately reuse the exact same immutable BrainRequest. The transport creates
    # independent Responses calls, so any decision-field mismatch here is provider/model
    # variance rather than C6 context compaction.
    second, second_telemetry = await evaluate_structured_work_request(
        client,
        legacy_request,
    )
    comparison = compare_context_decisions(first, second)
    return {
        **common,
        "model_calls": 2,
        "same_context_stable": comparison.equivalent,
        "case": {
            **case_common,
            "first_action": first.action,
            "second_action": second.action,
            "action_equal": comparison.action_equal,
            "first_parameters": dict(first.parameters),
            "second_parameters": dict(second.parameters),
            "first_parameters_digest": canonical_digest(first.parameters),
            "second_parameters_digest": canonical_digest(second.parameters),
            "goal_complete_equal": comparison.goal_complete_equal,
            "needs_owner_equal": comparison.needs_owner_equal,
            "owner_question_equal": comparison.owner_question_equal,
            "parameters_equal": comparison.parameters_equal,
            "first_usage": dict(first_telemetry.usage),
            "first_usage_observed": first_telemetry.usage_observed,
            "first_latency_ms": round(first_telemetry.latency_ms, 2),
            "second_usage": dict(second_telemetry.usage),
            "second_usage_observed": second_telemetry.usage_observed,
            "second_latency_ms": round(second_telemetry.latency_ms, 2),
        },
    }


async def _run_fixture_first_pair_benchmark(
    *,
    model: str,
    preflight_only: bool = False,
) -> dict[str, object]:
    """Compare one fixed legacy-vs-optimized fixture pair with at most two model calls."""

    prepared, candidate_stats = _prepare_fixture_benchmark(
        max_cases=_MAX_PAIRED_BENCHMARK_CASES
    )
    selected = next(
        (
            item
            for item in prepared
            if item[0].case_id == "development_repair_after_failure"
        ),
        None,
    )
    ready = selected is not None
    common: dict[str, object] = {
        "corpus_source": "checked_in_descriptor_fixture",
        "model": model,
        "fixture_first_pair_preflight_only": bool(preflight_only),
        "fixture_first_pair_ready": ready,
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        # One pair is diagnostic evidence only; it can never prove global C6 APPLY.
        "c6_apply_decision_equivalence_proven": False,
        "candidate_stats": candidate_stats,
    }
    if selected is None:
        return {
            **common,
            "model_calls": 0,
            "pair_equivalent": None,
            "case": None,
        }

    case, legacy_chars, optimized_chars = selected
    legacy_request = replace(case.request, context_mode=WorkContextMode.SHADOW)
    legacy_payload = _work_input_payload(legacy_request)
    optimized_payload = _work_input_payload(case.request)
    case_common = {
        "case_id": case.case_id,
        "work_id": case.request.work.work_id,
        "work_type": case.request.work.work_type.value,
        "legacy_chars": legacy_chars,
        "optimized_chars": optimized_chars,
        "reduction_percent": round(
            (legacy_chars - optimized_chars) * 100.0 / legacy_chars,
            2,
        ),
        "legacy_request_digest": canonical_digest(legacy_payload),
        "optimized_request_digest": canonical_digest(optimized_payload),
        "reasoning_contract_digest": work_reasoning_contract_digest(),
    }
    if preflight_only:
        return {
            **common,
            "model_calls": 0,
            "pair_equivalent": None,
            "case": case_common,
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
            f"C6 first-pair model {model!r} is not visible to the connected ChatGPT plan"
        )
    client = build_chatgpt_plan_structured_output_client(
        model=model,
        session_manager=plan,
        provider_retries=False,
    )

    legacy, legacy_telemetry = await evaluate_structured_work_request(
        client,
        legacy_request,
    )
    optimized, optimized_telemetry = await evaluate_structured_work_request(
        client,
        case.request,
    )
    comparison = compare_context_decisions(legacy, optimized)
    return {
        **common,
        "model_calls": 2,
        "pair_equivalent": comparison.equivalent,
        "case": {
            **case_common,
            "legacy_action": legacy.action,
            "optimized_action": optimized.action,
            "action_equal": comparison.action_equal,
            "legacy_parameters": dict(legacy.parameters),
            "optimized_parameters": dict(optimized.parameters),
            "legacy_parameters_digest": canonical_digest(legacy.parameters),
            "optimized_parameters_digest": canonical_digest(optimized.parameters),
            "goal_complete_equal": comparison.goal_complete_equal,
            "needs_owner_equal": comparison.needs_owner_equal,
            "owner_question_equal": comparison.owner_question_equal,
            "parameters_equal": comparison.parameters_equal,
            "legacy_usage": dict(legacy_telemetry.usage),
            "legacy_usage_observed": legacy_telemetry.usage_observed,
            "legacy_latency_ms": round(legacy_telemetry.latency_ms, 2),
            "optimized_usage": dict(optimized_telemetry.usage),
            "optimized_usage_observed": optimized_telemetry.usage_observed,
            "optimized_latency_ms": round(optimized_telemetry.latency_ms, 2),
        },
    }


async def _run_fixture_decision_benchmark(
    *,
    model: str,
    max_cases: int,
    min_equivalent_cases: int,
    preflight_only: bool = False,
    case_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    prepare_limit = _MAX_PAIRED_BENCHMARK_CASES if case_ids else max_cases
    prepared, candidate_stats = _prepare_fixture_benchmark(max_cases=prepare_limit)
    subset_mode = case_ids is not None
    if case_ids is not None:
        by_id = {item[0].case_id: item for item in prepared}
        prepared = [by_id[case_id] for case_id in case_ids if case_id in by_id]
    representative = bool(candidate_stats["representative_corpus_covered"])
    ready = len(prepared) >= min_equivalent_cases and representative

    common = {
        "corpus_source": "checked_in_descriptor_fixture",
        "model": model,
        "requested_max_cases": max_cases,
        "minimum_equivalent_cases": min_equivalent_cases,
        "fixture_preflight_only": bool(preflight_only),
        "fixture_preflight_ready": ready,
        "representative_corpus_covered": representative,
        "subset_mode": subset_mode,
        "requested_case_ids": list(case_ids or ()),
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        "candidate_stats": candidate_stats,
    }
    planned_cases = [
        {
            "case_id": case.case_id,
            "work_id": case.request.work.work_id,
            "work_type": case.request.work.work_type.value,
            "rationale": case.rationale,
            "legacy_chars": legacy_chars,
            "optimized_chars": optimized_chars,
            "reduction_percent": round(
                (legacy_chars - optimized_chars) * 100.0 / legacy_chars,
                2,
            ),
        }
        for case, legacy_chars, optimized_chars in prepared
    ]
    if not ready:
        return {
            **common,
            "fixture_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_fixture_cases_equivalent": False,
            "all_fixture_cases_reduced": False,
            "c6_apply_decision_equivalence_proven": False,
            "planned_cases": planned_cases,
            "cases": [],
        }
    if preflight_only:
        return {
            **common,
            "fixture_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_fixture_cases_equivalent": False,
            "all_fixture_cases_reduced": True,
            "c6_apply_decision_equivalence_proven": False,
            "planned_cases": planned_cases,
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
            f"C6 fixture benchmark model {model!r} is not visible to the connected "
            "ChatGPT plan"
        )
    client = build_chatgpt_plan_structured_output_client(
        model=model,
        session_manager=plan,
        provider_retries=False,
    )

    results: list[dict[str, object]] = []
    for case, legacy_chars, optimized_chars in prepared:
        legacy_request = replace(
            case.request,
            context_mode=WorkContextMode.SHADOW,
        )
        legacy, legacy_telemetry = await evaluate_structured_work_request(
            client,
            legacy_request,
        )
        optimized, optimized_telemetry = await evaluate_structured_work_request(
            client,
            case.request,
        )
        comparison = compare_context_decisions(legacy, optimized)
        legacy_input_tokens = int(legacy_telemetry.usage.get("input_tokens", 0) or 0)
        optimized_input_tokens = int(
            optimized_telemetry.usage.get("input_tokens", 0) or 0
        )
        provider_input_tokens_reduced = (
            legacy_telemetry.usage_observed
            and optimized_telemetry.usage_observed
            and legacy_input_tokens > 0
            and optimized_input_tokens < legacy_input_tokens
        )
        results.append(
            {
                "case_id": case.case_id,
                "work_id": case.request.work.work_id,
                "work_type": case.request.work.work_type.value,
                "equivalent": comparison.equivalent,
                "legacy_action": legacy.action,
                "optimized_action": optimized.action,
                "action_equal": comparison.action_equal,
                "legacy_parameters": dict(legacy.parameters),
                "optimized_parameters": dict(optimized.parameters),
                "legacy_parameters_digest": canonical_digest(legacy.parameters),
                "optimized_parameters_digest": canonical_digest(optimized.parameters),
                "goal_complete_equal": comparison.goal_complete_equal,
                "needs_owner_equal": comparison.needs_owner_equal,
                "owner_question_equal": comparison.owner_question_equal,
                "parameters_equal": comparison.parameters_equal,
                "legacy_chars": legacy_chars,
                "optimized_chars": optimized_chars,
                "reduction_percent": round(
                    (legacy_chars - optimized_chars) * 100.0 / legacy_chars,
                    2,
                ),
                "legacy_usage": dict(legacy_telemetry.usage),
                "legacy_usage_observed": legacy_telemetry.usage_observed,
                "legacy_latency_ms": round(legacy_telemetry.latency_ms, 2),
                "optimized_usage": dict(optimized_telemetry.usage),
                "optimized_usage_observed": optimized_telemetry.usage_observed,
                "optimized_latency_ms": round(optimized_telemetry.latency_ms, 2),
                "provider_input_tokens_reduced": provider_input_tokens_reduced,
                "provider_input_token_reduction_percent": (
                    round(
                        (legacy_input_tokens - optimized_input_tokens)
                        * 100.0
                        / legacy_input_tokens,
                        2,
                    )
                    if provider_input_tokens_reduced
                    else 0.0
                ),
            }
        )
        if not comparison.equivalent:
            break

    equivalent_count = sum(bool(item["equivalent"]) for item in results)
    mismatch_count = len(results) - equivalent_count
    all_provider_input_tokens_reduced = bool(results) and all(
        bool(item["provider_input_tokens_reduced"]) for item in results
    )
    apply_equivalence_proven = (
        not subset_mode
        and len(results) >= min_equivalent_cases
        and mismatch_count == 0
        and representative
    )
    return {
        **common,
        "fixture_preflight_only": False,
        "fixture_cases": len(results),
        "equivalent_cases": equivalent_count,
        "mismatch_cases": mismatch_count,
        "all_fixture_cases_equivalent": bool(results) and mismatch_count == 0,
        "all_fixture_cases_reduced": True,
        "all_provider_input_tokens_reduced": all_provider_input_tokens_reduced,
        "c6_apply_decision_equivalence_proven": apply_equivalence_proven,
        "planned_cases": planned_cases,
        "cases": results,
    }


def _installed_compressor_versions() -> dict[str, str | None]:
    packages = (
        "llmlingua",
        "torch",
        "transformers",
        "accelerate",
        "tiktoken",
        "nltk",
        "numpy",
    )
    versions: dict[str, str | None] = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def _llmlingua_fixture_cases(
    case_ids: tuple[str, ...] | None,
):
    cases = build_c6_benchmark_cases()
    if case_ids is None:
        return cases
    by_id = {case.case_id: case for case in cases}
    return tuple(by_id[case_id] for case_id in case_ids if case_id in by_id)


async def _run_llmlingua_fixture_benchmark(
    *,
    model: str | None,
    compressor_model: str,
    compression_rate: float,
    device_map: str,
    case_ids: tuple[str, ...] | None = None,
    preflight_only: bool = False,
    compressor_factory=None,
) -> dict[str, object]:
    """Compare full canonical history with its locally compressed equivalent."""

    selected = _llmlingua_fixture_cases(case_ids)
    requested_ids = list(case_ids or ())
    missing_ids = (
        []
        if case_ids is None
        else [
            case_id
            for case_id in case_ids
            if case_id not in {c.case_id for c in selected}
        ]
    )
    if compressor_factory is None:
        compressor = LLMLingua2WorkPayloadCompressor(
            model_name=compressor_model,
            rate=compression_rate,
            device_map=device_map,
        )
    else:
        compressor = compressor_factory()

    prepared: list[tuple] = []
    compression_failures: list[dict[str, object]] = []
    for case in selected:
        current_request = replace(case.request, context_mode=WorkContextMode.SHADOW)
        current_payload = _work_input_payload(current_request)
        full_history_payload = _work_full_history_input_payload(current_request)
        try:
            compressed = compressor.compress_payload(full_history_payload)
        except Exception as exc:  # noqa: BLE001 - explicit local-compressor boundary
            compression_failures.append(
                {
                    "case_id": case.case_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue

        current_chars = _chars(current_payload)
        current_estimated_tokens = max(1, (current_chars + 3) // 4)
        beats_current = (
            compressed.reduced
            and compressed.compressed_chars < current_chars
            and compressed.estimated_compressed_tokens < current_estimated_tokens
        )
        prepared.append(
            (
                case,
                current_request,
                current_payload,
                full_history_payload,
                compressed,
                beats_current,
            )
        )

    all_reduced = bool(prepared) and all(item[4].reduced for item in prepared)
    all_beat_current = bool(prepared) and all(bool(item[5]) for item in prepared)
    ready = (
        bool(selected)
        and not missing_ids
        and not compression_failures
        and len(prepared) == len(selected)
        and all_reduced
        and all_beat_current
    )
    planned_cases = [
        {
            "case_id": case.case_id,
            "work_id": case.request.work.work_id,
            "work_type": case.request.work.work_type.value,
            "baseline_scope": "full_history",
            "full_history_steps": len(
                case.request.full_history_steps or case.request.recent_steps
            ),
            "current_recent_steps": len(case.request.recent_steps),
            "current_chars": _chars(current_payload),
            "legacy_chars": compressed.original_chars,
            "full_history_chars": compressed.original_chars,
            "compressed_chars": compressed.compressed_chars,
            "reduction_percent": compressed.reduction_percent,
            "compressed_vs_current_reduction_percent": round(
                (_chars(current_payload) - compressed.compressed_chars)
                * 100.0
                / _chars(current_payload),
                2,
            ),
            "estimated_full_history_tokens": compressed.estimated_original_tokens,
            "estimated_compressed_tokens": compressed.estimated_compressed_tokens,
            "candidate_strings": compressed.candidate_strings,
            "compressed_strings": compressed.compressed_strings,
            "compression_latency_ms": round(compressed.latency_ms, 2),
            "changed_paths": list(compressed.changed_paths),
            "beats_current_payload": beats_current,
            "current_request_digest": canonical_digest(current_payload),
            "legacy_request_digest": canonical_digest(full_history_payload),
            "full_history_request_digest": canonical_digest(full_history_payload),
            "compressed_request_digest": canonical_digest(compressed.payload),
        }
        for (
            case,
            _request,
            current_payload,
            full_history_payload,
            compressed,
            beats_current,
        ) in prepared
    ]
    common: dict[str, object] = {
        "corpus_source": "checked_in_descriptor_fixture",
        "model": model,
        "compressor": "llmlingua2",
        "compressor_model": compressor_model,
        "compressor_library_revision": REVIEWED_LLMLINGUA_LIBRARY_REVISION,
        "compressor_model_revision": DEFAULT_LLMLINGUA2_REVISION,
        "runtime_dependency_versions": _installed_compressor_versions(),
        "compression_rate": compression_rate,
        "device_map": device_map,
        "requested_case_ids": requested_ids,
        "missing_case_ids": missing_ids,
        "preflight_only": bool(preflight_only),
        "preflight_ready": ready,
        "baseline_scope": "full_history",
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        "c6_apply_decision_equivalence_proven": False,
        "compression_failures": compression_failures,
        "planned_cases": planned_cases,
        "all_full_history_payloads_beat_current": all_beat_current,
    }
    if preflight_only or not ready:
        return {
            **common,
            "model_calls": 0,
            "fixture_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_fixture_cases_equivalent": False,
            "all_fixture_cases_reduced": all_reduced,
            "all_provider_input_tokens_reduced": False,
            "cases": [],
        }

    live_model = str(model or "").strip()
    if not live_model:
        raise ValueError("ChatGPT-plan model is required for LLMLingua live benchmark")

    circuit = BackgroundProviderCircuitRegistry().circuit(
        provider_circuit_key(provider=CHATGPT_PLAN_PROVIDER_ID, model=live_model)
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
    if live_model not in visible:
        raise RuntimeError(
            f"C6 LLMLingua benchmark model {live_model!r} is not visible to the "
            "connected ChatGPT plan"
        )
    client = build_chatgpt_plan_structured_output_client(
        model=live_model,
        session_manager=plan,
        provider_retries=False,
    )

    results: list[dict[str, object]] = []
    model_calls = 0
    for (
        case,
        current_request,
        current_payload,
        full_history_payload,
        compressed,
        beats_current,
    ) in prepared:
        full_context, full_context_telemetry = await evaluate_structured_work_request(
            client,
            current_request,
            provider_payload_override=full_history_payload,
        )
        model_calls += 1
        (
            compressed_decision,
            compressed_telemetry,
        ) = await evaluate_structured_work_request(
            client,
            current_request,
            provider_payload_override=compressed.payload,
        )
        model_calls += 1
        comparison = compare_context_decisions(full_context, compressed_decision)
        full_input_tokens = int(
            full_context_telemetry.usage.get("input_tokens", 0) or 0
        )
        compressed_input_tokens = int(
            compressed_telemetry.usage.get("input_tokens", 0) or 0
        )
        provider_input_tokens_reduced = (
            full_context_telemetry.usage_observed
            and compressed_telemetry.usage_observed
            and full_input_tokens > 0
            and compressed_input_tokens < full_input_tokens
        )
        results.append(
            {
                "case_id": case.case_id,
                "work_id": case.request.work.work_id,
                "work_type": case.request.work.work_type.value,
                "baseline_scope": "full_history",
                "full_history_steps": len(
                    case.request.full_history_steps or case.request.recent_steps
                ),
                "current_recent_steps": len(case.request.recent_steps),
                "equivalent": comparison.equivalent,
                "legacy_action": full_context.action,
                "full_context_action": full_context.action,
                "compressed_action": compressed_decision.action,
                "action_equal": comparison.action_equal,
                "legacy_parameters": dict(full_context.parameters),
                "full_context_parameters": dict(full_context.parameters),
                "compressed_parameters": dict(compressed_decision.parameters),
                "legacy_parameters_digest": canonical_digest(full_context.parameters),
                "full_context_parameters_digest": canonical_digest(
                    full_context.parameters
                ),
                "compressed_parameters_digest": canonical_digest(
                    compressed_decision.parameters
                ),
                "goal_complete_equal": comparison.goal_complete_equal,
                "needs_owner_equal": comparison.needs_owner_equal,
                "owner_question_equal": comparison.owner_question_equal,
                "parameters_equal": comparison.parameters_equal,
                "current_chars": _chars(current_payload),
                "legacy_chars": compressed.original_chars,
                "full_history_chars": compressed.original_chars,
                "compressed_chars": compressed.compressed_chars,
                "reduction_percent": compressed.reduction_percent,
                "compressed_vs_current_reduction_percent": round(
                    (_chars(current_payload) - compressed.compressed_chars)
                    * 100.0
                    / _chars(current_payload),
                    2,
                ),
                "beats_current_payload": beats_current,
                "candidate_strings": compressed.candidate_strings,
                "compressed_strings": compressed.compressed_strings,
                "compression_latency_ms": round(compressed.latency_ms, 2),
                "changed_paths": list(compressed.changed_paths),
                "current_request_digest": canonical_digest(current_payload),
                "legacy_request_digest": canonical_digest(full_history_payload),
                "full_history_request_digest": canonical_digest(full_history_payload),
                "compressed_request_digest": canonical_digest(compressed.payload),
                "legacy_usage": dict(full_context_telemetry.usage),
                "full_context_usage": dict(full_context_telemetry.usage),
                "legacy_usage_observed": full_context_telemetry.usage_observed,
                "full_context_usage_observed": full_context_telemetry.usage_observed,
                "legacy_latency_ms": round(full_context_telemetry.latency_ms, 2),
                "full_context_latency_ms": round(full_context_telemetry.latency_ms, 2),
                "compressed_usage": dict(compressed_telemetry.usage),
                "compressed_usage_observed": compressed_telemetry.usage_observed,
                "compressed_latency_ms": round(compressed_telemetry.latency_ms, 2),
                "provider_input_tokens_reduced": provider_input_tokens_reduced,
                "provider_input_token_reduction_percent": (
                    round(
                        (full_input_tokens - compressed_input_tokens)
                        * 100.0
                        / full_input_tokens,
                        2,
                    )
                    if provider_input_tokens_reduced
                    else 0.0
                ),
            }
        )
        if not comparison.equivalent:
            break

    equivalent_count = sum(bool(item["equivalent"]) for item in results)
    mismatch_count = len(results) - equivalent_count
    all_provider_input_tokens_reduced = bool(results) and all(
        bool(item["provider_input_tokens_reduced"]) for item in results
    )
    return {
        **common,
        "preflight_only": False,
        "model_calls": model_calls,
        "fixture_cases": len(results),
        "equivalent_cases": equivalent_count,
        "mismatch_cases": mismatch_count,
        "all_fixture_cases_equivalent": bool(results) and mismatch_count == 0,
        "all_fixture_cases_reduced": all_reduced,
        "all_provider_input_tokens_reduced": all_provider_input_tokens_reduced,
        "c6_apply_decision_equivalence_proven": False,
        "cases": results,
    }


async def _run_decision_replay(
    *,
    store: SQLiteWorkStore,
    route_store: BrainRouteStore,
    model: str,
    max_cases: int,
    min_equivalent_cases: int,
    preflight_only: bool = False,
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

    ready_types = tuple(
        sorted({item[0].work_type for item in prepared}, key=lambda value: value.value)
    )
    ready_by_type = {
        work_type.value: sum(1 for item in prepared if item[0].work_type is work_type)
        for work_type in ready_types
    }
    selected = []
    selected_ids: set[int] = set()

    # C6 APPLY is global. Seed the bounded corpus across the Work types that actually
    # reached model reasoning under the current contract instead of hard-coding
    # Phase-9 RESEARCH/DEVELOPMENT, which may now be control-plane driven.
    for required_type in ready_types:
        if len(selected) >= max_cases:
            break
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
    representative_corpus = len(selected_types) >= 2 and distinct_work_items >= 2

    candidate_stats = {
        **candidate_stats,
        "same_model_candidates": len(candidates),
        "context_drift_cases": context_drift_cases,
        "non_reducing_cases": non_reducing_cases,
        "replay_ready_by_work_type": ready_by_type,
        "replay_ready_work_types": [item.value for item in ready_types],
        "selected_replay_cases": len(prepared),
        "selected_work_types": sorted(item.value for item in selected_types),
        "selected_distinct_work_items": distinct_work_items,
        "representative_corpus_covered": representative_corpus,
    }
    if len(prepared) < min_equivalent_cases or not representative_corpus:
        return {
            "model": model,
            "requested_max_cases": max_cases,
            "minimum_equivalent_cases": min_equivalent_cases,
            "replay_preflight_only": bool(preflight_only),
            "replay_preflight_ready": False,
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

    if preflight_only:
        planned_cases = [
            {
                "route_request_id": recorded.route_request_id,
                "work_id": work.work_id,
                "work_type": work.work_type.value,
                "historical_decision_id": historical_attempt.decision_id,
                "historical_provider_id": historical_attempt.provider_id,
                "historical_model_id": historical_attempt.model_id,
                "legacy_chars": legacy_chars,
                "optimized_chars": optimized_chars,
                "reduction_percent": round(
                    (legacy_chars - optimized_chars) * 100.0 / legacy_chars,
                    2,
                ),
            }
            for (
                work,
                recorded,
                historical_attempt,
                _replay,
                legacy_chars,
                optimized_chars,
            ) in prepared
        ]
        return {
            "model": model,
            "requested_max_cases": max_cases,
            "minimum_equivalent_cases": min_equivalent_cases,
            "replay_preflight_only": True,
            "replay_preflight_ready": True,
            "replayed_cases": 0,
            "equivalent_cases": 0,
            "mismatch_cases": 0,
            "all_replayed_cases_equivalent": False,
            "all_replayed_cases_reduced": True,
            "representative_corpus_covered": representative_corpus,
            "c6_apply_decision_equivalence_proven": False,
            "production_routing_mutated": False,
            "actions_executed": False,
            "paid_fallback_enabled": False,
            "provider_circuit_updated": False,
            "candidate_stats": candidate_stats,
            "planned_cases": planned_cases,
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
        "replay_preflight_only": False,
        "replay_preflight_ready": True,
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
    replay_mode = parser.add_mutually_exclusive_group()
    replay_mode.add_argument(
        "--decision-replay",
        action="store_true",
        help=(
            "Explicitly consume bounded ChatGPT-plan inference to compare optimized "
            "APPLY decisions with durable legacy SHADOW decisions."
        ),
    )
    replay_mode.add_argument(
        "--decision-replay-preflight",
        action="store_true",
        help=(
            "Validate exact replay corpus/model lineage and context reduction without "
            "initializing ChatGPT-plan or consuming model quota."
        ),
    )
    replay_mode.add_argument(
        "--paired-decision-preflight",
        action="store_true",
        help=(
            "Validate a representative historical snapshot corpus for a fresh "
            "legacy-context vs optimized-context A/B benchmark without model calls."
        ),
    )
    replay_mode.add_argument(
        "--paired-decision-benchmark",
        action="store_true",
        help=(
            "Explicitly consume at most two ChatGPT-plan calls per selected case to "
            "compare legacy and optimized decisions on the same historical request."
        ),
    )
    replay_mode.add_argument(
        "--fixture-stability-preflight",
        action="store_true",
        help=(
            "Validate the fixed same-context C6 stability probe without initializing "
            "ChatGPT-plan or consuming model quota."
        ),
    )
    replay_mode.add_argument(
        "--fixture-stability-benchmark",
        action="store_true",
        help=(
            "Explicitly consume exactly two ChatGPT-plan calls for the same legacy "
            "fixture request to measure provider/model decision stability. No Work "
            "action is executed and this cannot prove C6 APPLY equivalence."
        ),
    )
    replay_mode.add_argument(
        "--fixture-first-pair-preflight",
        action="store_true",
        help=(
            "Validate the fixed first legacy-vs-optimized C6 fixture pair without "
            "initializing ChatGPT-plan or consuming model quota."
        ),
    )
    replay_mode.add_argument(
        "--fixture-first-pair-benchmark",
        action="store_true",
        help=(
            "Explicitly consume exactly two ChatGPT-plan calls to compare the corrected "
            "first legacy-vs-optimized fixture pair. No Work action is executed and one "
            "pair cannot prove global C6 APPLY equivalence."
        ),
    )
    replay_mode.add_argument(
        "--fixture-remaining-preflight",
        action="store_true",
        help=(
            "Validate only the two fixed C6 fixture pairs not covered by the accepted "
            "first-pair run, without initializing ChatGPT-plan or consuming quota."
        ),
    )
    replay_mode.add_argument(
        "--fixture-remaining-benchmark",
        action="store_true",
        help=(
            "Consume at most four ChatGPT-plan calls across only the two remaining "
            "fixed C6 fixture pairs. Stops on the first mismatch and cannot promote "
            "global C6 APPLY by itself."
        ),
    )
    replay_mode.add_argument(
        "--fixture-decision-preflight",
        action="store_true",
        help=(
            "Validate the checked-in descriptor-only C6 benchmark corpus without "
            "initializing ChatGPT-plan or consuming model quota."
        ),
    )
    replay_mode.add_argument(
        "--fixture-decision-benchmark",
        action="store_true",
        help=(
            "Explicitly consume at most six ChatGPT-plan calls across the fixed "
            "three-case C6 benchmark corpus. No Work action is executed."
        ),
    )
    replay_mode.add_argument(
        "--llmlingua-fixture-preflight",
        action="store_true",
        help=(
            "Load the local LLMLingua-2 compressor and validate structure-preserving "
            "compression on the fixed C6 corpus without any ChatGPT-plan calls."
        ),
    )
    replay_mode.add_argument(
        "--llmlingua-fixture-benchmark",
        action="store_true",
        help=(
            "Compare exact legacy payloads with locally LLMLingua-compressed full "
            "context. Uses at most two ChatGPT-plan calls per selected fixture and "
            "stops on the first semantic mismatch."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Optional ChatGPT-plan model override for replay/paired benchmark. "
            "Defaults to the persisted JARVIS_CHATGPT_PLAN_MODEL."
        ),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=3,
        help=(
            "Maximum benchmark cases. Historical recorded-decision replay permits up "
            "to 5; paired and fixture A/B modes are hard-capped at 3 cases."
        ),
    )
    parser.add_argument(
        "--min-equivalent-cases",
        type=int,
        default=3,
        help=(
            "Minimum equivalent cases required to mark C6 decision equivalence proven."
        ),
    )
    parser.add_argument(
        "--llmlingua-model",
        default=DEFAULT_LLMLINGUA2_MODEL,
        help="Local LLMLingua-2 compressor model.",
    )
    parser.add_argument(
        "--llmlingua-rate",
        type=float,
        default=0.5,
        help="Target LLMLingua-2 compression rate in the interval (0, 1].",
    )
    parser.add_argument(
        "--llmlingua-device",
        default="cpu",
        help="Local device_map passed to LLMLingua-2; defaults to CPU.",
    )
    parser.add_argument(
        "--llmlingua-case-id",
        action="append",
        default=None,
        help=(
            "Optional fixed fixture case ID for LLMLingua modes. Repeat to select "
            "multiple cases. By default the benchmark targets the research case that "
            "failed hand-selected C6 equivalence."
        ),
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
    if (
        args.paired_decision_preflight
        or args.paired_decision_benchmark
        or args.fixture_decision_preflight
        or args.fixture_decision_benchmark
    ) and args.max_cases > _MAX_PAIRED_BENCHMARK_CASES:
        print(
            "ERROR: paired/fixture benchmark --max-cases cannot exceed "
            f"{_MAX_PAIRED_BENCHMARK_CASES} ({_MAX_PAIRED_BENCHMARK_CASES * 2} "
            "maximum model calls).",
            file=sys.stderr,
        )
        return 2

    if not 0.0 < args.llmlingua_rate <= 1.0:
        print("ERROR: --llmlingua-rate must be within (0, 1].", file=sys.stderr)
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
    if (
        args.decision_replay
        or args.decision_replay_preflight
        or args.paired_decision_preflight
        or args.paired_decision_benchmark
        or args.fixture_stability_preflight
        or args.fixture_stability_benchmark
        or args.fixture_first_pair_preflight
        or args.fixture_first_pair_benchmark
        or args.fixture_remaining_preflight
        or args.fixture_remaining_benchmark
        or args.fixture_decision_preflight
        or args.fixture_decision_benchmark
        or args.llmlingua_fixture_preflight
        or args.llmlingua_fixture_benchmark
    ):
        settings = load_machine_settings()
        model = str(
            args.model
            or configured_text("JARVIS_CHATGPT_PLAN_MODEL", settings, "")
            or ""
        ).strip()
        if not model and not args.llmlingua_fixture_preflight:
            print(
                "ERROR: --model or JARVIS_CHATGPT_PLAN_MODEL is required "
                "for live replay/benchmark modes.",
                file=sys.stderr,
            )
            return 2
        try:
            if args.llmlingua_fixture_preflight or args.llmlingua_fixture_benchmark:
                replay = asyncio.run(
                    _run_llmlingua_fixture_benchmark(
                        model=(model or None),
                        compressor_model=str(args.llmlingua_model).strip(),
                        compression_rate=float(args.llmlingua_rate),
                        device_map=str(args.llmlingua_device).strip(),
                        case_ids=(
                            ("research_requires_reresolution_after_new_evidence",)
                            if not args.llmlingua_case_id
                            else tuple(dict.fromkeys(args.llmlingua_case_id))
                        ),
                        preflight_only=args.llmlingua_fixture_preflight,
                    )
                )
            elif args.fixture_stability_preflight or args.fixture_stability_benchmark:
                replay = asyncio.run(
                    _run_fixture_stability_benchmark(
                        model=model,
                        preflight_only=args.fixture_stability_preflight,
                    )
                )
            elif args.fixture_first_pair_preflight or args.fixture_first_pair_benchmark:
                replay = asyncio.run(
                    _run_fixture_first_pair_benchmark(
                        model=model,
                        preflight_only=args.fixture_first_pair_preflight,
                    )
                )
            elif args.fixture_remaining_preflight or args.fixture_remaining_benchmark:
                replay = asyncio.run(
                    _run_fixture_decision_benchmark(
                        model=model,
                        max_cases=2,
                        min_equivalent_cases=2,
                        preflight_only=args.fixture_remaining_preflight,
                        case_ids=(
                            "development_ready_for_local_commit",
                            "research_requires_reresolution_after_new_evidence",
                        ),
                    )
                )
            elif args.fixture_decision_preflight or args.fixture_decision_benchmark:
                replay = asyncio.run(
                    _run_fixture_decision_benchmark(
                        model=model,
                        max_cases=args.max_cases,
                        min_equivalent_cases=args.min_equivalent_cases,
                        preflight_only=args.fixture_decision_preflight,
                    )
                )
            elif args.paired_decision_preflight or args.paired_decision_benchmark:
                replay = asyncio.run(
                    _run_paired_decision_benchmark(
                        store=store,
                        route_store=route_store,
                        model=model,
                        max_cases=args.max_cases,
                        min_equivalent_cases=args.min_equivalent_cases,
                        preflight_only=args.paired_decision_preflight,
                    )
                )
            else:
                replay = asyncio.run(
                    _run_decision_replay(
                        store=store,
                        route_store=route_store,
                        model=model,
                        max_cases=args.max_cases,
                        min_equivalent_cases=args.min_equivalent_cases,
                        preflight_only=args.decision_replay_preflight,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - explicit benchmark boundary
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

        if args.llmlingua_fixture_preflight:
            result["model_api_called"] = False
            result["llmlingua_fixture_preflight"] = replay
            result["c6_llmlingua_preflight_ready"] = replay["preflight_ready"]
            result["c6_apply_decision_equivalence_proven"] = False
            result["c6_apply_note"] = (
                "LLMLingua local-compression preflight only; production remains SHADOW "
                "and no ChatGPT-plan model call was made."
            )
            if replay["preflight_ready"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.llmlingua_fixture_benchmark:
            result["model_api_called"] = bool(replay["model_calls"])
            result["llmlingua_fixture_benchmark"] = replay
            result["c6_apply_decision_equivalence_proven"] = False
            result["c6_apply_note"] = (
                "LLMLingua A/B evidence cannot promote C6 APPLY automatically. "
                "Production remains SHADOW pending explicit owner acceptance."
            )
            if (
                replay["all_fixture_cases_equivalent"] is not True
                or replay["all_full_history_payloads_beat_current"] is not True
                or replay["all_provider_input_tokens_reduced"] is not True
            ):
                result["status"] = "INCOMPLETE"
        elif args.fixture_stability_preflight:
            result["model_api_called"] = False
            result["fixture_stability_preflight"] = replay
            result["c6_fixture_stability_ready"] = replay["fixture_stability_ready"]
            result["c6_apply_note"] = (
                "Same-context stability preflight only; no model call was made and "
                "C6 APPLY remains unproven."
            )
            if replay["fixture_stability_ready"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_stability_benchmark:
            result["model_api_called"] = bool(replay["model_calls"])
            result["fixture_stability_benchmark"] = replay
            result["c6_apply_decision_equivalence_proven"] = False
            result["c6_apply_note"] = (
                "Same-context stability is a nondeterminism diagnostic only. It does "
                "not prove legacy-vs-optimized C6 equivalence and cannot promote APPLY."
            )
            if replay["same_context_stable"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_first_pair_preflight:
            result["model_api_called"] = False
            result["fixture_first_pair_preflight"] = replay
            result["c6_fixture_first_pair_ready"] = replay["fixture_first_pair_ready"]
            result["c6_apply_note"] = (
                "First-pair preflight only; no model call was made and C6 APPLY "
                "remains unproven."
            )
            if replay["fixture_first_pair_ready"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_first_pair_benchmark:
            result["model_api_called"] = bool(replay["model_calls"])
            result["fixture_first_pair_benchmark"] = replay
            result["c6_apply_decision_equivalence_proven"] = False
            result["c6_apply_note"] = (
                "One corrected legacy-vs-optimized pair is diagnostic evidence only. "
                "It cannot promote global C6 APPLY."
            )
            if replay["pair_equivalent"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_remaining_preflight:
            result["model_api_called"] = False
            result["fixture_remaining_preflight"] = replay
            result["c6_fixture_remaining_ready"] = replay["fixture_preflight_ready"]
            result["c6_apply_note"] = (
                "Remaining-pairs preflight only; no model call was made and global "
                "C6 APPLY remains unproven."
            )
            if replay["fixture_preflight_ready"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_remaining_benchmark:
            result["model_api_called"] = bool(replay["fixture_cases"])
            result["fixture_remaining_benchmark"] = replay
            result["c6_apply_decision_equivalence_proven"] = False
            result["c6_apply_note"] = (
                "Remaining-pairs evidence cannot independently promote global C6 APPLY."
            )
            if replay["all_fixture_cases_equivalent"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_decision_preflight:
            result["model_api_called"] = False
            result["fixture_decision_preflight"] = replay
            result["c6_fixture_preflight_ready"] = replay["fixture_preflight_ready"]
            result["c6_apply_note"] = (
                "Checked-in fixture corpus preflight only; no model call was made "
                "and C6 APPLY remains unproven until the bounded fixture benchmark "
                "passes."
            )
            if replay["fixture_preflight_ready"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.fixture_decision_benchmark:
            result["model_api_called"] = bool(replay["fixture_cases"])
            result["fixture_decision_benchmark"] = replay
            result["c6_apply_decision_equivalence_proven"] = replay[
                "c6_apply_decision_equivalence_proven"
            ]
            result["c6_apply_note"] = (
                "Fixture A/B equivalence is benchmark evidence only. Production "
                "remains unchanged until JARVIS_WORK_CONTEXT_MODE is explicitly "
                "promoted."
            )
            if replay["c6_apply_decision_equivalence_proven"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.paired_decision_preflight:
            result["model_api_called"] = False
            result["paired_decision_preflight"] = replay
            result["c6_paired_preflight_ready"] = replay["paired_preflight_ready"]
            result["c6_apply_note"] = (
                "Paired benchmark corpus preflight only; no model call was made and "
                "C6 APPLY remains unproven until the bounded paired benchmark passes."
            )
            if replay["paired_preflight_ready"] is not True:
                result["status"] = "INCOMPLETE"
        elif args.paired_decision_benchmark:
            result["model_api_called"] = bool(replay["paired_cases"])
            result["paired_decision_benchmark"] = replay
            result["c6_apply_decision_equivalence_proven"] = replay[
                "c6_apply_decision_equivalence_proven"
            ]
            result["c6_apply_note"] = (
                "Paired A/B equivalence is benchmark evidence only. Production "
                "remains unchanged until JARVIS_WORK_CONTEXT_MODE is explicitly "
                "promoted."
            )
            if replay["c6_apply_decision_equivalence_proven"] is not True:
                result["status"] = "INCOMPLETE"
        else:
            result["model_api_called"] = bool(replay["replayed_cases"])
            if args.decision_replay_preflight:
                result["decision_replay_preflight"] = replay
                result["c6_replay_preflight_ready"] = replay["replay_preflight_ready"]
                result["c6_apply_note"] = (
                    "Replay corpus preflight only; no model call was made and C6 APPLY "
                    "remains unproven until the bounded decision replay passes."
                )
                if replay["replay_preflight_ready"] is not True:
                    result["status"] = "INCOMPLETE"
            else:
                result["decision_replay"] = replay
                result["c6_apply_decision_equivalence_proven"] = replay[
                    "c6_apply_decision_equivalence_proven"
                ]
                result["c6_apply_note"] = (
                    "Decision equivalence is benchmark evidence only. Production "
                    "remains unchanged until JARVIS_WORK_CONTEXT_MODE is explicitly "
                    "promoted."
                )
                if replay["c6_apply_decision_equivalence_proven"] is not True:
                    result["status"] = "INCOMPLETE"

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
