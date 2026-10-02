"""Owner-machine smoke for admitted bounded Phase-9 JEV runtime wiring.

This check is intentionally side-effect free:
- it does not start the voice runtime, DBOS, cameras, or audio;
- it does not issue a JEV decision/API request;
- it validates the persisted owner-machine admission and constructs the same
  bounded advisor used by production composition.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from jarvis.capability_acquisition.jev import (
    JevAcquisitionCandidateAdvisor,
    build_jev_acquisition_candidate_advisor,
)
from jarvis.config import JarvisConfig
from jarvis.machine_config import default_machine_config_path


def probe_jev_runtime_admission() -> dict[str, object]:
    config = JarvisConfig.from_environment()

    if not config.work_orchestration_enabled:
        raise RuntimeError(
            "production JEV path is inactive because work orchestration is disabled"
        )
    if not config.jev_bounded_decisions_enabled:
        raise RuntimeError("bounded JEV decisions are not enabled")
    if not config.jev_benchmark_admitted:
        raise RuntimeError("JEV benchmark is not admitted")
    if config.jev_min_confidence != 0.95:
        raise RuntimeError(
            "owner-admitted JEV confidence threshold must be exactly 0.95"
        )

    report_text = str(config.jev_benchmark_report_path or "").strip()
    if not report_text:
        raise RuntimeError("JEV benchmark report path is missing")
    report_path = Path(report_text).expanduser().resolve()
    if not report_path.is_file():
        raise RuntimeError(f"JEV benchmark report is missing: {report_path}")

    credential_configured = bool(os.getenv("JEV_API_KEY", "").strip())
    if not credential_configured:
        raise RuntimeError("JEV_API_KEY is not available to this process")

    advisor = build_jev_acquisition_candidate_advisor(
        enabled=config.jev_bounded_decisions_enabled,
        benchmark_admitted=config.jev_benchmark_admitted,
        minimum_confidence=config.jev_min_confidence,
        model=config.jev_model,
        endpoint=config.jev_endpoint,
        benchmark_report_path=str(report_path),
    )
    if not isinstance(advisor, JevAcquisitionCandidateAdvisor):
        raise TypeError("production JEV advisor was not constructed")

    return {
        "status": "PASS",
        "work_orchestration_enabled": config.work_orchestration_enabled,
        "jev_bounded_decisions_enabled": config.jev_bounded_decisions_enabled,
        "jev_benchmark_admitted": config.jev_benchmark_admitted,
        "jev_min_confidence": config.jev_min_confidence,
        "jev_model": config.jev_model,
        "jev_endpoint": config.jev_endpoint,
        "jev_benchmark_report_path": str(report_path),
        "machine_config_path": str(default_machine_config_path()),
        "credential_configured": credential_configured,
        "advisor_constructed": True,
        "api_calls_made": 0,
    }


def main() -> int:
    try:
        result = probe_jev_runtime_admission()
    except Exception as exc:  # noqa: BLE001 - owner-machine smoke boundary
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "api_calls_made": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
