"""Authenticated local inspection and lifecycle; no private UI feed."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .project_routing import normalize_name


@dataclass(frozen=True)
class DeletionReceipt:
    project_id: str
    deleted_sources: int
    epoch: int
    # Jarvis replies/tool results in other projects removed because they were
    # generated with this project's content (directly or through another reply).
    derived_sources: int = 0


# Every archived event of the forgotten project, plus every non-user event
# anywhere whose recorded evidence reaches one of them (transitively). Owner
# turns are never derived, so they stop the walk.
_TAINTED_EVENTS_SQL = """
WITH RECURSIVE tainted(event_id) AS (
    SELECT event_id FROM conversation_event
    WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=?)
    UNION
    SELECT d.event_id FROM conversation_event_dependency d
    JOIN tainted ON tainted.event_id = d.source_event_id
    JOIN conversation_event e ON e.event_id = d.event_id
    WHERE e.role <> 'user'
)
SELECT event_id FROM tainted
"""

# Events saved before provenance tracking have no evidence edges. A Jarvis reply
# or tool result of that kind, saved in another project after the forgotten
# project began, may have quoted it; there is no way to prove otherwise, so it
# is removed too. Owner turns and earlier replies are kept.
_LEGACY_SUSPECT_SQL = """
SELECT e.event_id FROM conversation_event e
JOIN conversation_thread t ON t.thread_id = e.thread_id
WHERE t.project_id <> ? AND e.provenance_tracked = 0 AND e.role <> 'user'
AND NOT (e.role = 'tool' AND e.text = '[forgotten]')
AND e.accepted_at >= (
    SELECT min(accepted_at) FROM conversation_event
    WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=?)
)
"""


class ProjectControls:
    def __init__(self, access):
        self.access = access

    async def _entry(self, project_id):
        catalog = await self.access.catalog()
        matches = [e for e in catalog.entries if e.selection.project_id == project_id]
        if not matches:
            raise PermissionError("project unavailable")
        return next((e for e in matches if e.selection == catalog.current), matches[-1])

    async def inspect_project(self, project_id, *, authorize=None):
        if authorize is not None and authorize() is not True:
            raise PermissionError("inspection denied")
        entry = await self._entry(project_id)
        return await self.access.snapshot(entry.selection, limit=512, project_wide=True)

    async def _metadata(self, project_id, *, paused=None, aliases=None):
        entry = await self._entry(project_id)
        s = entry.selection
        material = {
            "operation": "project_metadata",
            "selection": s.__dict__
            if hasattr(s, "__dict__")
            else {
                "project_id": s.project_id,
                "thread_id": s.thread_id,
                "revision": s.revision,
            },
            "paused": paused,
            "aliases": aliases,
        }

        def write(conn):
            row = conn.execute(
                "SELECT epoch,forgotten_at FROM conversation_workspace WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if row != (s.revision, None):
                raise PermissionError("project metadata changed")
            if paused is not None:
                conn.execute(
                    "UPDATE conversation_workspace SET retention_paused=? WHERE project_id=?",
                    (int(paused), project_id),
                )
            if aliases is not None:
                conn.execute(
                    "UPDATE conversation_workspace SET aliases_json=? WHERE project_id=?",
                    (json.dumps(aliases), project_id),
                )
            conn.execute(
                "UPDATE conversation_workspace SET epoch=epoch+1 WHERE project_id=?",
                (project_id,),
            )

        await self.access._perform(
            s,
            material,
            "admit",
            lambda p: self.access.store._bound_write(
                s, material, permit=p, write=write
            ),
        )
        self.access.local_revision += 1
        for callback in self.access._invalidators:
            callback("metadata", project_id)

    async def pause_project(self, project_id, *, paused):
        if type(paused) is not bool:
            raise ValueError("explicit pause boolean required")
        await self._metadata(project_id, paused=paused)

    async def set_aliases(self, project_id, aliases):
        if (
            type(aliases) is not tuple
            or len(aliases) > 8
            or any(
                not isinstance(a, str) or not 1 <= len(a.strip()) <= 160
                for a in aliases
            )
        ):
            raise ValueError("bounded explicit aliases required")
        if len({normalize_name(a) for a in aliases}) != len(aliases):
            raise ValueError("duplicate aliases")
        await self._metadata(project_id, aliases=aliases)

    async def forget_project(self, project_id, *, expected_revision, permit=None):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("exact archive revision required")
        entry = await self._entry(project_id)
        s = entry.selection
        catalog = await self.access.catalog()
        thread_versions = tuple(
            sorted(
                (e.selection.thread_id, e.archive_revision)
                for e in catalog.entries
                if e.selection.project_id == project_id
            )
        )
        material = {
            "operation": "forget_project",
            "thread_versions": thread_versions,
            "project_id": project_id,
            "epoch": s.revision,
            "expected_revision": expected_revision,
        }
        issuer = self.access.authority
        if permit is None:
            permit = await asyncio.to_thread(
                issuer.authorize_project_deletion, material
            )

        def erase(conn):
            with issuer.deletion_scope(permit, material) as validate:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT w.epoch,t.archive_revision FROM conversation_workspace w JOIN conversation_thread t "
                        "ON t.project_id=w.project_id WHERE w.project_id=? AND t.thread_id=? AND w.forgotten_at IS NULL",
                        (project_id, s.thread_id),
                    ).fetchone()
                    if row != (s.revision, expected_revision):
                        raise PermissionError("project changed before deletion")
                    current_versions = tuple(
                        conn.execute(
                            "SELECT thread_id,archive_revision FROM conversation_thread WHERE project_id=? ORDER BY thread_id",
                            (project_id,),
                        ).fetchall()
                    )
                    if current_versions != thread_versions:
                        raise PermissionError("project changed before deletion")
                    count = conn.execute(
                        "SELECT count(*) FROM conversation_event WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=?)",
                        (project_id,),
                    ).fetchone()[0]
                    # Find derived replies elsewhere before redacting, while the
                    # forgotten project's events are still identifiable.
                    tainted = {
                        r[0] for r in conn.execute(_TAINTED_EVENTS_SQL, (project_id,))
                    }
                    tainted |= {
                        r[0]
                        for r in conn.execute(
                            _LEGACY_SUSPECT_SQL, (project_id, project_id)
                        )
                    }
                    own = {
                        r[0]
                        for r in conn.execute(
                            "SELECT event_id FROM conversation_event WHERE thread_id IN "
                            "(SELECT thread_id FROM conversation_thread WHERE project_id=?)",
                            (project_id,),
                        )
                    }
                    derived = sorted(tainted - own)
                    # Redact payloads, preserve only immutable tombstone identities.
                    # Reusing a deleted event ID in any project is then rejected.
                    conn.execute(
                        "UPDATE conversation_event SET text='[forgotten]',role='tool',delivery='failed',payload_sha256=? WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=?)",
                        ("0" * 64, project_id),
                    )
                    derived_threads = set()
                    for start in range(0, len(derived), 256):
                        chunk = derived[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        derived_threads |= {
                            r[0]
                            for r in conn.execute(
                                f"SELECT DISTINCT thread_id FROM conversation_event WHERE event_id IN ({marks})",
                                chunk,
                            )
                        }
                        conn.execute(
                            "UPDATE conversation_event SET text='[forgotten]',role='tool',delivery='failed',"
                            f"payload_sha256=? WHERE event_id IN ({marks})",
                            ("0" * 64, *chunk),
                        )
                    # The evidence links of redacted events are themselves
                    # provenance about the forgotten content; drop them.
                    tainted_list = sorted(tainted)
                    for start in range(0, len(tainted_list), 256):
                        chunk = tainted_list[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        conn.execute(
                            f"DELETE FROM conversation_event_dependency WHERE event_id IN ({marks})",
                            chunk,
                        )
                    # Content of other threads changed: stale packets and appends
                    # built on the old revision must fail rather than reuse it.
                    for thread_id in sorted(derived_threads):
                        conn.execute(
                            "UPDATE conversation_thread SET archive_revision=archive_revision+1 WHERE thread_id=?",
                            (thread_id,),
                        )
                    # Rewrite the derived search index so the forgotten words are
                    # gone from its segments, not only hidden from queries.
                    conn.execute(
                        "INSERT INTO conversation_event_fts(conversation_event_fts) VALUES('optimize')"
                    )
                    conn.execute(
                        "UPDATE conversation_thread SET state_json=NULL,covered_sequence=0,archive_revision=archive_revision+1 WHERE project_id=?",
                        (project_id,),
                    )
                    conn.execute(
                        "UPDATE conversation_workspace SET title='[forgotten]',aliases_json='[]',epoch=epoch+1,forgotten_at=? WHERE project_id=?",
                        (datetime.now(UTC).isoformat(), project_id),
                    )
                    conn.execute(
                        "UPDATE conversation_selection SET revision=revision+1 WHERE project_id=?",
                        (project_id,),
                    )
                    validate()
                    conn.commit()
                    self.access.store.change_revision += 1
                    return DeletionReceipt(
                        project_id, count, s.revision + 1, len(derived)
                    )
                except BaseException:
                    conn.rollback()
                    raise

        result = await self.access.store._writer.run(erase)
        self.access.local_revision += 1
        for callback in self.access._invalidators:
            callback("forget", project_id)
        return result
