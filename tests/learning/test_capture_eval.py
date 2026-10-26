import pytest
from tools.research import personal_auto_learning_capture_eval as evaluation


def test_capture_subset_defaults_to_zero_network_and_cannot_accept_release(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        evaluation, "_provider_cases", lambda *a: pytest.fail("network entered")
    )
    result = evaluation.run_capture_eval(tmp_path / "out")
    assert result["status"] == "contract_checked"
    assert result["single_send_calls"] == 0 and result["unrun"] == 45
    assert result["accepted"] is False


def test_capture_subset_preserves_prior_reserve_and_hard_cap(tmp_path):
    with pytest.raises(ValueError):
        evaluation.run_capture_eval(tmp_path / "out", max_single_send_calls=66)
    with pytest.raises(ValueError):
        evaluation.run_capture_eval(tmp_path / "out2", max_single_send_calls=-1)


def test_capture_subset_is_frozen_separate_from_exposed_v1_and_gold(tmp_path):
    inputs, gold = evaluation.load_frozen_capture()
    assert len(inputs["episodes"]) == 45
    assert {
        lang: sum(e["language"] == lang for e in inputs["episodes"])
        for lang in ["en", "hi", "hinglish"]
    } == {"en": 15, "hi": 15, "hinglish": 15}
    assert all("expected" not in e for e in inputs["episodes"])
    assert all(not e["answer_subset"] for e in inputs["episodes"])
    assert len(gold["episodes"]) == 45
    changed = tmp_path / "changed.json"
    changed.write_text(
        evaluation.INPUT.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="hash"):
        evaluation.load_frozen_capture(inputs_path=changed)


def test_preliminary_floor_is_not_ninety_case_release_acceptance():
    rows = [
        {
            "id": f"{lang}-test-{i}",
            "status": "completed",
            "predictions": [
                {
                    "category": "goal",
                    "action": "create",
                    "text": "objective",
                    "state": "active",
                }
            ],
        }
        for lang in ["en", "hi", "hinglish"]
        for i in range(15)
    ]
    gold = {
        "episodes": {
            r["id"]: {
                "expected": [
                    {
                        "category": "goal",
                        "action": "create",
                        "contains": ["objective"],
                        "state": "active",
                    }
                ]
            }
            for r in rows
        }
    }
    scores = evaluation.capture_scores(rows, gold)
    assert scores["preliminary_semantic_floor"] is True
    assert scores["quality_floor_pass"] is False
