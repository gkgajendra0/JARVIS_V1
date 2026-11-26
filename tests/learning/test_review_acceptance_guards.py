"""Offline release-safety regressions; no provider or production data access."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarvis.voice import personal_memory_acceptance as acceptance
from jarvis.voice import project_memory_lab as entry


def _approved_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "approved" / "ledger.sqlite3"
    ledger.parent.mkdir()
    ledger.touch()
    monkeypatch.setattr(entry, "APPROVED_PAID_LEDGER", ledger, raising=False)
    return ledger


def test_paid_resume_refuses_replacement_ledger_before_any_request(
    tmp_path, monkeypatch
):
    ledger = _approved_ledger(tmp_path, monkeypatch)
    root = tmp_path / "lab"
    root.mkdir()
    (root / "acceptance-steps.jsonl").write_text(
        json.dumps({"lane": "paid", "paid_budget": {"ledger": str(ledger)}}) + "\n"
    )
    with pytest.raises(ValueError, match="ledger"):
        entry.check_lane(root, "paid", tmp_path / "replacement.sqlite3")


def test_new_paid_lab_cannot_start_an_independent_budget(tmp_path, monkeypatch):
    _approved_ledger(tmp_path, monkeypatch)
    root = tmp_path / "lab"
    root.mkdir()
    with pytest.raises(ValueError, match="ledger"):
        entry.check_lane(root, "paid", tmp_path / "new-budget.sqlite3")


def test_missing_shared_ledger_requires_explicit_budget_recovery(tmp_path, monkeypatch):
    ledger = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(entry, "APPROVED_PAID_LEDGER", ledger, raising=False)
    with pytest.raises(ValueError, match="ledger"):
        entry.check_lane(tmp_path, "paid", ledger)
    assert not ledger.exists()


def test_ledger_identity_is_pinned_before_first_model_step(tmp_path, monkeypatch):
    ledger = _approved_ledger(tmp_path, monkeypatch)
    root = tmp_path / "lab"
    root.mkdir()
    entry.check_lane(root, "paid", ledger)
    marker = root / "acceptance-lane.json"
    assert json.loads(marker.read_text())["ledger"] == str(ledger.resolve())
    # Losing an approval or crashing before the first step cannot lose this pin.
    monkeypatch.setattr(entry, "APPROVED_PAID_LEDGER", tmp_path / "other.sqlite3")
    with pytest.raises(ValueError, match="ledger"):
        entry.check_lane(root, "paid", tmp_path / "other.sqlite3")


def test_mixed_build_summary_keeps_each_case_and_attempt_provenance(tmp_path):
    old = acceptance.ResultLog(
        tmp_path,
        commit="a" * 40,
        hashes={},
        models={"evidence_kind": "scripted_offline"},
    )
    old.case({"case": "D17", "step_id": "story-18c", "status": "FAIL", "checks": []})
    new = acceptance.ResultLog(
        tmp_path,
        commit="b" * 40,
        hashes={},
        models={"evidence_kind": "controlled_text"},
    )
    new.case({"case": "D17", "step_id": "story-18c", "status": "PASS", "checks": []})
    runner = acceptance.AcceptanceRunner(tmp_path, SimpleNamespace(), new)
    summary = runner.write_summary()
    latest = summary["cases"]["D17"]
    earlier = summary["earlier_case_results"]["D17"][0]
    assert latest["source_commit"] == "b" * 40
    assert latest["evidence_kind"] == "controlled_text"
    assert earlier["source_commit"] == "a" * 40
    assert earlier["evidence_kind"] == "scripted_offline"
    assert summary["mixed_source_commits"] is True
    assert summary["source_commits"] == ["a" * 40, "b" * 40]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [False, True])
async def test_started_step_cannot_silently_repeat_side_effects(tmp_path, retry):
    log = acceptance.ResultLog(tmp_path, commit="a" * 40, hashes={}, models={})
    log.step({"group": "group", "step_id": "step", "status": "started", "attempt": 1})
    log.event(
        {
            "group": "group",
            "step_id": "step",
            "kind": "tool_result",
            "result": {"ok": True},
        }
    )
    runner = acceptance.AcceptanceRunner(
        tmp_path,
        SimpleNamespace(),
        log,
        groups_map={"group": (SimpleNamespace(id="step"),)},
        retry_interrupted=retry,
    )
    runner._run_group = AsyncMock()
    with pytest.raises(acceptance.AcceptanceInterrupted, match="reconcil"):
        await runner.run()
    runner._run_group.assert_not_awaited()
    assert log.step_states()["step"]["attempt"] == 1


def test_cross_build_recovery_requires_product_invariance_evidence(tmp_path):
    marker = tmp_path / "project-memory.marker"
    marker.write_text(
        json.dumps({"kind": entry.MARKER, "commit": "a" * 40}, sort_keys=True)
    )
    assert not entry._resume_allowed(tmp_path, marker, "b" * 40, True)


@pytest.mark.parametrize(
    "changed, expected",
    [
        ("src/jarvis/voice/project_memory_lab.py\n", True),
        ("src/jarvis/voice/personal_memory_acceptance.py\n", True),
        ("src/jarvis/memory/learning_runtime.py\n", False),
        ("src/jarvis/voice/project_memory_lab.py\nsrc/jarvis/voice/agent.py\n", False),
        ("policies/step3_authority.rego\n", False),
        ("pyproject.toml\n", False),
    ],
)
def test_recovery_does_not_accept_product_or_authority_changes(
    tmp_path, monkeypatch, changed, expected
):
    def diff(args, **_kwargs):
        assert args[args.index("--") + 1 :][:2] == ["src", "policies"]
        return changed

    monkeypatch.setattr(entry.subprocess, "check_output", diff)
    assert entry._same_product_source(tmp_path, "a" * 40, "b" * 40) is expected


def test_recovery_refuses_when_product_diff_cannot_be_verified(tmp_path, monkeypatch):
    def diff(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(entry.subprocess, "check_output", diff)
    assert not entry._same_product_source(tmp_path, "a" * 40, "b" * 40)


def test_recovery_compares_real_git_trees(tmp_path, monkeypatch):
    # The fixture is self-contained, including its Git configuration.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    repo = tmp_path / "source"
    repo.mkdir()

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert result.returncode == 0, result.stdout
        return result.stdout.strip()

    git("init")
    git("config", "user.name", "Fictional Test")
    git("config", "user.email", "test@example.invalid")
    product = repo / "src" / "jarvis" / "memory" / "example.py"
    product.parent.mkdir(parents=True)
    product.write_text("original = True\n")
    git("add", ".")
    git("commit", "-m", "fictional product")
    original = git("rev-parse", "HEAD")
    lab = repo / "src" / "jarvis" / "voice" / "project_memory_lab.py"
    lab.parent.mkdir()
    lab.write_text("lab_only = True\n")
    git("add", ".")
    git("commit", "-m", "fictional lab recovery")
    recovery = git("rev-parse", "HEAD")
    assert entry._same_product_source(repo, original, recovery)
    product.write_text("original = False\n")
    git("add", ".")
    git("commit", "-m", "fictional product change")
    changed_product = git("rev-parse", "HEAD")
    assert not entry._same_product_source(repo, original, changed_product)
