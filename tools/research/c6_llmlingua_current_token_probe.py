"""One-call provider-token probe reusing accepted C6 LLMLingua evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

if __package__:
    from tools.research import c6_context_owner_acceptance as c6
    from tools.research.c6_benchmark_corpus import build_c6_benchmark_cases
else:
    import c6_context_owner_acceptance as c6
    from c6_benchmark_corpus import build_c6_benchmark_cases

from jarvis.chatgpt_plan import CHATGPT_PLAN_PROVIDER_ID, ChatGPTPlanSessionManager
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.hands.provider_adapters import build_chatgpt_plan_structured_output_client
from jarvis.provider_circuit import (
    BackgroundProviderCircuitRegistry,
    provider_circuit_key,
)
from jarvis.work.context import WorkContextMode
from jarvis.work.prompt_compression import (
    DEFAULT_LLMLINGUA2_REVISION,
    REVIEWED_LLMLINGUA_LIBRARY_REVISION,
    LLMLingua2WorkPayloadCompressor,
)
from jarvis.work.reasoner import (
    _work_full_history_input_payload,
    _work_input_payload,
    evaluate_structured_work_request,
)

_CASE_ID = "research_ready_for_digest_bound_finalize"
_ACCEPTED_OWNER_COMMIT = "3749bcea09556ea48ccbbcf6c2688eb67e0588c1"
_ACCEPTED_RUNTIME_BLOBS = {
    "src/jarvis/work/reasoner.py": "32c197b55732729236ec9b93b408b4b69d7d2105",
    "src/jarvis/work/prompt_compression.py": "5a879c95b709847b58af42652cbcabf164ba8002",
    "src/jarvis/hands/provider_adapters.py": "131befe250983ace29b26043490649ee7ada48f2",
    "src/jarvis/chatgpt_plan.py": "4bde709975eef39b0dadbc79362f2637a70acfe4",
    "src/jarvis/engineering_substrate/canonical.py": "dc5dbe65cf662d0e8283548b2f62812ff9805f1c",
    "tools/research/c6_benchmark_corpus.py": "d0cda8ea0e2b8313cf0fb4831af4c1758ab2b837",
    "tools/research/c6_context_owner_acceptance.py": "1717f16e8707c215919fe9ac148b7940d8f9a49a",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError("evidence report must contain a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_output(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _validated_runtime_lineage() -> dict[str, Any]:
    """Bind the one-call token comparison to the runtime that produced the PASS."""

    repo_root = Path(__file__).resolve().parents[2]
    mismatches: list[str] = []
    actual_blobs: dict[str, str] = {}
    for relative_path, expected_blob in _ACCEPTED_RUNTIME_BLOBS.items():
        path = repo_root / relative_path
        if not path.is_file():
            mismatches.append(f"{relative_path}:missing")
            continue
        actual_blob = _git_output(repo_root, "hash-object", str(path))
        actual_blobs[relative_path] = actual_blob
        if actual_blob != expected_blob:
            mismatches.append(
                f"{relative_path}:expected={expected_blob}:actual={actual_blob}"
            )
    if mismatches:
        raise ValueError(
            "C6 accepted runtime lineage drifted since owner PASS: "
            + "; ".join(mismatches)
        )

    return {
        "accepted_owner_commit": _ACCEPTED_OWNER_COMMIT,
        "current_head": _git_output(repo_root, "rev-parse", "HEAD"),
        "accepted_runtime_blobs": dict(_ACCEPTED_RUNTIME_BLOBS),
        "actual_runtime_blobs": actual_blobs,
        "runtime_lineage_matches_owner_pass": True,
    }


def _validated_prior_evidence(
    report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if report.get("status") != "PASS":
        raise ValueError("prior LLMLingua evidence must have status PASS")
    benchmark = report.get("llmlingua_fixture_benchmark")
    if not isinstance(benchmark, dict):
        raise TypeError("prior report is missing llmlingua_fixture_benchmark")
    if benchmark.get("preflight_only") is not False:
        raise ValueError("prior evidence must be a live LLMLingua benchmark")
    if benchmark.get("all_baselines_stable") is not True:
        raise ValueError("prior full-history baseline was not stable")
    if benchmark.get("all_fixture_cases_equivalent") is not True:
        raise ValueError("prior compressed decision was not strictly equivalent")
    if benchmark.get("all_full_history_payloads_beat_current") is not True:
        raise ValueError(
            "prior compressed payload did not beat current serialized size"
        )
    if benchmark.get("all_provider_input_tokens_reduced") is not True:
        raise ValueError(
            "prior compressed payload did not beat full-history provider tokens"
        )
    if (
        benchmark.get("compressor_library_revision")
        != REVIEWED_LLMLINGUA_LIBRARY_REVISION
    ):
        raise ValueError(
            "prior LLMLingua library revision does not match reviewed revision"
        )
    if benchmark.get("compressor_model_revision") != DEFAULT_LLMLINGUA2_REVISION:
        raise ValueError(
            "prior LLMLingua model revision does not match reviewed revision"
        )

    cases = benchmark.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict):
        raise ValueError("prior evidence must contain exactly one live case")
    case = cases[0]
    if case.get("case_id") != _CASE_ID:
        raise ValueError("prior evidence uses the wrong C6 research case")
    required_true = (
        "baseline_stable",
        "compressed_evaluated",
        "equivalent",
        "action_equal",
        "parameters_equal",
        "goal_complete_equal",
        "needs_owner_equal",
        "owner_question_equal",
        "beats_current_payload",
        "provider_input_tokens_reduced",
    )
    missing = [name for name in required_true if case.get(name) is not True]
    if missing:
        raise ValueError(
            "prior evidence is missing required PASS fields: " + ", ".join(missing)
        )
    return benchmark, case


def _rebuild_payloads(
    benchmark: dict[str, Any],
    prior_case: dict[str, Any],
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    cases = {case.case_id: case for case in build_c6_benchmark_cases()}
    case = cases[_CASE_ID]
    current_request = replace(case.request, context_mode=WorkContextMode.SHADOW)
    current_payload = _work_input_payload(current_request)
    full_history_payload = _work_full_history_input_payload(current_request)

    compressor = LLMLingua2WorkPayloadCompressor(
        model_name=str(benchmark["compressor_model"]),
        rate=float(benchmark["compression_rate"]),
        device_map=str(benchmark["device_map"]),
    )
    compressed = compressor.compress_payload(full_history_payload)

    digests = {
        "current_request_digest": canonical_digest(current_payload),
        "full_history_request_digest": canonical_digest(full_history_payload),
        "compressed_request_digest": canonical_digest(compressed.payload),
    }
    for key, actual in digests.items():
        expected = str(prior_case.get(key) or "")
        if not expected or actual != expected:
            raise ValueError(f"prior evidence payload digest mismatch: {key}")

    previous_versions = benchmark.get("runtime_dependency_versions")
    current_versions = c6._installed_compressor_versions()
    if previous_versions != current_versions:
        raise ValueError(
            "local compressor dependency versions drifted since PASS evidence"
        )

    return current_request, current_payload, compressed.payload


async def _run_probe(
    *,
    evidence_report: Path,
    model_override: str | None,
) -> dict[str, Any]:
    lineage = _validated_runtime_lineage()
    report = _read_json(evidence_report)
    benchmark, prior_case = _validated_prior_evidence(report)
    current_request, current_payload, _compressed_payload = _rebuild_payloads(
        benchmark,
        prior_case,
    )

    evidence_model = str(benchmark.get("model") or "").strip()
    model = str(model_override or evidence_model).strip()
    if not model:
        raise ValueError(
            "model is missing from prior evidence and no override was supplied"
        )
    if evidence_model and model != evidence_model:
        raise ValueError("model override does not match prior PASS evidence model")

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
            f"C6 current-payload probe model {model!r} is not visible to the connected plan"
        )

    client = build_chatgpt_plan_structured_output_client(
        model=model,
        session_manager=plan,
        provider_retries=False,
    )
    current_decision, telemetry = await evaluate_structured_work_request(
        client,
        current_request,
        provider_payload_override=current_payload,
    )

    current_input_tokens = int(telemetry.usage.get("input_tokens", 0) or 0)
    prior_usage = prior_case.get("compressed_usage")
    if not isinstance(prior_usage, dict):
        raise TypeError("prior evidence is missing compressed provider usage")
    compressed_input_tokens = int(prior_usage.get("input_tokens", 0) or 0)
    if (
        not telemetry.usage_observed
        or current_input_tokens <= 0
        or compressed_input_tokens <= 0
    ):
        raise ValueError("provider input-token usage is unavailable")

    compressed_beats_current = compressed_input_tokens < current_input_tokens
    reduction_percent = (
        round(
            (current_input_tokens - compressed_input_tokens)
            * 100.0
            / current_input_tokens,
            2,
        )
        if compressed_beats_current
        else 0.0
    )

    prior_action = str(prior_case.get("full_context_first_action") or "")
    prior_parameters = prior_case.get("full_context_first_parameters")
    action_matches_prior_full = current_decision.action == prior_action
    parameters_match_prior_full = (
        isinstance(prior_parameters, dict)
        and current_decision.parameters == prior_parameters
    )

    return {
        "status": "PASS" if compressed_beats_current else "INCOMPLETE",
        **lineage,
        "evidence_report": str(evidence_report),
        "evidence_report_sha256": _sha256_file(evidence_report),
        "model": model,
        "model_calls": 1,
        "case_id": _CASE_ID,
        "current_recent_steps": len(current_request.recent_steps),
        "full_history_steps": len(
            current_request.full_history_steps or current_request.recent_steps
        ),
        "current_payload_chars": c6._chars(current_payload),
        "compressed_payload_chars": int(prior_case["compressed_chars"]),
        "current_provider_input_tokens": current_input_tokens,
        "accepted_compressed_provider_input_tokens": compressed_input_tokens,
        "compressed_beats_current_provider_tokens": compressed_beats_current,
        "compressed_vs_current_provider_token_reduction_percent": reduction_percent,
        "current_action": current_decision.action,
        "current_action_matches_prior_full_history": action_matches_prior_full,
        "current_parameters_match_prior_full_history": parameters_match_prior_full,
        "production_routing_mutated": False,
        "actions_executed": False,
        "paid_fallback_enabled": False,
        "provider_circuit_updated": False,
        "c6_apply_decision_equivalence_proven": False,
        "note": (
            "This one-call probe reuses accepted full-history/compressed semantic evidence "
            "and measures actual provider input tokens for today's current payload. "
            "It does not automatically promote production APPLY."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reuse accepted C6 LLMLingua evidence and make one current-payload model "
            "call to measure actual provider-token savings versus production today."
        )
    )
    parser.add_argument("--evidence-report", required=True)
    parser.add_argument("--model", default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(
            _run_probe(
                evidence_report=Path(args.evidence_report).expanduser().resolve(),
                model_override=args.model,
            )
        )
    except Exception as exc:  # noqa: BLE001 - explicit owner acceptance boundary
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
