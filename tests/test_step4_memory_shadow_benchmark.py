"""Contract tests only: never claim these authored cases are blind acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from tools.research.step4_memory_shadow_benchmark import (
    DEFAULT_CASES,
    evaluate,
    load_cases,
    load_challenger,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/research/step4_memory_shadow_benchmark.py"


def test_development_benchmark_scores_real_incumbent_and_shadow_policies() -> None:
    corpus, digest = load_cases(DEFAULT_CASES)
    result = evaluate(corpus)
    assert len(digest) == 64
    assert result["acceptance_status"] == "NOT_ACCEPTANCE_DEVELOPMENT_FIXTURES"
    assert result["counts"] == {"candidate": 18, "context": 24}
    assert result["language_counts"] == {
        "en": 14,
        "hi": 14,
        "hinglish": 14,
    }

    incumbent = result["candidate_results"]["incumbent_policy"]
    shadow = result["candidate_results"]["shadow_review"]
    assert incumbent["evaluated"] == 18
    assert shadow["evaluated"] == 18
    assert shadow["correct"] >= incumbent["correct"]
    assert shadow["correct"] == 18
    assert incumbent["correct"] < 18

    no_memory = result["context_results"]["no_memory"]
    scope_probe = result["context_results"]["scope_probe"]
    assert no_memory["evaluated"] == 24
    assert scope_probe["evaluated"] == 24
    assert no_memory["true_useful"] == 0
    assert no_memory["unsafe_steering_influence"] == 0
    assert scope_probe["true_useful"] > 0
    # This is why exact task-scope matching is NOT sufficient to enable injection.
    assert scope_probe["unsafe_steering_influence"] > 0
    assert scope_probe["unnecessary_influence"] > 0


def test_challenger_labels_are_evaluated_only_if_submitted(tmp_path: Path) -> None:
    corpus, _ = load_cases(DEFAULT_CASES)
    challenger_file = tmp_path / "predictions.json"
    challenger_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "simulated_offline_challenger",
                "candidate_predictions": {"c01": "review", "c07": "skip"},
                "context_signals": {
                    "x01": "helpful",
                    "x02": "essential",
                    "x04": "steering_risk",
                },
            }
        ),
        encoding="utf-8",
    )
    challenge = load_challenger(challenger_file, corpus)
    report = evaluate(corpus, challenge)
    assert report["candidate_results"]["simulated_offline_challenger"][
        "evaluated"
    ] == 2
    utility = report["context_results"]["simulated_offline_challenger"]
    assert utility["evaluated"] == 3
    assert utility["true_useful"] == 2
    assert utility["unsafe_steering_influence"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda obj: obj.update(schema_version=2),
        lambda obj: obj["cases"].append(deepcopy(obj["cases"][0])),
        lambda obj: obj["cases"][0].update(language="unknown"),
        lambda obj: obj["cases"][0].update(expected="approved_write"),
        lambda obj: obj["cases"][18].update(expected="private_release"),
        lambda obj: obj.update(purpose="blind_acceptance"),
    ],
)
def test_corpus_validation_rejects_malformed_cases(
    tmp_path: Path, mutation
) -> None:
    corpus, _ = load_cases(DEFAULT_CASES)
    mutated = deepcopy(corpus)
    mutation(mutated)
    file_path = tmp_path / "invalid.json"
    file_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(file_path)


def test_challenger_rejects_wrong_case_ids_and_labels(tmp_path: Path) -> None:
    corpus, _ = load_cases(DEFAULT_CASES)
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "bad_submitter",
                "context_signals": {"c01": "helpful"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid challenger context"):
        load_challenger(path, corpus)


def test_export_unlabeled_view_never_exposes_gold_labels() -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--unlabeled-view"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(run.stdout)
    assert len(output["cases"]) == 42
    assert all("expected" not in item for item in output["cases"])
    assert output["schema_version"] == 1


def test_cli_reports_dev_only_markers_and_never_claims_live_success() -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(run.stdout)
    assert report["acceptance_status"] == "NOT_ACCEPTANCE_DEVELOPMENT_FIXTURES"
    assert "not live model extraction" in report["benchmark_scope"]
    assert "no_memory" in report["context_results"]
    assert "hindsight" not in report["context_results"]
    assert "jev" not in report["context_results"]
