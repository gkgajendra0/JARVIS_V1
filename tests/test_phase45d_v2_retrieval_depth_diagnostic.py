from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[ModuleType, ModuleType]:
    inserted = str(RESEARCH)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)
    _load(
        "step4_phase45d_abstention_calibration",
        RESEARCH / "step4_phase45d_abstention_calibration.py",
    )
    cases = _load(
        "step4_phase45d_final_v2_cases",
        RESEARCH / "step4_phase45d_final_v2_cases.py",
    )
    diagnostic = _load(
        "step4_phase45d_v2_retrieval_depth_diagnostic",
        RESEARCH / "step4_phase45d_v2_retrieval_depth_diagnostic.py",
    )
    return cases, diagnostic


def _row(
    diagnostic: ModuleType,
    *,
    case_id: str,
    expected_rank: int | None,
    top_by_depth: dict[int, str],
    expected: str = "memory_expected",
) -> object:
    return diagnostic.PositiveDiagnostic(
        case_id=case_id,
        split="validation",
        language="hi",
        category="cross_lingual",
        relation="region",
        expected_memory_id=expected,
        expected_first_stage_rank=expected_rank,
        reranked_top_memory_by_depth=top_by_depth,
        query_embedding_ms=1.0,
        retrieval_ms=2.0,
        rerank_top20_ms=3.0,
    )


def test_depth_contract_is_development_only_and_wider_than_v2() -> None:
    cases, diagnostic = _modules()

    assert diagnostic.RETRIEVAL_DEPTHS == (3, 5, 10, 20, 50, 100)
    assert diagnostic.RERANK_DEPTHS == (3, 5, 10, 20)
    assert max(diagnostic.RERANK_DEPTHS) <= max(diagnostic.RETRIEVAL_DEPTHS)
    assert diagnostic.QWEN3_EMBEDDING_CONTRACT.dimension == 256
    assert diagnostic.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-retrieval-depth-diagnostic-v1.json"
    )

    positives = [item for item in cases.build_payload()["queries"] if item["label"] == "release"]
    assert len(positives) == 900


def test_depth_metrics_distinguish_candidate_recall_from_reranked_top1() -> None:
    _, diagnostic = _modules()
    expected = "memory_expected"
    rows = [
        _row(
            diagnostic,
            case_id="a",
            expected_rank=2,
            expected=expected,
            top_by_depth={3: expected, 5: expected, 10: expected, 20: expected},
        ),
        _row(
            diagnostic,
            case_id="b",
            expected_rank=7,
            expected=expected,
            top_by_depth={
                3: "wrong",
                5: "wrong",
                10: expected,
                20: expected,
            },
        ),
        _row(
            diagnostic,
            case_id="c",
            expected_rank=30,
            expected=expected,
            top_by_depth={3: "wrong", 5: "wrong", 10: "wrong", 20: "wrong"},
        ),
        _row(
            diagnostic,
            case_id="d",
            expected_rank=None,
            expected=expected,
            top_by_depth={3: "wrong", 5: "wrong", 10: "wrong", 20: "wrong"},
        ),
    ]

    metrics = diagnostic._depth_metrics(rows)

    assert metrics["first_stage"]["3"]["recall"] == 0.25
    assert metrics["first_stage"]["10"]["recall"] == 0.5
    assert metrics["first_stage"]["50"]["recall"] == 0.75
    assert metrics["first_stage"]["100"]["recall"] == 0.75
    assert metrics["reranked"]["3"]["top1_accuracy"] == 0.25
    assert metrics["reranked"]["10"]["top1_accuracy"] == 0.5
    assert metrics["missing_expected_at_max_retrieval_depth"] == ["d"]


def test_public_case_omits_query_and_timing_payload() -> None:
    _, diagnostic = _modules()
    row = _row(
        diagnostic,
        case_id="case",
        expected_rank=4,
        top_by_depth={3: "wrong", 5: "memory_expected", 10: "memory_expected", 20: "memory_expected"},
    )

    public = diagnostic._public_case(row)

    assert public["expected_first_stage_rank"] == 4
    assert public["reranked_top_memory_by_depth"]["5"] == "memory_expected"
    assert "query_embedding_ms" not in public
    assert "retrieval_ms" not in public
    assert "rerank_top20_ms" not in public
