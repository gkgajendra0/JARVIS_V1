from __future__ import annotations

import pytest

from jarvis.capability_acquisition.evaluation import run_replay_suite
from jarvis.capability_acquisition.external_acceptance import (
    Phase9ExternalAcceptanceError,
    load_external_acceptance,
    validate_external_acceptance,
)


def _external_payload() -> dict[str, object]:
    return {
        "schema": "phase9_external_acceptance.v1",
        "capability_id": "tv.control",
        "package_id": "tv.control.package",
        "package_version": "1.0.0",
        "package_digest": "a" * 64,
        "target_kind": "device",
        "target_identity": "living-room-tv",
        "operations": [
            {
                "operation": "power",
                "verified": True,
                "external_effect_observed": True,
                "observation": "TV changed from standby to powered on.",
                "evidence_refs": ["owner-machine:tv-power-observation"],
            }
        ],
        "effective_enabled_verified": True,
        "disable_rollback_verified": True,
        "owner_confirmed": True,
        "recorded_at": "2026-09-27T20:00:00+05:30",
        "source": "jarvis-owner-machine",
    }


def test_external_acceptance_requires_observed_real_effect() -> None:
    payload = _external_payload()
    payload["operations"][0]["external_effect_observed"] = False

    with pytest.raises(Phase9ExternalAcceptanceError, match="external effect"):
        validate_external_acceptance(payload)


def test_external_acceptance_rejects_secret_material() -> None:
    payload = _external_payload()
    payload["token"] = "must-never-be-recorded"

    with pytest.raises(Phase9ExternalAcceptanceError, match="secret field"):
        validate_external_acceptance(payload)


def test_external_acceptance_digest_is_stable_and_optional_digest_is_checked() -> None:
    first = validate_external_acceptance(_external_payload())
    second = validate_external_acceptance(_external_payload())

    assert first == second
    assert first.digest == second.digest
    assert len(first.digest) == 64

    payload = _external_payload()
    payload["evidence_digest"] = "f" * 64
    with pytest.raises(Phase9ExternalAcceptanceError, match="digest mismatch"):
        validate_external_acceptance(payload)


def test_external_acceptance_loader_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(Phase9ExternalAcceptanceError, match="unavailable"):
        load_external_acceptance(tmp_path / "missing.json")


def test_phase9_replay_has_24_green_cases(tmp_path) -> None:
    report = run_replay_suite(tmp_path / "phase9-replay")

    failures = {
        item.case_id: item.evidence for item in report.cases if not item.passed
    }
    assert report.status == "PASS", failures
    assert len(report.cases) == 24
    assert len(report.suite_digest) == 64
    assert len(report.phase7_suite_digest) == 64
    assert len(report.phase8_suite_digest) == 64
