"""Development-only Gemini production-shape coverage diagnostic for Phase 4.5D.

The V2 corpus is exposed and retired from acceptance. The prior single-instance
boundary diagnostic proved that 120-instance batching materially changed Gemini
semantic-judge decisions. This harness therefore checks a small, preregistered set of
previously-correct positive and ordinary semantic-abstain cells using the intended
production shape: exactly one query/document pair per Gemini request.

No result from this diagnostic is final acceptance evidence and it cannot authorize
Phase 4.5E.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import step4_phase45d_answerability_verifier_bakeoff as answerability
import step4_phase45d_final_v2_cases as v2_cases
import step4_phase45d_gemini_single_instance_boundary_diagnostic as boundary
import step4_phase45d_semantic_judge_bakeoff as semantic

from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)

SOURCE_ARTIFACT_DEFAULT = boundary.SOURCE_ARTIFACT_DEFAULT
BOUNDARY_ARTIFACT_DEFAULT = boundary.OUTPUT_DEFAULT
OUTPUT_DEFAULT = Path(
    ".step4-phase45d-v2-gemini-single-instance-coverage-diagnostic-v1.json"
)
ORDINARY_ABSTAIN_CATEGORIES = (
    "absent",
    "near_miss",
    "ambiguous",
    "adversarial_lexical",
    "negation",
    "relation_mismatch",
    "unsupported_source",
)
TARGET_LANGUAGES = boundary.TARGET_LANGUAGES
EXPECTED_POSITIVE_CASES = len(TARGET_LANGUAGES)
EXPECTED_ORDINARY_ABSTAIN_CASES = len(ORDINARY_ABSTAIN_CATEGORIES) * len(
    TARGET_LANGUAGES
)
EXPECTED_CASE_COUNT = EXPECTED_POSITIVE_CASES + EXPECTED_ORDINARY_ABSTAIN_CASES
COMBINED_PRODUCTION_SHAPE_CELLS = EXPECTED_CASE_COUNT + boundary.EXPECTED_CASE_COUNT
GEMINI_BATCH_SIZE = 1
GEMINI_CONCURRENCY = 1
DEFAULT_GEMINI_RPM = 12.0


def _load_boundary_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"single-instance boundary artifact not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("single-instance boundary artifact is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("single-instance boundary artifact must be a JSON object")
    if payload.get("status") != (
        "DEVELOPMENT_GEMINI_SINGLE_INSTANCE_BOUNDARY_DIAGNOSTIC_COMPLETE"
    ):
        raise RuntimeError("single-instance boundary diagnostic did not complete")
    if payload.get("acceptance_evidence") is not False:
        raise RuntimeError("boundary artifact must remain development-only evidence")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise TypeError("single-instance boundary artifact has no summary")
    required = {
        "cases": boundary.EXPECTED_CASE_COUNT,
        "prior_batch_release": boundary.EXPECTED_CASE_COUNT,
        "single_instance_release": 0,
        "single_instance_abstain": boundary.EXPECTED_CASE_COUNT,
        "release_to_abstain_flips": boundary.EXPECTED_CASE_COUNT,
        "batching_confound_observed": True,
        "all_target_boundaries_abstained_single_instance": True,
    }
    for key, expected in required.items():
        if summary.get(key) != expected:
            raise RuntimeError(
                f"boundary artifact does not satisfy frozen prerequisite {key}: "
                f"{summary.get(key)!r} != {expected!r}"
            )
    return payload


def _select_coverage_cases(source: dict[str, Any]) -> list[dict[str, Any]]:
    cases = source.get("cases")
    if not isinstance(cases, list):
        raise TypeError("semantic-judge source artifact cases are missing")

    selected: list[dict[str, Any]] = []
    for language in TARGET_LANGUAGES:
        matches = [
            raw
            for raw in cases
            if isinstance(raw, dict)
            and raw.get("split") == "validation"
            and raw.get("label") == "release"
            and raw.get("language") == language
            and raw.get("positive_top1_correct") is True
            and raw.get("gemini_decision") == "release"
        ]
        if not matches:
            raise RuntimeError(
                f"missing previously-correct validation positive for {language}"
            )
        selected.append(min(matches, key=lambda item: str(item.get("case_id", ""))))

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in cases:
        if not isinstance(raw, dict) or raw.get("split") != "validation":
            continue
        category = raw.get("category")
        language = raw.get("language")
        if category in ORDINARY_ABSTAIN_CATEGORIES and language in TARGET_LANGUAGES:
            grouped[(str(category), str(language))].append(raw)

    for category in ORDINARY_ABSTAIN_CATEGORIES:
        for language in TARGET_LANGUAGES:
            matches = [
                raw
                for raw in grouped.get((category, language), [])
                if raw.get("label") == "abstain"
                and raw.get("gemini_decision") == "abstain"
            ]
            if not matches:
                raise RuntimeError(
                    "missing previously-correct validation abstain for "
                    f"{category}/{language}"
                )
            selected.append(min(matches, key=lambda item: str(item.get("case_id", ""))))

    case_ids = [str(item.get("case_id")) for item in selected]
    if len(selected) != EXPECTED_CASE_COUNT or len(case_ids) != len(set(case_ids)):
        raise RuntimeError(
            "single-instance coverage selection is not exactly 24 unique cases"
        )
    return selected


async def _retrieve_selected_pairs(
    device: str,
    selected_source_cases: list[dict[str, Any]],
) -> tuple[list[answerability.RetrievalPair], dict[str, Any]]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required") from exc

    payload = v2_cases.build_payload()
    query_by_id = {str(item["case_id"]): item for item in payload["queries"]}
    selected_queries: list[dict[str, Any]] = []
    for source_case in selected_source_cases:
        case_id = str(source_case["case_id"])
        item = query_by_id.get(case_id)
        if item is None:
            raise RuntimeError(
                f"selected coverage case is absent from frozen V2 corpus: {case_id}"
            )
        selected_queries.append(item)

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-gemini-coverage-") as temp_dir:
        worker = answerability.baseline._connection_worker(
            Path(temp_dir) / "single-instance-coverage.db"
        )
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: answerability.baseline.NOW,
            assertion_id_factory=answerability.baseline._id_factory(
                "phase45d-gemini-coverage-assertion"
            ),
            operation_id_factory=answerability.baseline._id_factory(
                "phase45d-gemini-coverage-operation"
            ),
        )
        embeddings = SemanticEmbeddingStore(
            worker,
            clock=lambda: answerability.baseline.NOW,
        )
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=device)
        reranker = Qwen3RetrievalReranker(
            device=device,
            candidate_window=answerability.QWEN_CANDIDATE_WINDOW,
        )
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError(
                "coverage diagnostic must use the frozen JARVIS reranker instruction"
            )

        query_embedding_ms: list[float] = []
        retrieval_ms: list[float] = []
        rerank_ms: list[float] = []
        pairs: list[answerability.RetrievalPair] = []
        try:
            populate_started = time.perf_counter()
            _, assertion_to_memory = await answerability.baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            populate_seconds = time.perf_counter() - populate_started

            for item, source_case in zip(
                selected_queries,
                selected_source_cases,
                strict=True,
            ):
                query = str(item["query"])
                tick = time.perf_counter_ns()
                query_vector = embedder.encode_query(query)
                query_embedding_ms.append((time.perf_counter_ns() - tick) / 1_000_000)

                tick = time.perf_counter_ns()
                first_stage = await retrieval.retrieve_first_stage(
                    query,
                    query_vector,
                    eligibility=RetrievalEligibility.cloud_context(),
                    limit=answerability.QWEN_CANDIDATE_WINDOW,
                )
                retrieval_ms.append((time.perf_counter_ns() - tick) / 1_000_000)
                if not first_stage:
                    raise RuntimeError(f"no eligible candidates for {item['case_id']}")

                tick = time.perf_counter_ns()
                reranked = reranker.rerank(query, first_stage)
                rerank_ms.append((time.perf_counter_ns() - tick) / 1_000_000)
                if not reranked:
                    raise RuntimeError(
                        f"reranker returned nothing for {item['case_id']}"
                    )

                top = reranked[0]
                top_memory_id = assertion_to_memory.get(
                    top.candidate.assertion.assertion_id
                )
                if top_memory_id is None:
                    raise RuntimeError(f"unknown top assertion for {item['case_id']}")
                if top_memory_id != source_case.get("top_memory_id"):
                    raise RuntimeError(
                        "Qwen top memory did not reproduce the batch-120 source artifact for "
                        f"{item['case_id']}: {top_memory_id} != "
                        f"{source_case.get('top_memory_id')}"
                    )

                expected = item.get("expected_memory_id")
                positive_top1_correct = (
                    item["label"] == "release" and top_memory_id == expected
                )
                if item["label"] == "release" and not positive_top1_correct:
                    raise RuntimeError(
                        f"selected positive no longer has the expected Top-1 memory: "
                        f"{item['case_id']}"
                    )
                margin = (
                    float(top.rerank_score - reranked[1].rerank_score)
                    if len(reranked) > 1
                    else None
                )
                pairs.append(
                    answerability.RetrievalPair(
                        case_id=str(item["case_id"]),
                        split=str(item["split"]),
                        label=str(item["label"]),
                        expected_memory_id=(
                            str(expected) if expected is not None else None
                        ),
                        language=str(item["language"]),
                        category=str(item["category"]),
                        query=query,
                        top_memory_id=top_memory_id,
                        top_document=top.candidate.assertion.normalized_text,
                        positive_top1_correct=positive_top1_correct,
                        rerank_score=float(top.rerank_score),
                        rerank_margin=margin,
                    )
                )
        finally:
            await worker.close()

        peak_cuda_bytes = (
            int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None
        )

    def _timing(values: list[float]) -> dict[str, float]:
        ordered = sorted(values)
        return {
            "p50": round(ordered[len(ordered) // 2], 4),
            "max": round(max(ordered), 4),
        }

    return pairs, {
        "fixture_population_and_document_embedding_seconds": round(populate_seconds, 4),
        "query_embedding_ms": _timing(query_embedding_ms),
        "first_stage_retrieval_ms": _timing(retrieval_ms),
        "rerank_ms": _timing(rerank_ms),
        "qwen_peak_cuda_bytes": peak_cuda_bytes,
    }


def _comparison_rows(
    selected_source_cases: list[dict[str, Any]],
    pairs: list[answerability.RetrievalPair],
    judgments: list[semantic.GeminiJudgeItem],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_case, pair, judgment in zip(
        selected_source_cases,
        pairs,
        judgments,
        strict=True,
    ):
        expected_decision = "release" if pair.label == "release" else "abstain"
        prior_decision = str(source_case["gemini_decision"])
        if prior_decision != expected_decision:
            raise RuntimeError(
                f"selected source case was not previously correct: {pair.case_id}"
            )
        rows.append(
            {
                "case_id": pair.case_id,
                "label": pair.label,
                "category": pair.category,
                "language": pair.language,
                "top_memory_id": pair.top_memory_id,
                "positive_top1_correct": pair.positive_top1_correct,
                "prior_batch_size": 120,
                "prior_batch_decision": prior_decision,
                "expected_single_instance_decision": expected_decision,
                "single_instance_decision": judgment.decision,
                "single_instance_failure_mode": judgment.failure_mode,
                "preserved_correct_decision": judgment.decision == expected_decision,
            }
        )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    preserved = sum(bool(row["preserved_correct_decision"]) for row in rows)
    regressions = len(rows) - preserved
    by_language: dict[str, dict[str, int]] = {}
    for language in TARGET_LANGUAGES:
        language_rows = [row for row in rows if row["language"] == language]
        by_language[language] = {
            "cases": len(language_rows),
            "preserved": sum(
                bool(row["preserved_correct_decision"]) for row in language_rows
            ),
            "regressions": sum(
                not bool(row["preserved_correct_decision"]) for row in language_rows
            ),
        }

    by_family: dict[str, dict[str, int]] = {}
    for family in ("positive", *ORDINARY_ABSTAIN_CATEGORIES):
        family_rows = [
            row
            for row in rows
            if (family == "positive" and row["label"] == "release")
            or (family != "positive" and row["category"] == family)
        ]
        by_family[family] = {
            "cases": len(family_rows),
            "preserved": sum(
                bool(row["preserved_correct_decision"]) for row in family_rows
            ),
            "regressions": sum(
                not bool(row["preserved_correct_decision"]) for row in family_rows
            ),
        }

    return {
        "cases": len(rows),
        "positive_cases": sum(row["label"] == "release" for row in rows),
        "ordinary_abstain_cases": sum(row["label"] == "abstain" for row in rows),
        "preserved_correct_decisions": preserved,
        "regressions": regressions,
        "all_coverage_cells_correct_single_instance": regressions == 0,
        "by_language": by_language,
        "by_family": by_family,
    }


def _decision(
    coverage_summary: dict[str, Any],
    boundary_artifact: dict[str, Any],
) -> dict[str, Any]:
    boundary_summary = boundary_artifact["summary"]
    boundary_ok = bool(
        boundary_summary.get("all_target_boundaries_abstained_single_instance")
    )
    coverage_ok = bool(coverage_summary["all_coverage_cells_correct_single_instance"])
    return {
        "boundary_cells_correct": boundary.EXPECTED_CASE_COUNT if boundary_ok else 0,
        "coverage_cells_correct": (
            EXPECTED_CASE_COUNT
            if coverage_ok
            else int(coverage_summary["preserved_correct_decisions"])
        ),
        "combined_production_shape_cells": COMBINED_PRODUCTION_SHAPE_CELLS,
        "combined_all_cells_correct": boundary_ok and coverage_ok,
        "gemini_selected_for_v3_design": boundary_ok and coverage_ok,
        "v3_is_acceptance_complete": False,
        "phase45e_authorized": False,
    }


async def _run(
    *,
    source_path: Path,
    boundary_path: Path,
    device: str,
    gemini_rpm: float,
) -> dict[str, Any]:
    source = boundary._load_source_artifact(source_path)
    boundary_artifact = _load_boundary_artifact(boundary_path)
    selected = _select_coverage_cases(source)
    pairs, qwen_timing = await _retrieve_selected_pairs(device, selected)
    judgments, gemini_timing = await semantic._score_gemini(
        pairs,
        batch_size=GEMINI_BATCH_SIZE,
        concurrency=GEMINI_CONCURRENCY,
        rpm=gemini_rpm,
    )
    rows = _comparison_rows(selected, pairs, judgments)
    summary = _summary(rows)
    decision = _decision(summary, boundary_artifact)
    return {
        "status": "DEVELOPMENT_GEMINI_SINGLE_INSTANCE_COVERAGE_DIAGNOSTIC_COMPLETE",
        "purpose": (
            "Verify that production-shaped single-instance Gemini preserves the "
            "previously-correct positive and ordinary semantic-abstain decisions "
            "before authorizing a fresh V3 design"
        ),
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "source_artifact": str(source_path),
        "boundary_artifact": str(boundary_path),
        "selection": {
            "split": "validation",
            "positive_rule": (
                "lexicographically first previously-correct positive per language"
            ),
            "ordinary_abstain_rule": (
                "lexicographically first previously-correct case per frozen "
                "ordinary category/language cell"
            ),
            "languages": list(TARGET_LANGUAGES),
            "ordinary_abstain_categories": list(ORDINARY_ABSTAIN_CATEGORIES),
            "cases": EXPECTED_CASE_COUNT,
        },
        "models": {
            "embedding_model_id": answerability.QWEN3_EMBEDDING_MODEL_ID,
            "embedding_revision": answerability.QWEN3_EMBEDDING_REVISION,
            "embedding_dimension": answerability.QWEN3_EMBEDDING_CONTRACT.dimension,
            "reranker_model_id": answerability.QWEN3_RERANKER_MODEL_ID,
            "reranker_revision": answerability.QWEN3_RERANKER_REVISION,
            "candidate_window": answerability.QWEN_CANDIDATE_WINDOW,
            "gemini_model_id": semantic.GEMINI_MODEL_ID,
            "gemini_request_shape": "one query/document case per request",
        },
        "summary": summary,
        "decision": decision,
        "timing": {
            "qwen": qwen_timing,
            "gemini": gemini_timing,
        },
        "cases": rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE_ARTIFACT_DEFAULT,
        help="completed batch-120 semantic-judge artifact",
    )
    parser.add_argument(
        "--boundary",
        type=Path,
        default=BOUNDARY_ARTIFACT_DEFAULT,
        help="completed 15-case single-instance boundary artifact",
    )
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    output_path = args.output
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing diagnostic evidence: {output_path}"
        )
    result = asyncio.run(
        _run(
            source_path=args.source,
            boundary_path=args.boundary,
            device=args.device,
            gemini_rpm=args.gemini_rpm,
        )
    )
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print(f"STATUS: {result['status']}")
    print("SUMMARY: " + json.dumps(result["summary"], ensure_ascii=False))
    print("DECISION: " + json.dumps(result["decision"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
