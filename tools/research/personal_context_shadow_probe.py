"""Offline shadow-contract probe, using only a disposable fictional memory store.

Run with the repository interpreter, e.g. python -I tools/research/personal_context_shadow_probe.py.
No model/network/hardware calls, production config reads, or live memory access.
The planner is controlled: this measures canonical contracts, not natural query quality.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.personal_context import (
    NativePersonalContextSource,
    PersonalContextRequest,
    PersonalContextSelector,
)
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.query_plan import (
    MemoryQueryIntent,
    MemoryQueryProposal,
    MemoryTemporalScope,
)
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker


class ControlledPlanner:
    """Fictional exact-facet proposals; no claim of model semantic evaluation."""

    def __init__(self):
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.resume.set()

    async def interpret(self, *, text, catalog):
        self.started.set()
        await self.resume.wait()
        if text != "What is my coffee preference?":
            return MemoryQueryProposal(intent=MemoryQueryIntent.UNSUPPORTED)
        return MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="personal",
            subject="owner",
            predicate="coffee_preference",
            subject_reference="my",
            requested_relation="coffee preference",
            temporal_scope=MemoryTemporalScope.CURRENT,
        )


async def run_probe(path: Path) -> dict:
    now = datetime.now(UTC)

    def connect():
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        MemoryMigrationRunner(clock=lambda: now).apply(connection)
        return connection

    worker = SerialConnectionWorker(connect, thread_name="fictional-shadow-probe")
    lifecycle = MemoryLifecycleService(worker)
    reader = CanonicalMemoryReader(worker)
    retrieval = SemanticRetrievalService(worker)
    planner = ControlledPlanner()
    source = NativePersonalContextSource(
        coordinator=MemoryQueryCoordinator(interpreter=planner, retrieval=retrieval),
        retrieval=retrieval,
        reader=reader,
    )
    conversation = ConversationSession(session_id="fictional-shadow-probe")
    conversation.start()
    requester = ["owner"]
    selector = PersonalContextSelector(
        source=source, conversation=conversation, requester=lambda: requester[0]
    )
    results = []

    def provenance(name, sensitivity=Sensitivity.STANDARD):
        return MemorySource(
            source_id=name,
            source_class=MemorySourceClass.OWNER_EXPLICIT,
            canonical_ref=f"fictional:{name}",
            observed_at=now,
            created_at=now,
            authority_class=AuthorityClass.OWNER_EXPLICIT,
            sensitivity=sensitivity,
        )

    def draft(value, sensitivity=Sensitivity.STANDARD):
        return SemanticAssertionDraft(
            subject_scope="personal",
            subject="owner",
            predicate="coffee_preference",
            value_type=ValueType.TEXT,
            value=value,
            normalized_text=f"Owner coffee preference: {value}",
            freshness_class=FreshnessClass.CHANGEABLE,
            sensitivity=sensitivity,
        )

    def request(text="What is my coffee preference?", destination="cloud"):
        turn = conversation.accept_turn(ConversationRole.USER, text)
        return PersonalContextRequest(
            turn_id=turn.turn_id,
            session_id=conversation.session_id,
            requester="owner",
            utterance=turn.text,
            as_of=datetime.now(UTC),
            destination=destination,
            budget_units=2048,
            deadline_ms=1000,
        )

    async def observe(name, query, expected):
        packet = await selector.select(query)
        results.append(
            {
                "scenario": name,
                "expected_status": expected,
                "passed": packet.status == expected,
                **packet.operational_summary(),
            }
        )
        return packet

    try:
        fact = await lifecycle.create(draft("decaf"), provenance("fictional-coffee"))
        await observe("off_by_default", request(), "abstain")
        selector.set_enabled(True)
        query = request()
        await observe("exact_saved_owner_fact", query, "ready")
        await observe("duplicate_event", query, "abstain")
        fact = await lifecycle.correct(
            fact.assertion_id, draft("tea"), provenance("fictional-correction")
        )
        corrected = await observe("corrected_fact", request(), "ready")
        results[-1]["canonical_value_checked"] = (
            json.loads(corrected.evidence[0].text)["value"] == "tea"
        )
        results[-1]["passed"] &= results[-1]["canonical_value_checked"]
        await lifecycle.forget(fact.assertion_id, provenance("fictional-forget"))
        await observe("forgotten_fact", request(), "abstain")
        await lifecycle.create(
            draft("decaf", Sensitivity.LOCAL_ONLY),
            provenance("fictional-private", Sensitivity.LOCAL_ONLY),
        )
        await observe("local_only_to_cloud", request(), "abstain")
        await observe("local_only_to_local", request(destination="local"), "ready")
        requester[0] = "guest"
        await observe(
            "guest_cannot_claim_owner", request(destination="local"), "abstain"
        )
        requester[0] = "owner"
        await observe(
            "advice_not_supported_by_exact_recall",
            request("Suggest a drink"),
            "abstain",
        )
        await observe(
            "insufficient_budget",
            replace(request(destination="local"), budget_units=8),
            "abstain",
        )
        planner.resume.clear()
        await observe(
            "late_context_deadline",
            replace(request(destination="local"), deadline_ms=10),
            "unavailable",
        )
        planner.started.clear()
        pending = asyncio.create_task(
            observe(
                "reconnect_discards_pending", request(destination="local"), "stale_turn"
            )
        )
        await planner.started.wait()
        selector.reconnect(conversation)
        planner.resume.set()
        await pending
        conversation.close()
        await observe("closed_session", replace(query, turn_id="closed"), "stale_turn")
        return {
            "schema_version": 1,
            "observed_at": datetime.now(UTC).isoformat(),
            "scope": "offline_native_shadow_contracts",
            "data": "disposable fictional SQLite store with production schema and lifecycle",
            "planner": "controlled exact-facet proposals; no model inference or semantic quality measurement",
            "source": "native MemoryQueryCoordinator + canonical readers + shadow selector",
            "model_calls": 0,
            "network_calls": 0,
            "production_config_reads": 0,
            "live_memory_reads": 0,
            "provider_context_updates": 0,
            "first_spoken_output_ms": None,
            "live_voice_timing_measured": False,
            "results": results,
            "passed": all(item["passed"] for item in results),
            "limits": [
                "Not the accepted-JARVIS model/answer baseline or a vendor trial.",
                "No live voice, audio hardware, provider-verifier or persistence/restart acceptance.",
                "Ready means shadow evidence only; it grants no future provider release or action permission.",
            ],
        }
    finally:
        selector.set_enabled(False)
        await worker.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jarvis-fictional-shadow-") as directory:
        report = asyncio.run(run_probe(Path(directory) / "fictional.db"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
