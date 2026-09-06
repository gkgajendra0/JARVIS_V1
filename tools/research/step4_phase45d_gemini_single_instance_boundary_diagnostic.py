"""Development-only production-shape Gemini boundary diagnostic for Phase 4.5D.

The V2 corpus and the batch-120 semantic-judge artifact are exposed and retired from
acceptance. This diagnostic uses exactly 15 already-exposed V2 validation boundary
cases (five deterministic boundary categories x three languages), reproduces the same
eligible top-10 Qwen retrieval/rerank result, and asks Gemini to judge one case per
request. It exists only to determine whether the previous 120-instance request shape
confounded semantic-sufficiency behavior relative to production, where JARVIS judges
one live retrieval at a time.

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
import step4_phase45d_semantic_judge_bakeoff as semantic

from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)

SOURCE_ARTIFACT_DEFAULT = Path(".step4-phase45d-v2-semantic-judge-bakeoff-v1.json")
OUTPUT_DEFAULT = Path(
    ".step4-phase45d-v2-gemini-single-instance-boundary-diagnostic-v1.json"
)
TARGET_CATEGORIES = ("historical", "forgotten", "local_only", "secret", "untrusted")
TARGET_LANGUAGES = ("en", "hi", "hinglish")
EXPECTED_CASE_COUNT = len(TARGET_CATEGORIES) * len(TARGET_LANGUAGES)
GEMINI_BATCH_SIZE = 1
GEMINI_CONCURRENCY = 1
DEFAULT_GEMINI_RPM = 12.0


def _load_source_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"semantic-judge source artifact not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("semantic-judge source artifact is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("semantic-judge source artifact must be a JSON object")
    if payload.get("status") != "DEVELOPMENT_SEMANTIC_JUDGE_BAKEOFF_COMPLETE":
        raise RuntimeError(
            "semantic-judge source artifact did not complete successfully"
        )
    if payload.get("acceptance_evidence") is not False:
        raise RuntimeError("source artifact must remain development-only evidence")
    models = payload.get("models")
    if not isinstance(models, dict):
        raise TypeError("semantic-judge source artifact has no model metadata")
    gemini = models.get("gemini")
    if (
        not isinstance(gemini, dict)
        or gemini.get("model_id") != semantic.GEMINI_MODEL_ID
    ):
        raise RuntimeError(
            "source artifact Gemini model does not match frozen diagnostic"
        )
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 1800:
        raise RuntimeError(
            "semantic-judge source artifact must contain all 1,800 V2 cases"
        )
    return payload


def _select_boundary_cases(source: dict[str, Any]) -> list[dict[str, Any]]:
    cases = source.get("cases")
    if not isinstance(cases, list):
        raise TypeError("source artifact cases are missing")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in cases:
        if not isinstance(raw, dict) or raw.get("split") != "validation":
            continue
        category = raw.get("category")
        language = raw.get("language")
        if category in TARGET_CATEGORIES and language in TARGET_LANGUAGES:
            grouped[(str(category), str(language))].append(raw)

    selected: list[dict[str, Any]] = []
    for category in TARGET_CATEGORIES:
        for language in TARGET_LANGUAGES:
            matches = grouped.get((category, language), [])
            if not matches:
                raise RuntimeError(
                    f"missing V2 validation boundary case for {category}/{language}"
                )
            chosen = min(matches, key=lambda item: str(item.get("case_id", "")))
            if chosen.get("gemini_decision") != "release":
                raise RuntimeError(
                    "target diagnostic requires a prior batch-120 Gemini RELEASE for "
                    f"{category}/{language}"
                )
            selected.append(chosen)

    case_ids = [str(item.get("case_id")) for item in selected]
    if len(selected) != EXPECTED_CASE_COUNT or len(case_ids) != len(set(case_ids)):
        raise RuntimeError(
            "single-instance diagnostic selection is not exactly 15 unique cases"
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
    selected_ids = [str(item["case_id"]) for item in selected_source_cases]
    selected_queries: list[dict[str, Any]] = []
    for case_id in selected_ids:
        item = query_by_id.get(case_id)
        if item is None:
            raise RuntimeError(
                f"selected case is absent from frozen V2 corpus: {case_id}"
            )
        selected_queries.append(item)

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    with tempfile.TemporaryDirectory(
        prefix="jarvis-phase45d-gemini-single-"
    ) as temp_dir:
        worker = answerability.baseline._connection_worker(
            Path(temp_dir) / "single-instance-boundary.db"
        )
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: answerability.baseline.NOW,
            assertion_id_factory=answerability.baseline._id_factory(
                "phase45d-gemini-single-assertion"
            ),
            operation_id_factory=answerability.baseline._id_factory(
                "phase45d-gemini-single-operation"
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
                "diagnostic must use the frozen JARVIS reranker instruction"
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
                        f"{item['case_id']}: {top_memory_id} != {source_case.get('top_memory_id')}"
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
                        expected_memory_id=None,
                        language=str(item["language"]),
                        category=str(item["category"]),
                        query=query,
                        top_memory_id=top_memory_id,
                        top_document=top.candidate.assertion.normalized_text,
                        positive_top1_correct=False,
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
        array = sorted(values)
        return {
            "p50": round(array[len(array) // 2], 4),
            "max": round(max(array), 4),
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
        rows.append(
            {
                "case_id": pair.case_id,
                "category": pair.category,
                "language": pair.language,
                "top_memory_id": pair.top_memory_id,
                "prior_batch_size": 120,
                "prior_batch_decision": source_case["gemini_decision"],
                "single_instance_decision": judgment.decision,
                "single_instance_failure_mode": judgment.failure_mode,
                "flipped_to_abstain": (
                    source_case["gemini_decision"] == "release"
                    and judgment.decision == "abstain"
                ),
            }
        )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    release_count = sum(row["single_instance_decision"] == "release" for row in rows)
    abstain_count = len(rows) - release_count
    flips = sum(bool(row["flipped_to_abstain"]) for row in rows)

    by_category: dict[str, dict[str, int]] = {}
    for category in TARGET_CATEGORIES:
        category_rows = [row for row in rows if row["category"] == category]
        by_category[category] = {
            "cases": len(category_rows),
            "single_release": sum(
                row["single_instance_decision"] == "release" for row in category_rows
            ),
            "single_abstain": sum(
                row["single_instance_decision"] == "abstain" for row in category_rows
            ),
        }

    by_language: dict[str, dict[str, int]] = {}
    for language in TARGET_LANGUAGES:
        language_rows = [row for row in rows if row["language"] == language]
        by_language[language] = {
            "cases": len(language_rows),
            "single_release": sum(
                row["single_instance_decision"] == "release" for row in language_rows
            ),
            "single_abstain": sum(
                row["single_instance_decision"] == "abstain" for row in language_rows
            ),
        }

    return {
        "cases": len(rows),
        "prior_batch_release": sum(
            row["prior_batch_decision"] == "release" for row in rows
        ),
        "single_instance_release": release_count,
        "single_instance_abstain": abstain_count,
        "release_to_abstain_flips": flips,
        "batching_confound_observed": flips > 0,
        "all_target_boundaries_abstained_single_instance": release_count == 0,
        "by_category": by_category,
        "by_language": by_language,
    }


async def _run(
    *,
    source_path: Path,
    device: str,
    gemini_rpm: float,
) -> dict[str, Any]:
    source = _load_source_artifact(source_path)
    selected = _select_boundary_cases(source)
    pairs, qwen_timing = await _retrieve_selected_pairs(device, selected)
    judgments, gemini_timing = await semantic._score_gemini(
        pairs,
        batch_size=GEMINI_BATCH_SIZE,
        concurrency=GEMINI_CONCURRENCY,
        rpm=gemini_rpm,
    )
    rows = _comparison_rows(selected, pairs, judgments)
    summary = _summary(rows)
    return {
        "status": "DEVELOPMENT_GEMINI_SINGLE_INSTANCE_BOUNDARY_DIAGNOSTIC_COMPLETE",
        "purpose": (
            "Determine whether the 120-instance Gemini semantic-judge request shape "
            "confounded boundary decisions relative to production single-instance use"
        ),
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "source_artifact": str(source_path),
        "source_status": source["status"],
        "selection": {
            "split": "validation",
            "categories": list(TARGET_CATEGORIES),
            "languages": list(TARGET_LANGUAGES),
            "cases": EXPECTED_CASE_COUNT,
            "selection_rule": (
                "lexicographically first already-exposed V2 validation case for each "
                "frozen category/language cell; every selected source decision must be RELEASE"
            ),
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
        "interpretation": {
            "if_any_flip": (
                "At least one RELEASE->ABSTAIN flip demonstrates request-shape sensitivity; "
                "do not treat batch-120 decisions as equivalent to production single-instance behavior."
            ),
            "if_zero_release": (
                "Zero single-instance releases on all 15 targeted boundary cells supports "
                "continuing Gemini as a production-shape development candidate, but does not "
                "constitute V3 acceptance or authorize Phase 4.5E."
            ),
            "if_any_single_release": (
                "Any remaining single-instance RELEASE is a genuine targeted boundary miss "
                "for this diagnostic and requires architecture review before V3."
            ),
        },
        "timing": {"qwen": qwen_timing, "gemini": gemini_timing},
        "cases": rows,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE_ARTIFACT_DEFAULT))
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gemini_rpm <= 0:
        raise ValueError("Gemini RPM must be positive")
    source_path = Path(args.source)
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing diagnostic evidence: {output_path}"
        )

    result = asyncio.run(
        _run(
            source_path=source_path,
            device=args.device,
            gemini_rpm=args.gemini_rpm,
        )
    )
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", result["status"])
    print("SUMMARY:", json.dumps(result["summary"]))
    print(
        "DECISION:",
        json.dumps(
            {
                "batching_confound_observed": result["summary"][
                    "batching_confound_observed"
                ],
                "all_target_boundaries_abstained_single_instance": result["summary"][
                    "all_target_boundaries_abstained_single_instance"
                ],
            }
        ),
    )


if __name__ == "__main__":
    main()
