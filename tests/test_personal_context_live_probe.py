"""PI-1C always-off unless explicit owner command; no provider calls in CI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jarvis.voice.personal_context_live_probe import evaluate_probe_response

_ROOT = Path(__file__).resolve().parents[1]


def test_probe_accepts_only_observed_fictional_canary() -> None:
    assert (
        evaluate_probe_response("The synthetic codeword is brackenfold.")
        == "SYNTHETIC_CANARY_OBSERVED"
    )
    assert evaluate_probe_response("unknown") == "CANARY_NOT_OBSERVED"
    assert evaluate_probe_response("") == "NO_TEXT_TRANSCRIPT"


def test_probe_default_requires_opt_in_and_uses_no_network() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            str(_ROOT / "tools" / "research" / "pi1c_live_context_probe.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert process.returncode == 0
    payload = json.loads(process.stdout)
    assert payload["status"] == "OFFLINE_PREFLIGHT_ONLY"
    assert payload["owner_memory_access"] is False
    assert payload["would_run_live_provider"] is False
    assert payload["context_delivery_test"] == "NOT_RUN"
