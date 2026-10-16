"""The preflight is strictly read-only and never exports credential text."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools.research.step4_memory_owner_preflight import report_readiness

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/research/step4_memory_owner_preflight.py"


def test_readonly_preflight_does_not_probe_gpu_or_run_models() -> None:
    report = report_readiness(check_gpu=False)
    assert report["mode"] == "READ_ONLY_NO_NETWORK_NO_MODEL"
    assert report["gpu"] == {"checked": False}
    assert report["model_calls"] == 0
    assert report["memory_writes"] == 0
    assert "operating_system" in report
    assert "pydantic" in report["packages"]


def test_credential_presence_only_never_exports_key_value() -> None:
    sentinel = "synthetic-test-secret-do-not-emit"
    before = os.environ.get("GOOGLE_API_KEY")
    try:
        os.environ["GOOGLE_API_KEY"] = sentinel
        report = report_readiness(check_gpu=False)
        assert report["credential_presence_not_values"]["google_api_key"] is True
        assert sentinel not in json.dumps(report)
    finally:
        if before is None:
            os.environ.pop("GOOGLE_API_KEY", None)
        else:
            os.environ["GOOGLE_API_KEY"] = before


def test_cli_default_requires_no_credentials_and_prints_json() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["model_calls"] == 0
    assert report["memory_writes"] == 0
    assert report["gpu"]["checked"] is False
