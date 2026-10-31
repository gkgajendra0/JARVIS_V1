"""Fixed fictional text-lab fixture; no model client or automatic quality grading."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jarvis.authority.conversation_history import HistoryActionBinding
from jarvis.memory.project_conversation_store import archive_digest
from jarvis.memory.project_conversations import ConversationEvent, ProjectSelection
from jarvis.memory.project_routing import ProjectRoutingDecision

FIXTURE_KIND = "original-evidence-conflict-v1"


async def seed_acceptance_fixture(access):
    """Caller owns the new isolated lab lock; never seed an occupied archive."""
    catalog = await access.catalog()
    if catalog.entries:
        raise ValueError("acceptance fixture requires an empty archive")
    selection = ProjectSelection(str(uuid4()), str(uuid4()), 0)
    await access.select(
        ProjectRoutingDecision(
            "ready",
            selection,
            "Nepal acceptance",
            catalog.selection_revision,
            create=True,
        )
    )
    rows = [
        ("user", "For this fictional trip, we chose the Jimny. The permit is pending."),
        ("user", "Correction for this fictional trip: the permit is now approved."),
        (
            "assistant",
            "For this fictional trip, you chose the Scorpio and the permit is pending.",
        ),
        *[
            (
                "user" if i % 2 == 0 else "assistant",
                f"Synthetic checkpoint {i}" if i % 2 == 0 else "OK",
            )
            for i in range(40)
        ],
    ]
    original_ids = []
    conflict_id = None
    stamp = datetime.now(UTC)
    segment = str(uuid4())
    for revision, (role, text) in enumerate(rows):
        event = ConversationEvent(
            str(uuid4()),
            segment,
            str(uuid4()),
            role,
            text,
            stamp + timedelta(microseconds=revision),
        )
        material = access.store.append_material(selection, event, revision)
        issuer = access.authority
        issuer.register_source(access.grant, event.event_id, source=event)
        try:
            permit = issuer.issue_child(
                access.grant,
                HistoryActionBinding(
                    "admit",
                    event.event_id,
                    archive_digest(material),
                    targets=(
                        ("project", selection.project_id),
                        ("thread", selection.thread_id),
                    ),
                ),
            )
            await access.store.append_event(
                selection, event, permit=permit, expected_revision=revision
            )
        finally:
            issuer.release_source(access.grant, event.event_id)
        if revision < 2:
            original_ids.append(event.event_id)
        elif revision == 2:
            conflict_id = event.event_id
    return {
        "kind": FIXTURE_KIND,
        "project_id": selection.project_id,
        "thread_id": selection.thread_id,
        "seeded_events": len(rows),
        "original_source_ids": original_ids,
        "conflicting_assistant_id": conflict_id,
    }


class FixtureEvidenceProvider:
    """One-request observer: verify the whole-project baseline before dispatch."""

    def __init__(self, provider, access, manifest):
        self.provider, self.access, self.manifest = provider, access, manifest
        self.request_id = None
        self.fresh_trial = False

    async def step(self, packet, **kwargs):
        async def guard():
            result = kwargs["check"]()
            if inspect.isawaitable(result):
                await result

        if self.request_id is None:
            await guard()
            catalog = await self.access.catalog()
            entries = [
                e
                for e in catalog.entries
                if e.selection.project_id == self.manifest["project_id"]
            ]
            self.fresh_trial = (
                len(entries) == 1
                and packet.selection == entries[0].selection
                and packet.selection.thread_id == self.manifest["thread_id"]
                and entries[0].archive_revision == self.manifest["seeded_events"] + 1
            )
            await guard()
            self.request_id = packet.request_id
        elif self.request_id != packet.request_id:
            raise ValueError("fixture observer is bound to one request")
        return await self.provider.step(packet, **kwargs)


def fixture_evidence(manifest, result, *, observer=None):
    """Source presence is metadata evidence, never an automatic answer PASS."""
    if result.packet.selection.project_id != manifest["project_id"]:
        return None
    body = json.loads(result.packet.context)
    identities = set(result.packet.source_ids)
    return {
        "kind": FIXTURE_KIND,
        "request_id": result.packet.request_id,
        "fresh_fixture_trial": (
            observer is not None
            and observer.request_id == result.packet.request_id
            and observer.fresh_trial
        ),
        "original_sources_expected": len(manifest["original_source_ids"]),
        "original_sources_in_final_context": len(
            identities & set(manifest["original_source_ids"])
        ),
        "conflicting_assistant_in_final_context": manifest["conflicting_assistant_id"]
        in identities,
        "provider_steps": len(result.usage),
        "tools": [
            {"tool": row["tool"], "status": row["status"]} for row in body["retrieval"]
        ],
        "answer_quality": "not_evaluated",
    }
