"""Development-only Gemini 3.8 diagnostic on exposed V3 calibration.

Fresh V3 failed calibration and validation was never executed. This harness replays
only the exposed calibration split, proves exact Top-10 Qwen retrieval reproduction,
then changes one semantic variable: Gemini 3.5 Flash-Lite -> Gemini 3.8 Flash with
medium thinking. It must never access V3 validation and is not acceptance evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import step4_phase45d_abstention_calibration as baseline
import step4_phase45d_final_v3_acceptance as v3_acceptance
import step4_phase45d_final_v3_cases as v3_cases
import step4_phase45d_semantic_judge_bakeoff as semantic
from pydantic import ValidationError

from jarvis.ai_provider import require_provider_api_key
from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)

GEMINI38_MODEL_ID = "gemini-3.8-flash"
GEMINI38_THINKING_LEVEL = "medium"
GEMINI_BATCH_SIZE = 1
GEMINI_CONCURRENCY = 1
DEFAULT_GEMINI_RPM = 12.0
SOURCE_DEFAULT = Path(".step4-phase45d-final-v3-acceptance.json")
OUTPUT_DEFAULT = Path(".step4-phase45d-v3-gemini38-calibration-diagnostic-v1.json")
EXPECTED_V3_OWNER_SHA = "783a5b49cdf31a957c403066f1ea421c007354a4"
EXPECTED_V3_FALSE_RELEASE_IDS = frozenset(
    {
        "v3_cal_p0036",
        "v3_cal_p0084",
        "v3_cal_p0120",
        "v3_cal_p0132",
        "v3_cal_p0168",
        "v3_cal_aord0026",
        "v3_cal_aord0027",
        "v3_cal_aord0028",
        "v3_cal_aord0044",
        "v3_cal_aord0091",
        "v3_cal_abnd0006",
        "v3_cal_abnd0007",
        "v3_cal_abnd0010",
        "v3_cal_abnd0011",
    }
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_v3_source(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"missing retired V3 evidence: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "FAIL_CALIBRATION":
        raise RuntimeError("source artifact is not the retired V3 calibration failure")
    if payload.get("validation_executed") is not False:
        raise RuntimeError("V3 validation must remain unexecuted for this diagnostic")
    if payload.get("git_sha") != EXPECTED_V3_OWNER_SHA:
        raise RuntimeError(
            "source artifact owner SHA does not match frozen V3 execution"
        )
    corpus = payload.get("corpus")
    if not isinstance(corpus, dict):
        raise TypeError("source artifact has no corpus metadata")
    if corpus.get("sha256") != v3_acceptance.EXPECTED_V3_PAYLOAD_SHA256:
        raise RuntimeError("source artifact corpus SHA does not match frozen V3")
    acceptance = payload.get("acceptance")
    if (
        not isinstance(acceptance, dict)
        or acceptance.get("calibration_pass") is not False
    ):
        raise RuntimeError("source artifact does not preserve V3 calibration failure")
    if acceptance.get("validation_executed") is not False:
        raise RuntimeError("source artifact unexpectedly exposed V3 validation")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 360:
        raise RuntimeError(
            "retired V3 source must contain exactly 360 calibration cases"
        )
    if any(case.get("split") != "calibration" for case in cases):
        raise RuntimeError("retired V3 source contains non-calibration cases")
    calibration = payload.get("calibration")
    if not isinstance(calibration, dict):
        raise TypeError("source artifact has no calibration section")
    source_acceptance = calibration.get("acceptance")
    if not isinstance(source_acceptance, dict):
        raise TypeError("source artifact has no calibration acceptance result")
    policy = source_acceptance.get("policy")
    if not isinstance(policy, dict):
        raise TypeError("source artifact has no calibration policy")
    false_ids = frozenset(
        str(value) for value in policy.get("false_release_case_ids", [])
    )
    if false_ids != EXPECTED_V3_FALSE_RELEASE_IDS:
        raise RuntimeError("retired V3 false-release set does not match owner result")
    return payload


def _assert_retrieval_reproduction(
    retrieved: Sequence[v3_acceptance.RetrievedCase],
    source: dict[str, Any],
) -> None:
    source_cases = source["cases"]
    source_by_id = {str(case["case_id"]): case for case in source_cases}
    if len(source_by_id) != 360 or len(retrieved) != 360:
        raise RuntimeError("V3 calibration case count changed during reproduction")
    if set(source_by_id) != {case.case_id for case in retrieved}:
        raise RuntimeError("V3 calibration case IDs changed during reproduction")
    for case in retrieved:
        prior = source_by_id[case.case_id]
        if prior.get("top_memory_id") != case.top_memory_id:
            raise RuntimeError(f"Top-1 reproduction changed for {case.case_id}")
        if bool(prior.get("positive_top1_correct")) != case.positive_top1_correct:
            raise RuntimeError(f"Top-1 correctness changed for {case.case_id}")
        if bool(prior.get("positive_hit_at_10")) != case.positive_hit_at_10:
            raise RuntimeError(f"Recall@10 reproduction changed for {case.case_id}")


async def _call_gemini38(
    client: Any,
    pair: Any,
    *,
    pacer: semantic.GeminiRequestPacer,
) -> semantic.GeminiBatchResult:
    input_payload = {
        "cases": [
            {
                "index": 0,
                "query": pair.query,
                "memory": pair.top_document,
            }
        ]
    }
    last_error: Exception | None = None
    for attempt in range(5):
        await pacer.wait()
        started = time.perf_counter()
        try:
            response = await client.aio.interactions.create(
                model=GEMINI38_MODEL_ID,
                input=json.dumps(input_payload, ensure_ascii=False),
                system_instruction=semantic.GEMINI_SYSTEM_PROMPT,
                generation_config={"thinking_level": GEMINI38_THINKING_LEVEL},
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": semantic.GeminiJudgeBatch.model_json_schema(),
                },
                store=False,
            )
            elapsed = time.perf_counter() - started
            output_text = getattr(response, "output_text", None)
            if not isinstance(output_text, str) or not output_text.strip():
                raise RuntimeError("Gemini 3.8 returned no semantic-judge output")
            try:
                parsed = semantic.GeminiJudgeBatch.model_validate_json(output_text)
            except ValidationError as exc:
                raise RuntimeError("Gemini 3.8 returned invalid judge JSON") from exc
            if len(parsed.results) != 1 or parsed.results[0].index != 0:
                raise RuntimeError("Gemini 3.8 single-instance index contract changed")
            return semantic.GeminiBatchResult(
                judgments=parsed.results,
                elapsed_seconds=elapsed,
                usage=semantic._extract_usage(response),
            )
        except Exception as exc:
            last_error = exc
            raw = str(exc)
            upper = raw.upper()
            retryable = any(
                marker in upper
                for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")
            )
            if not retryable or attempt == 4:
                raise
            retry_after = semantic._retry_after_seconds(raw)
            delay = max(
                float(2**attempt),
                pacer.interval_seconds,
                (retry_after + 1.0) if retry_after is not None else 0.0,
            )
            await asyncio.sleep(delay)
    raise AssertionError(f"unreachable Gemini 3.8 retry state: {last_error}")


async def _score_gemini38(
    pairs: Sequence[Any],
    *,
    rpm: float,
) -> tuple[list[semantic.GeminiJudgeItem], dict[str, Any]]:
    from google import genai

    api_key = require_provider_api_key(
        "gemini", purpose="Gemini 3.8 memory judge diagnostic"
    )
    client = genai.Client(api_key=api_key)
    pacer = semantic.GeminiRequestPacer(rpm)
    judgments: list[semantic.GeminiJudgeItem] = []
    request_seconds: list[float] = []
    usage: Counter[str] = Counter()
    started = time.perf_counter()
    for pair in pairs:
        result = await _call_gemini38(client, pair, pacer=pacer)
        judgments.extend(result.judgments)
        request_seconds.append(result.elapsed_seconds)
        usage.update(result.usage)
    wall = time.perf_counter() - started
    return judgments, {
        "model_id": GEMINI38_MODEL_ID,
        "thinking_level": GEMINI38_THINKING_LEVEL,
        "requests": len(pairs),
        "cases": len(pairs),
        "batch_size": GEMINI_BATCH_SIZE,
        "concurrency": GEMINI_CONCURRENCY,
        "rpm_cap": rpm,
        "minimum_request_start_interval_seconds": round(pacer.interval_seconds, 4),
        "wall_seconds": round(wall, 4),
        "mean_request_seconds": round(sum(request_seconds) / len(request_seconds), 4)
        if request_seconds
        else None,
        "usage": dict(usage),
    }


def _materialize(
    retrieved: Sequence[v3_acceptance.RetrievedCase],
    judgments: Sequence[semantic.GeminiJudgeItem],
) -> list[v3_acceptance.V3CaseResult]:
    callable_cases = [case for case in retrieved if case.gemini_pair() is not None]
    if len(callable_cases) != len(judgments):
        raise RuntimeError("Gemini 3.8 judgment count does not match callable cases")
    judgment_by_id = {
        case.case_id: judgment
        for case, judgment in zip(callable_cases, judgments, strict=True)
    }
    rows: list[v3_acceptance.V3CaseResult] = []
    for case in retrieved:
        judgment = judgment_by_id.get(case.case_id)
        rows.append(
            v3_acceptance.V3CaseResult(
                case_id=case.case_id,
                split=case.split,
                label=case.label,
                expected_memory_id=case.expected_memory_id,
                language=case.language,
                category=case.category,
                top_memory_id=case.top_memory_id,
                positive_top1_correct=case.positive_top1_correct,
                positive_hit_at_10=case.positive_hit_at_10,
                rerank_score=case.rerank_score,
                rerank_margin=case.rerank_margin,
                gemini_called=judgment is not None,
                gemini_decision=judgment.decision
                if judgment is not None
                else "abstain",
                gemini_failure_mode=(
                    judgment.failure_mode
                    if judgment is not None
                    else "missing_or_unsupported"
                ),
                query_embedding_ms=case.query_embedding_ms,
                retrieval_ms=case.retrieval_ms,
                rerank_ms=case.rerank_ms,
            )
        )
    return rows


def _comparison(
    source: dict[str, Any],
    current: Sequence[v3_acceptance.V3CaseResult],
) -> dict[str, Any]:
    prior_by_id = {str(case["case_id"]): case for case in source["cases"]}
    current_by_id = {case.case_id: case for case in current}
    if set(prior_by_id) != set(current_by_id):
        raise RuntimeError("case IDs changed before Gemini 3.8 comparison")

    old_false = {
        case_id
        for case_id, case in prior_by_id.items()
        if case.get("gemini_decision") == "release"
        and not bool(case.get("safe_to_release"))
    }
    new_false = {
        case.case_id for case in current if case.released and not case.safe_to_release
    }
    old_safe_releases = {
        case_id
        for case_id, case in prior_by_id.items()
        if case.get("gemini_decision") == "release"
        and bool(case.get("safe_to_release"))
    }
    new_safe_releases = {
        case.case_id for case in current if case.released and case.safe_to_release
    }
    return {
        "prior_false_releases": sorted(old_false),
        "corrected_prior_false_releases": sorted(old_false - new_false),
        "remaining_prior_false_releases": sorted(old_false & new_false),
        "new_false_releases": sorted(new_false - old_false),
        "safe_release_regressions": sorted(old_safe_releases - new_safe_releases),
        "new_safe_releases": sorted(new_safe_releases - old_safe_releases),
    }


def _selection(
    acceptance: dict[str, Any], *, retrieval_reproduced: bool
) -> dict[str, Any]:
    checks = {
        "retrieval_reproduced": retrieval_reproduced,
        "exact_precision_lower_bound": bool(
            acceptance["checks"]["exact_precision_lower_bound"]
        ),
        "release_recall": bool(acceptance["checks"]["release_recall"]),
        "language_release_recall": bool(
            acceptance["checks"]["language_release_recall"]
        ),
        "zero_security_boundary_releases": bool(
            acceptance["checks"]["zero_security_boundary_releases"]
        ),
    }
    return {"checks": checks, "selected_for_v4_design": all(checks.values())}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc

    source_path = Path(args.source)
    source = _load_v3_source(source_path)
    payload = v3_cases.build_payload()
    if v3_cases.payload_sha256(payload) != v3_acceptance.EXPECTED_V3_PAYLOAD_SHA256:
        raise RuntimeError("local V3 corpus changed after retirement")
    calibration_items = [
        item for item in payload["queries"] if item["split"] == "calibration"
    ]
    if len(calibration_items) != 360:
        raise RuntimeError("V3 calibration size changed")

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-v3-gemini38-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "diagnostic.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-v3-g38-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-v3-g38-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=args.device)
        reranker = Qwen3RetrievalReranker(
            device=args.device,
            candidate_window=v3_acceptance.QWEN_CANDIDATE_WINDOW,
        )
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError("frozen Qwen reranker instruction changed")
        try:
            started = time.perf_counter()
            _, assertion_to_memory = await baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            population_seconds = time.perf_counter() - started
            retrieved = await v3_acceptance._retrieve_cases(
                calibration_items,
                retrieval=retrieval,
                embedder=embedder,
                reranker=reranker,
                assertion_to_memory=assertion_to_memory,
            )
            _assert_retrieval_reproduction(retrieved, source)

            pairs = [
                case.gemini_pair()
                for case in retrieved
                if case.gemini_pair() is not None
            ]
            typed_pairs = [pair for pair in pairs if pair is not None]
            judgments, gemini_timing = await _score_gemini38(
                typed_pairs,
                rpm=args.gemini_rpm,
            )
            current = _materialize(retrieved, judgments)
        finally:
            await worker.close()

    acceptance = v3_acceptance._calibration_acceptance(current)
    comparison = _comparison(source, current)
    selection = _selection(acceptance, retrieval_reproduced=True)
    return {
        "status": "DEVELOPMENT_GEMINI38_CALIBRATION_DIAGNOSTIC_COMPLETE",
        "purpose": "Phase 4.5D one-variable Gemini 3.8 semantic judge diagnostic",
        "development_only": True,
        "acceptance_evidence": False,
        "v3_is_retired": True,
        "v3_validation_accessed": False,
        "v3_validation_executed": False,
        "source": {
            "path": str(source_path),
            "sha256": _file_sha256(source_path),
            "status": source["status"],
            "owner_run_sha": source["git_sha"],
            "cases": len(source["cases"]),
        },
        "corpus": {
            "sha256": v3_acceptance.EXPECTED_V3_PAYLOAD_SHA256,
            "split": "calibration_only",
            "cases": 360,
        },
        "frozen_shape": {
            "candidate_window": v3_acceptance.QWEN_CANDIDATE_WINDOW,
            "request_shape": "one_query_document_pair_per_interactions_request",
            "system_prompt": semantic.GEMINI_SYSTEM_PROMPT,
            "store": False,
        },
        "changed_variable": {
            "from_model": semantic.GEMINI_MODEL_ID,
            "to_model": GEMINI38_MODEL_ID,
            "thinking_level": GEMINI38_THINKING_LEVEL,
        },
        "calibration": {
            "acceptance": acceptance,
            "languages": v3_acceptance._breakdown(current, "language"),
            "categories": v3_acceptance._breakdown(current, "category"),
            "gemini_timing": gemini_timing,
            "fixture_population_and_document_embedding_seconds": round(
                population_seconds, 4
            ),
            "qwen_peak_cuda_bytes": (
                int(torch.cuda.max_memory_allocated())
                if torch.cuda.is_available()
                else None
            ),
        },
        "comparison_to_v3_flash_lite": comparison,
        "selection": selection,
        "cases": [v3_acceptance._public_case(case) for case in current],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--source", default=str(SOURCE_DEFAULT))
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not math.isfinite(args.gemini_rpm) or args.gemini_rpm <= 0:
        raise ValueError("--gemini-rpm must be a positive finite number")
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(f"refusing to overwrite existing diagnostic: {output_path}")
    output = asyncio.run(_run(args))
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", output["status"])
    print(
        "CALIBRATION:",
        json.dumps(output["calibration"]["acceptance"], ensure_ascii=False),
    )
    print(
        "COMPARISON:",
        json.dumps(output["comparison_to_v3_flash_lite"], ensure_ascii=False),
    )
    print("SELECTION:", json.dumps(output["selection"], ensure_ascii=False))


if __name__ == "__main__":
    main()
