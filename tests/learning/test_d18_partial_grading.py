"""D18 allows an explicitly partial answer; D25 separately requires paging."""

from types import SimpleNamespace

import pytest

from jarvis.voice import personal_memory_acceptance as acceptance


@pytest.mark.asyncio
@pytest.mark.parametrize("paged", [False, True])
async def test_d18_accepts_partial_or_complete_paging_but_keeps_manual_review(paged):
    tools = [
        {
            "tool": "read_personal_context_for_question",
            "result": {
                "facts": [],
                "paging": {"total": 11, "this_page": {"to": 8}, "complete": False},
            },
        }
    ]
    if paged:
        tools.append(
            {
                "tool": "read_personal_context_for_question",
                "result": {"facts": [], "paging": {"total": 11, "complete": True}},
            }
        )
    context = SimpleNamespace(
        replies={
            "s11-01": {
                "tools": tools,
                "answer": "11 saved; here are 8. Would you like the rest?",
            }
        }
    )
    checks = await acceptance.check_d18(context, None)
    assert not [c for c in checks if c["status"] == acceptance.FAIL]
    assert checks[-1]["status"] == acceptance.REVIEW
    assert checks[-1]["detail"]["pagination_exercised"] is paged


@pytest.mark.asyncio
async def test_d18_incomplete_attempted_paging_still_fails():
    read = {
        "tool": "read_personal_context_for_question",
        "result": {
            "facts": [],
            "paging": {"total": 11, "this_page": {"to": 8}, "complete": False},
        },
    }
    context = SimpleNamespace(
        replies={"s11-01": {"tools": [read, read], "answer": "All done."}}
    )
    checks = await acceptance.check_d18(context, None)
    assert any(c["status"] == acceptance.FAIL for c in checks)
