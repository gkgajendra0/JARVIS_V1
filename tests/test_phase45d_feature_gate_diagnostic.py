from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "research" / "step4_phase45d_feature_gate_diagnostic.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "step4_phase45d_feature_gate_diagnostic", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_evidence_excludes_language_and_category() -> None:
    module = _load()

    assert "language" not in module.FULL_EVIDENCE.feature_names
    assert "category" not in module.FULL_EVIDENCE.feature_names
    assert module.FULL_EVIDENCE.feature_names == (
        "rerank_score",
        "rerank_margin",
        "dense_score",
        "fused_score",
        "lexical_hit",
        "reciprocal_lexical_rank",
        "reciprocal_dense_rank",
    )


def test_feature_row_encodes_missing_lexical_rank_fail_closed() -> None:
    module = _load()
    case = {
        "rerank_score": 7.0,
        "rerank_margin": 5.0,
        "dense_score": 0.8,
        "fused_score": 0.02,
        "lexical_rank": None,
        "dense_rank": 2,
    }

    row = module._feature_row(case, module.FULL_EVIDENCE)

    assert row == [7.0, 5.0, 0.8, 0.02, 0.0, 0.0, 0.5]


def test_empirical_operating_point_prefers_recall_at_precision_floor() -> None:
    module = _load()
    probabilities = np.asarray([0.99, 0.95, 0.8, 0.2], dtype=np.float64)
    labels = np.asarray([1, 1, 0, 0], dtype=np.int64)

    result = module._best_empirical_operating_point(probabilities, labels)

    assert result["found"] is True
    assert result["best"]["tp"] == 2
    assert result["best"]["fp"] == 0
    assert result["best"]["precision"] == 1.0
    assert result["best"]["recall"] == 1.0


def test_empirical_operating_point_can_fail() -> None:
    module = _load()
    probabilities = np.asarray([0.9, 0.8], dtype=np.float64)
    labels = np.asarray([0, 1], dtype=np.int64)

    result = module._best_empirical_operating_point(probabilities, labels)

    assert result["found"] is False
    assert result["best"] is None
