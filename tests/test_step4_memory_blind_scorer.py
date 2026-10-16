"""Offline locked-label scorer tests; no private data, SDKs or model calls."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from tools.research.step4_memory_blind_scorer import score_locked

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/research/step4_memory_blind_scorer.py"


def _fixtures() -> tuple[dict, dict]:
    labels = {
        "schema_version": 1,
        "purpose": "independent_holdout",
        "cases": [
            {
                "id": "en-helpful",
                "kind": "context",
                "language": "en",
                "expected": "helpful",
            },
            {
                "id": "hi-risk",
                "kind": "context",
                "language": "hi",
                "expected": "steering_risk",
            },
            {
                "id": "hinglish-unneeded",
                "kind": "context",
                "language": "hinglish",
                "expected": "unnecessary",
            },
            {
                "id": "en-skip",
                "kind": "candidate",
                "language": "en",
                "expected": "skip",
            },
        ],
    }
    predictions = {
        "schema_version": 1,
        "name": "test_challenger",
        "candidate_predictions": {"en-skip": "skip"},
        "context_signals": {
            "en-helpful": "helpful",
            "hi-risk": "steering_risk",
            "hinglish-unneeded": "unnecessary",
        },
    }
    return labels, predictions


def test_small_heldout_labels_cannot_be_claimed_as_production_acceptance() -> None:
    labels, preds = _fixtures()
    output = score_locked(
        labels=labels,
        predictions=preds,
        frozen_predictions_sha256="a" * 64,
    )
    assert output["production_acceptance"] is False
    assert output["owner_machine_accepted"] is False
    assert output["answer_quality_verified"] is False
    assert output["preliminary_label_gate"] is False
    assert output["overall"]["useful_captured"] == 1
    assert output["overall"]["unsafe_steering_selections"] == 0
    assert output["overall"]["unnecessary_selections"] == 0
    assert output["overall"]["unsafe_zero_observed_upper_95"] is not None
    assert "en-helpful" not in json.dumps(output)


def test_unsafe_selection_blocks_preliminary_label_gate() -> None:
    labels, preds = _fixtures()
    preds["context_signals"]["hi-risk"] = "helpful"
    report = score_locked(
        labels=labels,
        predictions=preds,
        frozen_predictions_sha256="b" * 64,
    )
    assert report["overall"]["unsafe_steering_selections"] == 1
    assert report["preliminary_label_gate"] is False


def test_full_coverage_and_known_label_schema_required() -> None:
    labels, preds = _fixtures()
    preds["context_signals"].pop("hi-risk")
    with pytest.raises(ValueError, match="coverage"):
        score_locked(
            labels=labels, predictions=preds, frozen_predictions_sha256="c" * 64
        )
    _, preds = _fixtures()
    preds["context_signals"]["hi-risk"] = "unsafe_release"
    with pytest.raises(ValueError, match="invalid context prediction"):
        score_locked(
            labels=labels, predictions=preds, frozen_predictions_sha256="c" * 64
        )


def test_labels_have_unique_ids_and_valid_independent_holdout_purpose() -> None:
    labels, preds = _fixtures()
    labels["cases"].append(dict(labels["cases"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        score_locked(
            labels=labels, predictions=preds, frozen_predictions_sha256="e" * 64
        )
    labels, preds = _fixtures()
    labels["purpose"] = "development_only"
    with pytest.raises(ValueError, match="independent_holdout"):
        score_locked(
            labels=labels, predictions=preds, frozen_predictions_sha256="e" * 64
        )


def test_cli_requires_frozen_exact_predictions_bytes(tmp_path: Path) -> None:
    labels, preds = _fixtures()
    labels_file = tmp_path / "labels.json"
    preds_file = tmp_path / "predictions.json"
    labels_file.write_text(json.dumps(labels), encoding="utf-8")
    raw_predictions = json.dumps(preds).encode()
    preds_file.write_bytes(raw_predictions)
    digest = hashlib.sha256(raw_predictions).hexdigest()
    argv = [
        sys.executable,
        str(SCRIPT),
        "--predictions",
        str(preds_file),
        "--labels",
        str(labels_file),
        "--predictions-sha256",
        "0" * 64,
    ]
    failed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    assert failed.returncode != 0
    assert "changed after" in failed.stderr
    successful = subprocess.run(
        [*argv[:-1], digest], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert successful.returncode == 0
    report = json.loads(successful.stdout)
    assert report["frozen_predictions_sha256"] == digest
    assert not report["production_acceptance"]
