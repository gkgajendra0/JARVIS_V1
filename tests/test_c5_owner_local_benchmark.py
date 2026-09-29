from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c5_owner_local_benchmark.py"


def _load_module():
    name = "jarvis_c5_owner_local_benchmark_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_find_model_accepts_latest_alias() -> None:
    module = _load_module()

    model = module._find_model(
        [
            {"name": "phi4-mini:latest", "size_vram_bytes": 123},
            {"name": "qwen3.5:4b", "size_vram_bytes": 456},
        ],
        "phi4-mini",
    )

    assert model is not None
    assert model["name"] == "phi4-mini:latest"


def test_comparison_row_projects_benchmark_and_gpu_metrics() -> None:
    module = _load_module()
    benchmark = {
        "report": {
            "summaries": [
                {
                    "accuracy_over_covered": 0.9,
                    "coverage": 1.0,
                    "structured_output_failures": 1,
                    "unsafe_downgrades": 1,
                    "conservative_escalations": 2,
                    "latency_ms_p50": 500.0,
                    "latency_ms_p95": 900.0,
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "complete_api_cost_usd": 0.0,
                }
            ]
        }
    }

    row = module._comparison_row(
        "phi4-mini",
        benchmark,
        {
            "processor": "100% GPU",
            "size_vram_bytes": 2_700_000_000,
            "context_length": 4096,
        },
        [
            {
                "memory_used_mib": 4100,
                "memory_free_mib": 4051,
            }
        ],
    )

    assert row["model"] == "phi4-mini"
    assert row["accuracy_over_covered"] == 0.9
    assert row["structured_output_failures"] == 1
    assert row["unsafe_downgrades"] == 1
    assert row["api_cost_usd"] == 0.0
    assert row["ollama_processor"] == "100% GPU"
    assert row["gpu_memory_free_mib"] == 4051


def test_default_models_are_small_tier_a_candidates() -> None:
    module = _load_module()

    assert module.DEFAULT_MODELS == ("phi4-mini", "qwen3.5:4b")
