import asyncio

import pytest
from tools.research.personal_auto_learning_eval import AttemptBudget
from tools.research.personal_learning_bounded_recovery import recover_remaining


def test_three_health_checks_wait_in_chunks_and_never_start_unhealthy_segments():
    waits, probes, segments = [], [], []
    budget = AttemptBudget(239)

    async def wait(seconds):
        assert 0 < seconds <= 30
        waits.append(seconds)

    async def health(index):
        probes.append((index, sum(waits)))
        budget.take()
        return False

    async def segment(episodes, index):
        segments.append(index)
        return []

    result = asyncio.run(
        recover_remaining(
            [{"id": "en-new"}],
            [],
            budget=budget,
            health=health,
            segment=segment,
            wait=wait,
        )
    )
    assert probes == [(1, 60), (2, 180), (3, 420)]
    assert not segments
    assert result["opportunities_used"] == 3
    assert result["unrun_ids"] == ["en-new"]
    assert budget.attempts == 3


def test_unavailable_and_failed_answer_ids_are_never_replayed():
    episodes = [{"id": x} for x in ["old-failed", "a", "b", "c"]]
    prior = [
        {"id": "old-failed", "status": "completed", "answer_status": "unavailable"}
    ]
    budget = AttemptBudget(239)
    visits = []

    async def wait(seconds):
        pass

    async def health(index):
        budget.take()
        return True

    async def segment(remaining, index):
        visits.append([e["id"] for e in remaining])
        budget.take()
        return [{"id": remaining[0]["id"], "status": "unavailable"}]

    result = asyncio.run(
        recover_remaining(
            episodes, prior, budget=budget, health=health, segment=segment, wait=wait
        )
    )
    assert visits == [["a", "b", "c"], ["b", "c"], ["c"]]
    assert result["rows"][0] == prior[0]
    assert not result["unrun_ids"]


def test_exhausted_cap_after_health_never_starts_segment():
    budget = AttemptBudget(1)

    async def wait(seconds):
        pass

    async def health(index):
        budget.take()
        return True

    async def segment(remaining, index):
        pytest.fail("no budget remains")

    result = asyncio.run(
        recover_remaining(
            [{"id": "new"}],
            [],
            budget=budget,
            health=health,
            segment=segment,
            wait=wait,
        )
    )
    assert result["opportunities_used"] == 1
    assert budget.attempts == 1


def test_recovery_cannot_expand_239_remaining_cap():
    with pytest.raises(ValueError):
        asyncio.run(
            recover_remaining(
                [], [], budget=AttemptBudget(240), health=None, segment=None
            )
        )


def test_segment_cannot_return_an_exposed_id():
    budget = AttemptBudget(239)

    async def wait(seconds):
        pass

    async def health(index):
        budget.take()
        return True

    async def segment(remaining, index):
        return [{"id": "old", "status": "completed"}]

    with pytest.raises(ValueError, match="unattempted"):
        asyncio.run(
            recover_remaining(
                [{"id": "old"}, {"id": "new"}],
                [{"id": "old", "status": "unavailable"}],
                budget=budget,
                health=health,
                segment=segment,
                wait=wait,
            )
        )
