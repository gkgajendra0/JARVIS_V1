"""One-shot Phase 4.5D final V3 acceptance harness.

V3 uses a completely fresh corpus and the development-selected production shape:
canonical eligibility -> Qwen 256d hybrid top-10 -> frozen Qwen reranker -> one
query/document pair per Gemini 3.5 Flash-Lite Interactions request -> hard
RELEASE/ABSTAIN.

The policy is fixed before V3. Fresh calibration certifies precision using an exact
one-sided Clopper-Pearson lower bound. Validation Gemini calls are executed only if
all calibration hard gates pass. Validation never tunes anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import step4_phase45d_abstention_calibration as baseline
import step4_phase45d_answerability_verifier_bakeoff as answerability
import step4_phase45d_final_v3_cases as v3_cases
import step4_phase45d_semantic_judge_bakeoff as semantic

from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_CONTRACT,
    QWEN3_EMBEDDING_MODEL_ID,
    QWEN3_EMBEDDING_REVISION,
    SemanticEmbeddingStore,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.retrieval_models import (
    JARVIS_MEMORY_RERANK_INSTRUCTION,
    QWEN3_RERANKER_MODEL_ID,
    QWEN3_RERANKER_REVISION,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)

TARGET_PRECISION = 0.95
CONFIDENCE_LEVEL = 0.95
MIN_CALIBRATION_RELEASED_CASES = 59
MIN_POSITIVE_RECALL_AT_10 = 0.90
MIN_POSITIVE_TOP1_ACCURACY = 0.85
MIN_RELEASE_RECALL = 0.40
MIN_LANGUAGE_RELEASE_RECALL = 0.25
QWEN_CANDIDATE_WINDOW = 10
GEMINI_BATCH_SIZE = 1
GEMINI_CONCURRENCY = 1
DEFAULT_GEMINI_RPM = 12.0
EXPECTED_V3_PAYLOAD_SHA256 = "__FREEZE_AFTER_CORPUS_CI__"
OUTPUT_DEFAULT = Path(".step4-phase45d-final-v3-acceptance.json")
SECURITY_CATEGORIES = frozenset(v3_cases.SECURITY_BOUNDARY_CATEGORIES)


@dataclass(frozen=True, slots=True)
class RetrievedCase:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    query: str
    top_memory_id: str | None
    top_document: str | None
    positive_top1_correct: bool
    positive_hit_at_10: bool
    rerank_score: float | None
    rerank_margin: float | None
    query_embedding_ms: float
    retrieval_ms: float
    rerank_ms: float

    @property
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct

    def gemini_pair(self) -> answerability.RetrievalPair | None:
        if self.top_memory_id is None or self.top_document is None:
            return None
        return answerability.RetrievalPair(
            case_id=self.case_id,
            split=self.split,
            label=self.label,
            expected_memory_id=self.expected_memory_id,
            language=self.language,
            category=self.category,
            query=self.query,
            top_memory_id=self.top_memory_id,
            top_document=self.top_document,
            positive_top1_correct=self.positive_top1_correct,
            rerank_score=float(self.rerank_score or 0.0),
            rerank_margin=self.rerank_margin,
        )


@dataclass(frozen=True, slots=True)
class V3CaseResult:
    case_id: str
    split: str
    label: str
    expected_memory_id: str | None
    language: str
    category: str
    top_memory_id: str | None
    positive_top1_correct: bool
    positive_hit_at_10: bool
    rerank_score: float | None
    rerank_margin: float | None
    gemini_called: bool
    gemini_decision: str
    gemini_failure_mode: str
    query_embedding_ms: float
    retrieval_ms: float
    rerank_ms: float

    @property
    def safe_to_release(self) -> bool:
        return self.label == "release" and self.positive_top1_correct

    @property
    def released(self) -> bool:
        return self.gemini_decision == "release"


def _git_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 4)


def _environment(device: str) -> dict[str, Any]:
    try:
        import scipy
        import torch
        import torchvision
        import transformers
    except ImportError as exc:  # pragma: no cover - owner acceptance environment only
        raise RuntimeError("V3 acceptance dependencies are incomplete") from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA V3 acceptance requested but CUDA is unavailable")
    return {
        "device": device,
        "torch": str(torch.__version__),
        "torchvision": str(torchvision.__version__),
        "transformers": str(transformers.__version__),
        "scipy": str(scipy.__version__),
        "google_genai": _package_version("google-genai"),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_runtime": str(torch.version.cuda),
        "device_name": torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else None,
    }


def _ranking(cases: Sequence[V3CaseResult]) -> dict[str, Any]:
    positives = [case for case in cases if case.label == "release"]
    if not positives:
        return {
            "release_labels": 0,
            "positive_hit_at_10": 0,
            "positive_top1_correct": 0,
            "positive_recall_at_10": 0.0,
            "positive_top1_accuracy": 0.0,
        }
    hit10 = sum(case.positive_hit_at_10 for case in positives)
    top1 = sum(case.positive_top1_correct for case in positives)
    return {
        "release_labels": len(positives),
        "positive_hit_at_10": hit10,
        "positive_top1_correct": top1,
        "positive_recall_at_10": round(hit10 / len(positives), 6),
        "positive_top1_accuracy": round(top1 / len(positives), 6),
    }


def _policy(cases: Sequence[V3CaseResult]) -> dict[str, Any]:
    released = [case for case in cases if case.released]
    tp = sum(case.safe_to_release for case in released)
    fp = len(released) - tp
    positive_total = sum(case.label == "release" for case in cases)
    precision = tp / len(released) if released else 1.0
    recall = tp / positive_total if positive_total else 0.0
    false_cases = [case for case in released if not case.safe_to_release]
    false_by_category = Counter(case.category for case in false_cases)
    return {
        "tp": tp,
        "fp": fp,
        "released_cases": len(released),
        "precision": round(precision, 6),
        "positive_release_recall": round(recall, 6),
        "released_case_ids": [case.case_id for case in released],
        "false_release_case_ids": [case.case_id for case in false_cases],
        "false_releases_by_category": dict(sorted(false_by_category.items())),
        "security_boundary_release_case_ids": [
            case.case_id
            for case in released
            if case.category in SECURITY_CATEGORIES
        ],
    }


def _breakdown(cases: Sequence[V3CaseResult], attribute: str) -> dict[str, Any]:
    grouped: dict[str, list[V3CaseResult]] = defaultdict(list)
    for case in cases:
        grouped[str(getattr(case, attribute))].append(case)
    return {
        key: {
            "cases": len(values),
            "ranking": _ranking(values),
            "policy": _policy(values),
        }
        for key, values in sorted(grouped.items())
    }


def _precision_control(policy: dict[str, Any]) -> dict[str, Any]:
    try:
        from scipy.stats import binomtest
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("SciPy is required for V3 exact precision control") from exc

    tp = int(policy["tp"])
    released = int(policy["released_cases"])
    if released == 0:
        return {
            "method": "one_sided_clopper_pearson_exact",
            "target_precision": TARGET_PRECISION,
            "confidence_level": CONFIDENCE_LEVEL,
            "tp": tp,
            "released_cases": released,
            "minimum_releases_required": MIN_CALIBRATION_RELEASED_CASES,
            "minimum_releases_met": False,
            "lower_bound": 0.0,
            "pvalue": 1.0,
            "passes": False,
        }

    result = binomtest(
        tp,
        n=released,
        p=TARGET_PRECISION,
        alternative="greater",
    )
    interval = result.proportion_ci(
        confidence_level=CONFIDENCE_LEVEL,
        method="exact",
    )
    lower = float(interval.low)
    minimum_met = released >= MIN_CALIBRATION_RELEASED_CASES
    return {
        "method": "one_sided_clopper_pearson_exact",
        "target_precision": TARGET_PRECISION,
        "confidence_level": CONFIDENCE_LEVEL,
        "tp": tp,
        "released_cases": released,
        "minimum_releases_required": MIN_CALIBRATION_RELEASED_CASES,
        "minimum_releases_met": minimum_met,
        "lower_bound": round(lower, 9),
        "pvalue": round(float(result.pvalue), 12),
        "passes": minimum_met and lower >= TARGET_PRECISION,
    }


def _language_recall(cases: Sequence[V3CaseResult]) -> dict[str, float]:
    breakdown = _breakdown(cases, "language")
    return {
        language: float(breakdown[language]["policy"]["positive_release_recall"])
        for language in v3_cases.LANGUAGES
    }


def _calibration_acceptance(cases: Sequence[V3CaseResult]) -> dict[str, Any]:
    ranking = _ranking(cases)
    policy = _policy(cases)
    precision = _precision_control(policy)
    language_recall = _language_recall(cases)
    checks = {
        "positive_recall_at_10": (
            ranking["positive_recall_at_10"] >= MIN_POSITIVE_RECALL_AT_10
        ),
        "positive_top1_accuracy": (
            ranking["positive_top1_accuracy"] >= MIN_POSITIVE_TOP1_ACCURACY
        ),
        "minimum_released_cases": precision["minimum_releases_met"],
        "exact_precision_lower_bound": precision["passes"],
        "release_recall": policy["positive_release_recall"] >= MIN_RELEASE_RECALL,
        "language_release_recall": all(
            value >= MIN_LANGUAGE_RELEASE_RECALL for value in language_recall.values()
        ),
        "zero_security_boundary_releases": not policy[
            "security_boundary_release_case_ids"
        ],
    }
    return {
        "ranking": ranking,
        "policy": policy,
        "precision_control": precision,
        "language_release_recall": language_recall,
        "checks": checks,
        "pass": all(checks.values()),
    }


def _validation_acceptance(cases: Sequence[V3CaseResult]) -> dict[str, Any]:
    ranking = _ranking(cases)
    policy = _policy(cases)
    language_recall = _language_recall(cases)
    checks = {
        "positive_recall_at_10": (
            ranking["positive_recall_at_10"] >= MIN_POSITIVE_RECALL_AT_10
        ),
        "positive_top1_accuracy": (
            ranking["positive_top1_accuracy"] >= MIN_POSITIVE_TOP1_ACCURACY
        ),
        "zero_false_releases": policy["fp"] == 0,
        "release_recall": policy["positive_release_recall"] >= MIN_RELEASE_RECALL,
        "language_release_recall": all(
            value >= MIN_LANGUAGE_RELEASE_RECALL for value in language_recall.values()
        ),
        "zero_security_boundary_releases": not policy[
            "security_boundary_release_case_ids"
        ],
    }
    return {
        "ranking": ranking,
        "policy": policy,
        "language_release_recall": language_recall,
        "checks": checks,
        "pass": all(checks.values()),
    }


async def _retrieve_cases(
    items: Sequence[dict[str, Any]],
    *,
    retrieval: SemanticRetrievalService,
    embedder: Qwen3EmbeddingEncoder,
    reranker: Qwen3RetrievalReranker,
    assertion_to_memory: dict[str, str],
) -> list[RetrievedCase]:
    rows: list[RetrievedCase] = []
    for item in items:
        query = str(item["query"])
        label = str(item["label"])
        expected_raw = item.get("expected_memory_id")
        expected = str(expected_raw) if expected_raw is not None else None

        tick = time.perf_counter_ns()
        query_vector = embedder.encode_query(query)
        embedding_ms = (time.perf_counter_ns() - tick) / 1_000_000

        tick = time.perf_counter_ns()
        first_stage = await retrieval.retrieve_first_stage(
            query,
            query_vector,
            eligibility=RetrievalEligibility.cloud_context(),
            limit=QWEN_CANDIDATE_WINDOW,
        )
        retrieval_ms = (time.perf_counter_ns() - tick) / 1_000_000
        first_stage_ids = [
            assertion_to_memory.get(candidate.assertion.assertion_id)
            for candidate in first_stage
        ]
        hit10 = label == "release" and expected in first_stage_ids

        if not first_stage:
            rows.append(
                RetrievedCase(
                    case_id=str(item["case_id"]),
                    split=str(item["split"]),
                    label=label,
                    expected_memory_id=expected,
                    language=str(item["language"]),
                    category=str(item["category"]),
                    query=query,
                    top_memory_id=None,
                    top_document=None,
                    positive_top1_correct=False,
                    positive_hit_at_10=hit10,
                    rerank_score=None,
                    rerank_margin=None,
                    query_embedding_ms=embedding_ms,
                    retrieval_ms=retrieval_ms,
                    rerank_ms=0.0,
                )
            )
            continue

        tick = time.perf_counter_ns()
        reranked = reranker.rerank(query, first_stage)
        rerank_ms = (time.perf_counter_ns() - tick) / 1_000_000
        if not reranked:
            raise RuntimeError(f"reranker returned nothing for {item['case_id']}")
        top = reranked[0]
        top_memory_id = assertion_to_memory.get(top.candidate.assertion.assertion_id)
        if top_memory_id is None:
            raise RuntimeError(f"unknown Top-1 assertion for {item['case_id']}")
        margin = (
            float(top.rerank_score - reranked[1].rerank_score)
            if len(reranked) > 1
            else None
        )
        rows.append(
            RetrievedCase(
                case_id=str(item["case_id"]),
                split=str(item["split"]),
                label=label,
                expected_memory_id=expected,
                language=str(item["language"]),
                category=str(item["category"]),
                query=query,
                top_memory_id=top_memory_id,
                top_document=top.candidate.assertion.normalized_text,
                positive_top1_correct=label == "release" and top_memory_id == expected,
                positive_hit_at_10=hit10,
                rerank_score=float(top.rerank_score),
                rerank_margin=margin,
                query_embedding_ms=embedding_ms,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
            )
        )
    return rows


async def _judge_cases(
    cases: Sequence[RetrievedCase],
    *,
    gemini_rpm: float,
) -> tuple[list[V3CaseResult], dict[str, Any]]:
    callable_cases = [case for case in cases if case.gemini_pair() is not None]
    pairs = [case.gemini_pair() for case in callable_cases]
    typed_pairs = [pair for pair in pairs if pair is not None]
    if len(typed_pairs) != len(callable_cases):
        raise AssertionError("Gemini pair materialization changed unexpectedly")

    judgments: list[semantic.GeminiJudgeItem] = []
    timing: dict[str, Any] = {
        "model_id": semantic.GEMINI_MODEL_ID,
        "requests": 0,
        "cases": 0,
        "batch_size": GEMINI_BATCH_SIZE,
        "concurrency": GEMINI_CONCURRENCY,
        "rpm_cap": gemini_rpm,
    }
    if typed_pairs:
        judgments, timing = await semantic._score_gemini(
            typed_pairs,
            batch_size=GEMINI_BATCH_SIZE,
            concurrency=GEMINI_CONCURRENCY,
            rpm=gemini_rpm,
        )

    judgment_by_case = {
        case.case_id: judgment
        for case, judgment in zip(callable_cases, judgments, strict=True)
    }
    results: list[V3CaseResult] = []
    for case in cases:
        judgment = judgment_by_case.get(case.case_id)
        decision = judgment.decision if judgment is not None else "abstain"
        failure_mode = (
            judgment.failure_mode if judgment is not None else "missing_or_unsupported"
        )
        results.append(
            V3CaseResult(
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
                gemini_decision=decision,
                gemini_failure_mode=failure_mode,
                query_embedding_ms=case.query_embedding_ms,
                retrieval_ms=case.retrieval_ms,
                rerank_ms=case.rerank_ms,
            )
        )
    return results, timing


def _timing_summary(cases: Sequence[V3CaseResult]) -> dict[str, Any]:
    return {
        "query_embedding_p50_ms": _percentile(
            [case.query_embedding_ms for case in cases], 0.50
        ),
        "query_embedding_p95_ms": _percentile(
            [case.query_embedding_ms for case in cases], 0.95
        ),
        "retrieval_p50_ms": _percentile([case.retrieval_ms for case in cases], 0.50),
        "retrieval_p95_ms": _percentile([case.retrieval_ms for case in cases], 0.95),
        "rerank_p50_ms": _percentile([case.rerank_ms for case in cases], 0.50),
        "rerank_p95_ms": _percentile([case.rerank_ms for case in cases], 0.95),
    }


def _public_case(case: V3CaseResult) -> dict[str, Any]:
    return asdict(case) | {"safe_to_release": case.safe_to_release}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Torch is required for V3 acceptance") from exc

    payload = v3_cases.build_payload()
    payload_sha = v3_cases.payload_sha256(payload)
    if EXPECTED_V3_PAYLOAD_SHA256 == "__FREEZE_AFTER_CORPUS_CI__":
        raise RuntimeError("V3 payload SHA has not been frozen yet")
    if payload_sha != EXPECTED_V3_PAYLOAD_SHA256:
        raise RuntimeError(
            f"V3 payload SHA mismatch: {payload_sha} != {EXPECTED_V3_PAYLOAD_SHA256}"
        )

    environment = _environment(args.device)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    calibration_items = [
        item for item in payload["queries"] if item["split"] == "calibration"
    ]
    validation_items = [
        item for item in payload["queries"] if item["split"] == "validation"
    ]
    if len(calibration_items) != 360 or len(validation_items) != 360:
        raise RuntimeError("V3 split sizes changed unexpectedly")

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-v3-") as temp_dir:
        worker = baseline._connection_worker(Path(temp_dir) / "acceptance-v3.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: baseline.NOW,
            assertion_id_factory=baseline._id_factory("phase45d-v3-assertion"),
            operation_id_factory=baseline._id_factory("phase45d-v3-operation"),
        )
        embeddings = SemanticEmbeddingStore(worker, clock=lambda: baseline.NOW)
        retrieval = SemanticRetrievalService(worker)
        embedder = Qwen3EmbeddingEncoder(device=args.device)
        reranker = Qwen3RetrievalReranker(
            device=args.device,
            candidate_window=QWEN_CANDIDATE_WINDOW,
        )
        if reranker.instruction != JARVIS_MEMORY_RERANK_INSTRUCTION:
            raise RuntimeError("V3 must use the frozen JARVIS reranker instruction")

        try:
            started = time.perf_counter()
            _, assertion_to_memory = await baseline._populate_database(
                payload,
                lifecycle,
                embeddings,
                embedder,
            )
            population_seconds = time.perf_counter() - started

            calibration_retrieved = await _retrieve_cases(
                calibration_items,
                retrieval=retrieval,
                embedder=embedder,
                reranker=reranker,
                assertion_to_memory=assertion_to_memory,
            )
            calibration, calibration_gemini_timing = await _judge_cases(
                calibration_retrieved,
                gemini_rpm=args.gemini_rpm,
            )
            calibration_acceptance = _calibration_acceptance(calibration)

            validation_executed = bool(calibration_acceptance["pass"])
            validation: list[V3CaseResult] = []
            validation_gemini_timing: dict[str, Any] | None = None
            validation_acceptance: dict[str, Any] | None = None
            if validation_executed:
                validation_retrieved = await _retrieve_cases(
                    validation_items,
                    retrieval=retrieval,
                    embedder=embedder,
                    reranker=reranker,
                    assertion_to_memory=assertion_to_memory,
                )
                validation, validation_gemini_timing = await _judge_cases(
                    validation_retrieved,
                    gemini_rpm=args.gemini_rpm,
                )
                validation_acceptance = _validation_acceptance(validation)
        finally:
            await worker.close()

    qwen_peak_cuda_bytes = (
        int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    )
    if not calibration_acceptance["pass"]:
        status = "FAIL_CALIBRATION"
        final_pass = False
    else:
        if validation_acceptance is None:
            raise AssertionError("validation acceptance missing after calibration pass")
        final_pass = bool(validation_acceptance["pass"])
        status = "PASS_ACCEPTANCE" if final_pass else "FAIL_ACCEPTANCE"

    all_cases = calibration + validation
    return {
        "status": status,
        "purpose": "Phase 4.5D final V3 fixed-policy release acceptance",
        "final_acceptance_eligible": True,
        "acceptance_evidence": True,
        "development_data_used_for_tuning": False,
        "validation_used_for_tuning": False,
        "validation_executed": validation_executed,
        "phase45e_authorized": False,
        "phase45e_ready_for_closure": final_pass,
        "git_sha": _git_sha(),
        "environment": environment,
        "models": {
            "embedding": {
                "model_id": QWEN3_EMBEDDING_MODEL_ID,
                "revision": QWEN3_EMBEDDING_REVISION,
                "dimension": QWEN3_EMBEDDING_CONTRACT.dimension,
            },
            "reranker": {
                "model_id": QWEN3_RERANKER_MODEL_ID,
                "revision": QWEN3_RERANKER_REVISION,
                "candidate_window": QWEN_CANDIDATE_WINDOW,
                "instruction": JARVIS_MEMORY_RERANK_INSTRUCTION,
            },
            "semantic_judge": {
                "model_id": semantic.GEMINI_MODEL_ID,
                "api_surface": "interactions",
                "request_shape": "one_query_document_pair_per_request",
                "system_prompt": semantic.GEMINI_SYSTEM_PROMPT,
                "batch_size": GEMINI_BATCH_SIZE,
                "concurrency": GEMINI_CONCURRENCY,
                "store": False,
            },
        },
        "corpus": {
            "schema_version": v3_cases.V3_CORPUS_SCHEMA_VERSION,
            "sha256": payload_sha,
            "expected_sha256": EXPECTED_V3_PAYLOAD_SHA256,
            "documents": len(payload["documents"]),
            "queries": len(payload["queries"]),
            "calibration_labels": dict(
                Counter(item["label"] for item in calibration_items)
            ),
            "validation_labels": dict(
                Counter(item["label"] for item in validation_items)
            ),
            "calibration_languages": dict(
                Counter(item["language"] for item in calibration_items)
            ),
            "validation_languages": dict(
                Counter(item["language"] for item in validation_items)
            ),
            "fresh_vs_v2_exact_queries": True,
            "exchangeability_claim": False,
            "exchangeability_note": (
                "Synthetic V3 acceptance does not establish permanent exchangeability "
                "with future owner traffic; post-wiring shadow-labelled monitoring remains required."
            ),
        },
        "calibration": {
            "acceptance": calibration_acceptance,
            "languages": _breakdown(calibration, "language"),
            "categories": _breakdown(calibration, "category"),
            "gemini_timing": calibration_gemini_timing,
            "timing": _timing_summary(calibration),
        },
        "validation": (
            {
                "acceptance": validation_acceptance,
                "languages": _breakdown(validation, "language"),
                "categories": _breakdown(validation, "category"),
                "gemini_timing": validation_gemini_timing,
                "timing": _timing_summary(validation),
            }
            if validation_executed
            else None
        ),
        "timing": {
            "fixture_population_and_document_embedding_seconds": round(
                population_seconds, 4
            ),
            "qwen_peak_cuda_bytes": qwen_peak_cuda_bytes,
        },
        "acceptance": {
            "calibration_pass": bool(calibration_acceptance["pass"]),
            "validation_executed": validation_executed,
            "validation_pass": (
                bool(validation_acceptance["pass"])
                if validation_acceptance is not None
                else False
            ),
            "pass": final_pass,
        },
        "cases": [_public_case(case) for case in all_cases],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not math.isfinite(args.gemini_rpm) or args.gemini_rpm <= 0:
        raise ValueError("--gemini-rpm must be a positive finite number")
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(f"refusing to overwrite existing V3 evidence: {output_path}")
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
    print("VALIDATION_EXECUTED:", output["validation_executed"])
    if output["validation"] is not None:
        print(
            "VALIDATION:",
            json.dumps(output["validation"]["acceptance"], ensure_ascii=False),
        )
    print("ACCEPTANCE:", json.dumps(output["acceptance"], ensure_ascii=False))


if __name__ == "__main__":
    main()
