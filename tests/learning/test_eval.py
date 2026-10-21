import json
from pathlib import Path

import pytest
from tools.research import personal_auto_learning_eval as evaluation

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "benchmarks/personal_auto_learning_v1.json"
GOLD = ROOT / "benchmarks/personal_auto_learning_v1_gold.json"


def test_default_is_zero_network_and_never_quality_acceptance(tmp_path, monkeypatch):
    monkeypatch.setattr(
        evaluation,
        "_provider_cohort",
        lambda *args: pytest.fail("network path entered"),
    )
    summary = evaluation.run_learning_eval(INPUT, GOLD, tmp_path / "results")
    assert summary.status == "contract_checked" and summary.provider_attempts == 0
    assert summary.completed == 0 and not summary.accepted
    assert summary.unrun == 90


def test_fixed_manifest_rejects_input_or_gold_leakage(tmp_path):
    changed = tmp_path / INPUT.name
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    data["episodes"][0]["expected"] = "save"
    changed.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest|gold"):
        evaluation.run_learning_eval(changed, GOLD, tmp_path / "results")


def test_attempt_budget_is_shared_and_hard_bounded():
    budget = evaluation.AttemptBudget(2)
    budget.take()
    budget.take()
    with pytest.raises(evaluation.ProviderBudgetExceeded):
        budget.take()
    assert budget.attempts == 2
    with pytest.raises(ValueError):
        evaluation.AttemptBudget(271)


def test_partial_unavailable_run_is_not_correct_abstention():
    rows = [{"id": "en-01", "status": "unavailable", "predictions": []}]
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    result = evaluation.score_rows(rows, gold)
    assert result["completed"] == 0 and result["unavailable"] == 1
    assert result["true_positive"] == 0 and result["quality_floor_pass"] is False


def test_provider_payload_has_no_labels_or_seed_contracts():
    payload = evaluation.answer_payload("Why did I buy it?", [{"text": "I own a bike"}])
    assert set(payload) == {"question", "context"}
    assert "expected" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_attempt_cap_wraps_all_adapters_before_transport():
    calls = []

    class Adapter:
        async def _request(self, *args):
            calls.append(args)
            return {}

    budget = evaluation.AttemptBudget(2)
    extractor = evaluation._instrument(Adapter(), budget)
    answer = evaluation._instrument(Adapter(), budget)
    await extractor._request("extract", {}, {})
    await answer._request("answer", {}, {})
    with pytest.raises(evaluation.ProviderBudgetExceeded):
        await answer._request("again", {}, {})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_runner_uses_real_admission_and_only_fictional_database(
    learning, authority_parts, tmp_path, monkeypatch
):
    import jarvis.memory.runtime as memory_runtime
    from jarvis.memory.learning_contracts import (
        EvidenceSpan,
        LearningBatch,
        LearningCandidate,
        LearningResolution,
        LearningResolutionBatch,
    )

    monkeypatch.setattr(
        memory_runtime,
        "build_default_memory_runtime",
        lambda *a, **kw: pytest.fail("owner DB requested"),
    )
    authority_parts.broker._audit.close = lambda: None
    monkeypatch.setattr(
        evaluation,
        "_fictional_authority",
        lambda endpoint, directory: (authority_parts.broker, learning.authority),
    )

    class Adapter:
        provider = "gemini"

        async def extract(self, source):
            return LearningBatch(
                candidates=[
                    LearningCandidate(
                        category="owned_item",
                        kind="vehicle",
                        intent="new",
                        label=name,
                        value=name,
                        state="owned",
                        evidence=[
                            EvidenceSpan(
                                turn_id=source.turn_id, start=0, end=len(source.text)
                            )
                        ],
                    )
                    for name in ["Toyota Glanza", "TVS Ronin"]
                ]
            )

        async def resolve(self, source, batch, catalog):
            return LearningResolutionBatch(
                resolutions=[
                    LearningResolution(candidate_index=i, decision="new")
                    for i in range(len(batch.candidates))
                ]
            )

    episode = json.loads(INPUT.read_text(encoding="utf-8"))["episodes"][0]
    row = await evaluation._episode(episode, Adapter(), "unused", tmp_path)
    assert row["status"] == "completed" and row["committed_count"] == 2
    assert row["canonical_current_count"] == 2 and len(row["facts"]) == 2
    assert len(row["predictions"]) == 2
    assert (tmp_path / "fictional-memory.db").is_file()


def test_opa_policy_uses_one_adapter_protocol_version():
    import re

    versions = set(
        re.findall(
            r'"policy_version": "([^"]+)"',
            (ROOT / "policies/step3_authority.rego").read_text(),
        )
    )
    assert versions == {"step3-v1"}
