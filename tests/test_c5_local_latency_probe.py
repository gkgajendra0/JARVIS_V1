from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c5_local_latency_probe.py"


def _load_module():
    name = "jarvis_c5_local_latency_probe_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_profiles_cover_qwen_thinking_modes_and_phi() -> None:
    module = _load_module()

    assert [(item.name, item.model, item.think) for item in module.PROFILES] == [
        ("qwen-thinking-on", "qwen3.5:4b", True),
        ("qwen-thinking-off", "qwen3.5:4b", False),
        ("phi4-mini", "phi4-mini", None),
    ]


def test_summarize_profile_separates_cold_and_warm_latency() -> None:
    module = _load_module()
    profile = module.Profile("test", "test-model", False)
    runs = [
        {
            "run_kind": "cold",
            "wall_ms": 1200.0,
            "first_content_token_ms": 800.0,
            "load_duration_ms": 500.0,
            "eval_tokens_per_second": 40.0,
            "structured_valid": True,
            "thinking_chars": 0,
            "gpu_after_request": {"memory_used_mib": 4000},
        },
        {
            "run_kind": "warm",
            "wall_ms": 300.0,
            "first_content_token_ms": 100.0,
            "load_duration_ms": 5.0,
            "eval_tokens_per_second": 60.0,
            "structured_valid": True,
            "thinking_chars": 0,
            "gpu_after_request": {"memory_used_mib": 4100},
        },
        {
            "run_kind": "warm",
            "wall_ms": 500.0,
            "first_content_token_ms": 140.0,
            "load_duration_ms": 5.0,
            "eval_tokens_per_second": 64.0,
            "structured_valid": False,
            "thinking_chars": 90,
            "gpu_after_request": {"memory_used_mib": 4200},
        },
    ]

    row = module._summarize_profile(profile, runs)

    assert row["cold_wall_ms"] == 1200.0
    assert row["warm_wall_ms_median"] == 400.0
    assert row["warm_first_content_ms_median"] == 120.0
    assert row["warm_eval_tokens_per_second_median"] == 62.0
    assert row["structured_valid_runs"] == 2
    assert row["max_thinking_chars"] == 90
    assert row["peak_gpu_used_mib"] == 4200


def test_ns_to_ms_rejects_non_integer_metrics() -> None:
    module = _load_module()

    assert module._ns_to_ms(1_500_000) == 1.5
    assert module._ns_to_ms(None) is None
    assert module._ns_to_ms("100") is None
