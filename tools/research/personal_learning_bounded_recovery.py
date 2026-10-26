"""Owner-approved finite recovery for fictional qualification, not product retries."""

from __future__ import annotations

import asyncio

RECOVERY_DELAYS = (60, 120, 240)
MAX_REMAINING_SENDS = 239


async def recover_remaining(
    episodes, prior_rows, *, budget, health, segment, wait=asyncio.sleep, observer=None
):
    if (
        type(budget.maximum) is not int
        or not 0 <= budget.maximum <= MAX_REMAINING_SENDS
    ):
        raise ValueError("recovery cannot expand the239send envelope")
    ids = [e["id"] for e in episodes]
    rows = list(prior_rows)
    seen = {r["id"] for r in rows}
    if len(ids) != len(set(ids)) or len(seen) != len(rows) or not seen <= set(ids):
        raise ValueError("unique known input/previous IDs required")
    cycles = []
    reason = "opportunities_exhausted"

    def report(event, cycle):
        if observer:
            observer(
                {
                    "event": event,
                    "cycle": cycle,
                    "single_send_calls": budget.attempts,
                    "attempted_ids": [r["id"] for r in rows],
                    "opportunities_used": len(cycles),
                }
            )

    for cycle, delay in enumerate(RECOVERY_DELAYS, 1):
        remaining = [e for e in episodes if e["id"] not in seen]
        if not remaining:
            reason = "all_inputs_attempted"
            break
        if budget.attempts >= budget.maximum:
            reason = "budget_exhausted"
            break
        entry = {"cycle": cycle, "declared_wait_seconds": delay}
        cycles.append(entry)
        report("wait_started", cycle)
        left = delay
        while left:
            part = min(30, left)
            await wait(part)
            left -= part
        report("health_started", cycle)
        healthy = await health(cycle)
        entry["healthy"] = healthy is True
        report("health_returned" if healthy is True else "health_unavailable", cycle)
        if healthy is not True:
            continue
        if budget.attempts >= budget.maximum:
            reason = "budget_exhausted"
            break
        new_rows = await segment(remaining, cycle)
        returned = [r["id"] for r in new_rows]
        allowed = [e["id"] for e in remaining]
        if len(set(returned)) != len(returned) or returned != allowed[: len(returned)]:
            raise ValueError("segment must return only unattempted IDs in frozen order")
        if not new_rows:
            reason = "empty_segment"
            break
        rows.extend(new_rows)
        seen.update(returned)
        entry["new_attempted_ids"] = returned
        report("segment_stopped", cycle)
    unrun = [e["id"] for e in episodes if e["id"] not in seen]
    if not unrun:
        reason = "all_inputs_attempted"
    elif budget.attempts >= budget.maximum:
        reason = "budget_exhausted"
    return {
        "rows": rows,
        "cycles": cycles,
        "opportunities_used": len(cycles),
        "unrun_ids": unrun,
        "stop_reason": reason,
        "accepted": False,
    }
