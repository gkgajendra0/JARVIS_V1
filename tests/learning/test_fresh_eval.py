import asyncio
import json

import pytest
from tools.research import personal_auto_learning_fresh_eval as fresh


def test_fresh_contract_is_full_balanced_separate_and_zero_network(tmp_path):
    inputs, gold = fresh.load_frozen_v4()
    assert len(inputs["episodes"]) == 90
    assert sum(e["answer_subset"] for e in inputs["episodes"]) == 30
    assert all("expected" not in e for e in inputs["episodes"])
    for language in ("en", "hi", "hinglish"):
        selected = [e for e in inputs["episodes"] if e["language"] == language]
        assert len(selected) == 30
        assert sorted(
            gold["episodes"][e["id"]]["answer_kind"]
            for e in selected
            if e["answer_subset"]
        ) == sorted(["relevant"] * 6 + ["irrelevant"] * 2 + ["unknown_relation"] * 2)
    result = fresh.run_fresh_eval(tmp_path / "contract")
    assert result["single_send_calls"] == 0
    assert result["accepted"] is False
    assert result["status"] == "contract_checked"


@pytest.mark.parametrize("cap", [-1, 267, True, 1.5])
def test_fresh_stage_cannot_expand_authorized_remaining_cap(tmp_path, cap):
    with pytest.raises(ValueError):
        fresh.run_fresh_eval(tmp_path / "invalid", max_single_send_calls=cap)


def test_context_mismatch_is_not_hidden_by_correct_write():
    row = {
        "id": "hi-example",
        "status": "completed",
        "facts": [{"text": "old speaker"}],
    }
    gold = {
        "episodes": {
            "hi-example": {
                "context_contains": ["new speaker"],
                "context_excludes": ["old speaker"],
            }
        }
    }
    assert fresh.context_mismatches([row], gold) == ["hi-example"]


def test_answer_failure_preserves_semantic_row_and_stops_before_next_case(
    tmp_path, monkeypatch
):
    visited = []

    async def episode(e, adapter, endpoint, directory):
        visited.append(e["id"])
        return {"id": e["id"], "status": "completed", "predictions": [], "facts": []}

    class Answer:
        def __init__(self):
            self.last_failure = {"kind": "RateLimitError", "status": 429}

        async def _request(self, *args):
            raise RuntimeError("provider unavailable")

    class Learn:
        last_failure = None

    monkeypatch.setattr(fresh.base, "_episode", episode)
    episodes = [
        {
            "id": "en-first",
            "turns": ["fictional"],
            "question": "unknown?",
            "answer_subset": True,
        },
        {
            "id": "en-never",
            "turns": ["another"],
            "question": "unknown?",
            "answer_subset": False,
        },
    ]
    result = asyncio.run(
        fresh.execute_cases(
            {"episodes": episodes},
            tmp_path,
            fresh.base.AttemptBudget(2),
            Learn(),
            Answer(),
            "fictional-endpoint",
            spacing=0,
        )
    )
    assert visited == ["en-first"]
    assert result[0][0]["status"] == "completed"
    assert result[0][0]["answer_status"] == "unavailable"
    assert result[1] == []
    artifact = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert artifact["rows"][0]["answer_status"] == "unavailable"


def test_provider_setup_failure_still_publishes_unavailable_summary(
    tmp_path, monkeypatch
):
    async def unavailable(*args):
        raise RuntimeError("fictional unavailable configuration")

    monkeypatch.setattr(fresh, "_provider_run", unavailable)
    result = fresh.run_fresh_eval(tmp_path / "failure", allow_provider=True)
    assert result["accepted"] is False
    assert result["single_send_calls"] == 0
    assert result["unavailable"] == 1
    assert result["unrun"] == 89
    artifact = json.loads(
        (tmp_path / "failure" / "summary.json").read_text(encoding="utf-8")
    )
    assert artifact["rows"][0]["reason"] == "resources_unavailable"
