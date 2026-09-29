from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c5_local_runtime_probe.py"


def _load_module():
    name = "jarvis_c5_local_runtime_probe_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_detects_ready_owner_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    monkeypatch.setattr(module.shutil, "which", lambda name: f"C:/fake/{name}.exe")

    class _Result:
        returncode = 0
        stdout = "ollama version 0.22.0\n"
        stderr = ""

    monkeypatch.setattr(module, "_run", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda url, timeout=3.0: (
            {"version": "0.22.0"}
            if url.endswith("/api/version")
            else (
                {
                    "models": [
                        {
                            "name": "qwen3.5:4b",
                            "size": 3_400_000_000,
                            "details": {
                                "parameter_size": "4.7B",
                                "quantization_level": "Q4_K_M",
                                "family": "qwen35",
                            },
                        }
                    ]
                }
                if url.endswith("/api/tags")
                else {"models": []}
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "_nvidia_snapshot",
        lambda: [
            {
                "index": 0,
                "name": "NVIDIA GeForce RTX 5060 Ti",
                "driver_version": "999.99",
                "memory_total_mib": 8192,
                "memory_used_mib": 2048,
                "memory_free_mib": 6144,
                "utilization_gpu_percent": 10,
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "_jarvis_processes",
        lambda: [{"pid": 12000, "name": "python.exe", "cmdline": "jarvis voice"}],
    )

    report = module.build_report(ollama_host="http://127.0.0.1:11434")

    assert report["ready_for_model_pull"] is True
    assert report["ollama"]["server_reachable"] is True
    assert report["ollama"]["installed_models"][0]["name"] == "qwen3.5:4b"
    assert report["gpu"][0]["memory_total_mib"] == 8192
    assert report["jarvis_processes"][0]["pid"] == 12000


def test_ollama_model_projection_keeps_vram_and_context_fields() -> None:
    module = _load_module()

    models = module._ollama_models(
        {
            "models": [
                {
                    "name": "phi4-mini:latest",
                    "size": 2_500_000_000,
                    "size_vram": 2_700_000_000,
                    "context_length": 4096,
                    "details": {
                        "parameter_size": "3.8B",
                        "quantization_level": "Q4_K_M",
                        "family": "phi3",
                    },
                }
            ]
        }
    )

    assert models == [
        {
            "name": "phi4-mini:latest",
            "size_bytes": 2_500_000_000,
            "size_vram_bytes": 2_700_000_000,
            "context_length": 4096,
            "parameter_size": "3.8B",
            "quantization_level": "Q4_K_M",
            "family": "phi3",
            "processor": None,
            "expires_at": None,
        }
    ]
