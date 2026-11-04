"""Offline diagnostic of production archive/tools/packet paths; no model calls."""

import asyncio
import json
import os
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_project_conversation_store import event, setup_store

from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_context import build_project_context
from jarvis.voice.project_memory_tools import ProjectMemoryTools


@pytest.mark.parametrize("size", [20, 100, 200])
@pytest.mark.parametrize("shared_keyword", [False, True])
@pytest.mark.parametrize("query", ["Jimny", "Jimny chose"])
@pytest.mark.parametrize("padding", [0, 1000])
def test_scaling_probe(tmp_path, authority_parts, size, shared_keyword, query, padding):
    async def scenario():
        _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        try:
            for index in range(size):
                text = (
                    "I chose the Jimny for the Nepal trip."
                    if index == 0
                    else (
                        "Jimny discussion: check a different accessory later."
                        if shared_keyword
                        else "Packing discussion: check another accessory later."
                    )
                )
                value = event(f"probe-{index:04d}", text=text)
                value = replace(
                    value,
                    accepted_at=value.accepted_at + timedelta(seconds=index),
                    request_id=f"request-{index:04d}",
                    text=value.text + "x" * padding,
                )
                material = store.append_material(selection, value, index)
                await store.append_event(
                    selection,
                    value,
                    permit=permit("admit", material, value),
                    expected_revision=index,
                )
                issuer.release_source(grant, value.event_id)
            started = time.perf_counter()
            snapshot = await access.snapshot(selection, project_wide=True)
            initial, initial_ids, initial_bound = build_project_context(snapshot)
            initial_ms = (time.perf_counter() - started) * 1000
            tools = ProjectMemoryTools(
                access,
                selection=selection,
                request_id="new-question",
                is_current=lambda: True,
            )
            started = time.perf_counter()
            found = await tools.search_conversation_memory(selection.project_id, query)
            final, final_ids, final_bound = build_project_context(
                snapshot, extra_sources=found.sources
            )
            search_ms = (time.perf_counter() - started) * 1000
            row = {
                "events": size,
                "shared_keyword": shared_keyword,
                "query": query,
                "padding": padding,
                "snapshot_sources": len(snapshot.sources),
                "snapshot_status": snapshot.status,
                "initial_sources": len(initial_ids),
                "initial_bytes": len(initial.encode()),
                "initial_byte_bound": initial_bound,
                "initial_has_old_decision": "probe-0000" in initial_ids,
                "search_sources": len(found.sources),
                "search_status": found.status,
                "search_has_old_decision": any(
                    s.event.event_id == "probe-0000" for s in found.sources
                ),
                "final_sources": len(final_ids),
                "final_bytes": len(final.encode()),
                "final_byte_bound": final_bound,
                "final_has_old_decision": "probe-0000" in final_ids,
                "snapshot_and_build_ms": initial_ms,
                "search_and_build_ms": search_ms,
                "provider_calls": 0,
            }
            assert initial_bound <= 6000 and final_bound <= 6000
            assert len(snapshot.sources) == min(size, 32)
            # Specific queries must recover old decisions; this is not answer grading.
            if not shared_keyword:
                assert row["final_has_old_decision"]
            if shared_keyword and size >= 100:
                if query == "Jimny chose":
                    assert row["search_has_old_decision"]
                    assert row["final_has_old_decision"]
                else:
                    assert not row["search_has_old_decision"]
            return row
        finally:
            await reader.close()
            await writer.close()

    row = asyncio.run(scenario())
    if target := os.environ.get("PR303_PROBE_OUTPUT"):
        with Path(target).open("a", encoding="utf-8") as output:
            output.write(json.dumps(row) + "\n")
