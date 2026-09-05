from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "research" / "step4_phase45_embedding_bakeoff.py"


def _source() -> str:
    return HARNESS.read_text(encoding="utf-8")


def test_phase45_bakeoff_reuses_existing_fixed_retrieval_corpus() -> None:
    source = _source()
    assert "import step4_memory_retrieval_bakeoff as base" in source
    assert '"corpus_source": "step4_memory_retrieval_bakeoff.CORPUS/QUERIES"' in source
    assert "CORPUS = (" not in source
    assert "QUERIES = (" not in source


def test_phase45_bakeoff_is_narrow_two_model_comparison() -> None:
    source = _source()
    assert 'model_id="Qwen/Qwen3-Embedding-0.6B"' in source
    assert 'model_id="google/embeddinggemma-300m"' in source
    assert 'default="qwen,embeddinggemma"' in source
    assert "BAAI/bge-m3" not in source


def test_phase45_bakeoff_preserves_existing_rrf_and_256d_contract() -> None:
    source = _source()
    assert "TRUNCATE_DIM = 256" in source
    assert "RRF_K = hybrid.RRF_K" in source
    assert "FTS_WINDOW = hybrid.FTS_WINDOW" in source
    assert "hybrid._rrf_fuse" in source
    assert "base._fts_rank" in source


def test_phase45_bakeoff_remains_research_only() -> None:
    source = _source()
    assert "no production retrieval" in source
    assert "MemoryService" not in source
    assert "save_machine_settings" not in source
    assert "sqlite-vector" not in source
    assert "sqlite_vec" not in source
