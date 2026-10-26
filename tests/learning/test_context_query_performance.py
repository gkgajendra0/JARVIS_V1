"""Bounded local tool latency measurement; no provider or owner database access."""

import asyncio
import json
import platform
from time import perf_counter

import pytest
from context_query_helpers import context_session, seed_item


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 8, 32])
async def test_local_context_query_and_guard_latency(learning, size):
    vehicle = await seed_item(learning)
    for i in range(size - 1):
        await seed_item(learning, f"Phone{i}", "device")
    report = {
        "records": size,
        "samples_per_path": 30,
        "warmups_per_path": 5,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "paths": {},
    }
    for path in ("legacy", "query"):
        values = []
        delays = []
        done = asyncio.Event()

        async def heartbeat(done=done, delays=delays):
            while not done.is_set():
                start = perf_counter()
                await asyncio.sleep(0.001)
                delays.append(max(0, (perf_counter() - start - 0.001) * 1000))

        pulse = asyncio.create_task(heartbeat())
        try:
            for iteration in range(35):
                async with context_session(learning, "My City?") as (session, _, _):
                    start = perf_counter()
                    if path == "legacy":
                        catalog = await session.catalog()
                        packet = await session.read(
                            catalog["catalog_id"],
                            [catalog["facets"].index(vehicle.predicate)],
                        )
                    else:
                        packet = await session.query_for_question(
                            [
                                {
                                    "scope_key": "owned_item.vehicle",
                                    "target_quote": "City",
                                }
                            ]
                        )
                    assert (
                        packet["status"] == "selected"
                        and "City" in packet["facts"][0]["text"]
                    )
                    assert await session.allow_audio()
                    if iteration >= 5:
                        values.append((perf_counter() - start) * 1000)
        finally:
            done.set()
            await pulse
        ordered = sorted(values)
        report["paths"][path] = {
            "p50_ms": ordered[14],
            "p95_ms": ordered[28],
            "max_ms": max(ordered),
            "heartbeat_max_delay_ms": max(delays, default=0),
        }
    print("PI3_MEASUREMENT=" + json.dumps(report, sort_keys=True))
