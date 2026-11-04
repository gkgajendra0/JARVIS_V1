"""Authenticated local inspection and lifecycle; no private UI feed."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .project_conversation_store import REDACTED_DIGEST
from .project_routing import normalize_name


@dataclass(frozen=True)
class DeletionReceipt:
    project_id: str
    deleted_sources: int
    epoch: int
    # Jarvis replies/tool results in other projects removed because they were
    # generated with this project's content (directly or through another reply).
    derived_sources: int = 0


# Jarvis replies and tool results saved before provenance tracking (migration
# 0007) have no evidence edges. One saved in another live project after the
# forgotten project began may have quoted it and nothing proves otherwise, so it
# is treated as derived. Owner turns, omission markers and earlier events are
# kept.
_LEGACY_SUSPECTS = """
SELECT e.event_id FROM conversation_event e
JOIN conversation_thread t ON t.thread_id = e.thread_id
JOIN conversation_workspace w ON w.project_id = t.project_id
WHERE t.project_id <> :project AND w.forgotten_at IS NULL
AND e.provenance_tracked = 0 AND e.role <> 'user'
AND e.payload_sha256 <> :redacted
AND instr(e.text, '"capture":"omitted"') = 0
AND e.accepted_at >= (
    SELECT min(accepted_at) FROM conversation_event
    WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=:project)
)
"""

# Starting from the forgotten project's events and the legacy suspects, walk
# evidence edges to every non-user event that was generated with them in its
# context, directly or through another such reply. Owner turns carry no
# evidence and so are never reached.
_TAINTED_EVENTS = (
    """
WITH RECURSIVE tainted(event_id) AS (
    SELECT event_id FROM conversation_event
    WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=:project)
    UNION
"""
    + _LEGACY_SUSPECTS
    + """
    UNION
    SELECT d.event_id FROM conversation_event_dependency d
    JOIN tainted ON tainted.event_id = d.source_event_id
    JOIN conversation_event e ON e.event_id = d.event_id
    WHERE e.role <> 'user'
)
SELECT event_id FROM tainted
"""
)


def derived_events(conn, project_id):
    """IDs of events outside ``project_id`` that forgetting it must remove, and
    the current revision of each thread holding them."""
    parameters = {"project": project_id, "redacted": REDACTED_DIGEST}
    tainted = {r[0] for r in conn.execute(_TAINTED_EVENTS, parameters)}
    own = {
        r[0]
        for r in conn.execute(
            "SELECT event_id FROM conversation_event WHERE thread_id IN "
            "(SELECT thread_id FROM conversation_thread WHERE project_id=?)",
            (project_id,),
        )
    }
    derived = sorted(tainted - own)
    threads = {}
    for start in range(0, len(derived), 256):
        chunk = derived[start : start + 256]
        marks = ",".join("?" for _ in chunk)
        for thread_id, revision in conn.execute(
            "SELECT t.thread_id,t.archive_revision FROM conversation_thread t WHERE t.thread_id IN "
            f"(SELECT thread_id FROM conversation_event WHERE event_id IN ({marks}))",
            chunk,
        ):
            threads[thread_id] = revision
    return tuple(derived), tuple(sorted(threads.items())), tuple(sorted(tainted))


def _derived_digest(derived, threads):
    import hashlib

    return hashlib.sha256(
        json.dumps([list(derived), [list(t) for t in threads]]).encode()
    ).hexdigest()


@dataclass(frozen=True)
class QuarantineReport:
    count: int
    projects: tuple[tuple[str, int], ...]
    digest: str


def _quarantine_state(conn):
    import hashlib

    ids = [
        r[0]
        for r in conn.execute(
            "SELECT event_id FROM conversation_event_quarantine ORDER BY event_id"
        )
    ]
    projects = tuple(
        (title, count)
        for title, count in conn.execute(
            "SELECT w.title,count(*) FROM conversation_event_quarantine q "
            "JOIN conversation_event e ON e.event_id=q.event_id "
            "JOIN conversation_thread t ON t.thread_id=e.thread_id "
            "JOIN conversation_workspace w ON w.project_id=t.project_id "
            "GROUP BY w.project_id ORDER BY w.title"
        )
    )
    digest = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
    return QuarantineReport(len(ids), projects, digest)


@dataclass(frozen=True)
class ForgetPreview:
    derived_sources: int
    affected_projects: tuple[str, ...]
    digest: str


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

    async def _catalog_read(self, material, read):
        from .project_access import CATALOG

        return await self.access._perform(
            CATALOG,
            material,
            "read",
            lambda p: self.access.store._bound_read(
                CATALOG, material, permit=p, read=read
            ),
        )

    async def quarantine_report(self):
        """Upgrade quarantine: messages per project, plus a digest of the set.

        Counts and titles only; text is shown only by ``inspect_quarantine``.
        """

        def read(conn):
            return _quarantine_state(conn)

        return await self._catalog_read({"operation": "quarantine_report"}, read)

    async def inspect_quarantine(self, *, authorize=None):
        """The quarantined messages themselves, for the owner's local review."""
        if authorize is not None and authorize() is not True:
            raise PermissionError("inspection denied")

        def read(conn):
            return tuple(
                conn.execute(
                    "SELECT w.title,e.accepted_at,e.role,e.text FROM conversation_event_quarantine q "
                    "JOIN conversation_event e ON e.event_id=q.event_id "
                    "JOIN conversation_thread t ON t.thread_id=e.thread_id "
                    "JOIN conversation_workspace w ON w.project_id=t.project_id "
                    "ORDER BY w.title,e.accepted_at,e.event_id"
                ).fetchall()
            )

        return await self._catalog_read({"operation": "inspect_quarantine"}, read)

    async def resolve_quarantine(self, action, *, permit=None):
        """Owner-approved end of the upgrade quarantine.

        ``delete`` turns every quarantined message into a tombstone (the same
        redaction forget uses) and rewrites the search index; ``restore``
        returns them to normal use. The approval binds the exact set shown in
        the report; if it changed, nothing happens.
        """
        if action not in {"delete", "restore"}:
            raise ValueError("quarantine action must be delete or restore")
        report = await self.quarantine_report()
        if not report.count:
            return report
        material = {
            "operation": "resolve_quarantine",
            "action": action,
            "count": report.count,
            "projects": list(report.projects),
            "digest": report.digest,
        }
        issuer = self.access.authority
        if permit is None:
            permit = await asyncio.to_thread(
                issuer.authorize_quarantine_resolution, material
            )

        def resolve(conn):
            with issuer.deletion_scope(permit, material) as validate:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    state = _quarantine_state(conn)
                    if state.digest != material["digest"]:
                        raise PermissionError("quarantine changed before approval")
                    ids = [
                        r[0]
                        for r in conn.execute(
                            "SELECT event_id FROM conversation_event_quarantine ORDER BY event_id"
                        )
                    ]
                    threads = set()
                    for start in range(0, len(ids), 256):
                        chunk = ids[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        threads |= {
                            r[0]
                            for r in conn.execute(
                                f"SELECT DISTINCT thread_id FROM conversation_event WHERE event_id IN ({marks})",
                                chunk,
                            )
                        }
                        if action == "delete":
                            conn.execute(
                                "UPDATE conversation_event SET text='[forgotten]',role='tool',"
                                f"delivery='failed',payload_sha256=? WHERE event_id IN ({marks})",
                                (REDACTED_DIGEST, *chunk),
                            )
                            conn.execute(
                                f"DELETE FROM conversation_event_dependency WHERE event_id IN ({marks})",
                                chunk,
                            )
                    conn.execute("DELETE FROM conversation_event_quarantine")
                    if action == "delete":
                        conn.execute(
                            "INSERT INTO conversation_event_fts(conversation_event_fts) VALUES('optimize')"
                        )
                    # Context available to these threads changed.
                    for thread_id in sorted(threads):
                        conn.execute(
                            "UPDATE conversation_thread SET archive_revision=archive_revision+1 WHERE thread_id=?",
                            (thread_id,),
                        )
                    validate()
                    conn.commit()
                    self.access.store.change_revision += 1
                    return state
                except BaseException:
                    conn.rollback()
                    raise

        result = await self.access.store._writer.run(resolve)
        self.access.local_revision += 1
        for callback in self.access._invalidators:
            callback("quarantine_" + action, None)
        return result

    async def preview_forget(self, project_id):
        """What forgetting ``project_id`` would remove elsewhere: counts and
        project titles only, read under the owner's history permit."""
        await self._entry(project_id)
        from .project_access import CATALOG

        material = {"operation": "preview_forget", "project_id": project_id}

        def read(conn):
            derived, threads, _ = derived_events(conn, project_id)
            titles = sorted(
                {
                    r[0]
                    for thread_id, _ in threads
                    for r in conn.execute(
                        "SELECT w.title FROM conversation_thread t JOIN conversation_workspace w "
                        "ON w.project_id=t.project_id WHERE t.thread_id=?",
                        (thread_id,),
                    )
                }
            )
            return ForgetPreview(
                len(derived), tuple(titles), _derived_digest(derived, threads)
            )

        return await self.access._perform(
            CATALOG,
            material,
            "read",
            lambda p: self.access.store._bound_read(
                CATALOG, material, permit=p, read=read
            ),
        )

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
        preview = await self.preview_forget(project_id)
        material = {
            "operation": "forget_project",
            "thread_versions": thread_versions,
            "project_id": project_id,
            "epoch": s.revision,
            "expected_revision": expected_revision,
            "derived_count": preview.derived_sources,
            "derived_digest": preview.digest,
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
                    # Derived replies elsewhere, found before redaction and
                    # bound to the owner's approval: if they changed since the
                    # approval was shown, nothing is deleted.
                    derived, derived_threads, tainted_list = derived_events(
                        conn, project_id
                    )
                    if (
                        _derived_digest(derived, derived_threads)
                        != material["derived_digest"]
                    ):
                        raise PermissionError("derived history changed before deletion")
                    # Redact payloads, preserve only immutable tombstone identities.
                    # Reusing a deleted event ID in any project is then rejected.
                    conn.execute(
                        "UPDATE conversation_event SET text='[forgotten]',role='tool',delivery='failed',payload_sha256=? WHERE thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=?)",
                        ("0" * 64, project_id),
                    )
                    for start in range(0, len(derived), 256):
                        chunk = derived[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        conn.execute(
                            "UPDATE conversation_event SET text='[forgotten]',role='tool',delivery='failed',"
                            f"payload_sha256=? WHERE event_id IN ({marks})",
                            (REDACTED_DIGEST, *chunk),
                        )
                    # Redacted events need no further owner review.
                    for start in range(0, len(tainted_list), 256):
                        chunk = tainted_list[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        conn.execute(
                            f"DELETE FROM conversation_event_quarantine WHERE event_id IN ({marks})",
                            chunk,
                        )
                    # The evidence links of redacted events are themselves
                    # provenance about the forgotten content; drop them.
                    for start in range(0, len(tainted_list), 256):
                        chunk = tainted_list[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        conn.execute(
                            f"DELETE FROM conversation_event_dependency WHERE event_id IN ({marks})",
                            chunk,
                        )
                    # Content of other threads changed: stale packets and appends
                    # built on the old revision must fail rather than reuse it.
                    for thread_id, _ in derived_threads:
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

    async def preview_forget_mentions(self, terms):
        """What forgetting these words would remove: ids, counts and project
        titles, read under the owner's history grant. Nothing is changed."""
        terms = _forget_terms(terms)
        from .project_access import CATALOG

        material = {"operation": "preview_forget_mentions", "terms": list(terms)}
        return await self.access._perform(
            CATALOG,
            material,
            "read",
            lambda p: self.access.store._bound_read(
                CATALOG,
                material,
                permit=p,
                read=lambda conn: _mention_state(conn, terms)[0],
            ),
        )

    async def forget_mentions(self, preview, *, permit=None):
        """Redact exactly the previewed rows after a fresh owner approval (Windows
        Hello). If anything they cover changed since the preview, nothing changes."""
        if not isinstance(preview, MentionForgetPreview) or not preview.matched:
            raise ValueError("a non-empty mention preview is required")
        material = {
            "operation": "forget_mentions",
            "terms": list(preview.terms),
            "owner_rows": preview.owner_rows,
            "jarvis_rows": preview.jarvis_rows,
            "projects": list(preview.projects),
            "digest": preview.digest,
        }
        issuer = self.access.authority
        if permit is None:
            permit = await asyncio.to_thread(
                issuer.authorize_mention_deletion, material
            )

        def erase(conn):
            with issuer.deletion_scope(permit, material) as validate:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    current, threads = _mention_state(conn, preview.terms)
                    if current.digest != preview.digest:
                        raise PermissionError("history changed before deletion")
                    ids = (*current.matched, *current.derived)
                    for start in range(0, len(ids), 256):
                        chunk = ids[start : start + 256]
                        marks = ",".join("?" for _ in chunk)
                        conn.execute(
                            "UPDATE conversation_event SET text='[forgotten]',role='tool',"
                            f"delivery='failed',payload_sha256=? WHERE event_id IN ({marks})",
                            (REDACTED_DIGEST, *chunk),
                        )
                        conn.execute(
                            f"DELETE FROM conversation_event_dependency WHERE event_id IN ({marks})",
                            chunk,
                        )
                        conn.execute(
                            f"DELETE FROM conversation_event_quarantine WHERE event_id IN ({marks})",
                            chunk,
                        )
                    for thread_id in threads:
                        # Derived thread state may summarise the removed words.
                        conn.execute(
                            "UPDATE conversation_thread SET state_json=NULL,covered_sequence=0,"
                            "archive_revision=archive_revision+1 WHERE thread_id=?",
                            (thread_id,),
                        )
                    # Physically rewrite the search index without the removed words.
                    conn.execute(
                        "INSERT INTO conversation_event_fts(conversation_event_fts) VALUES('optimize')"
                    )
                    validate()
                    conn.commit()
                    self.access.store.change_revision += 1
                    return MentionDeletionReceipt(
                        current.owner_rows, current.jarvis_rows, current.projects
                    )
                except BaseException:
                    conn.rollback()
                    raise

        result = await self.access.store._writer.run(erase)
        self.access.local_revision += 1
        for callback in self.access._invalidators:
            callback("forget_mentions", None)
        return result


# -- forgetting what the owner said about something --------------------------
#
# Project forget removes a whole project. Mention forget removes only the saved
# rows (in any live project) that contain ALL of the owner's words, plus every
# Jarvis reply or tool result generated with one of them in context (evidence
# edges, transitively). Owner turns that do not contain the words are kept.

MAX_FORGET_TERMS = 6
MAX_FORGET_ROWS = 64


class ForgetTooBroadError(ValueError):
    """The words match too many saved rows; the owner must be more specific."""


@dataclass(frozen=True)
class MentionForgetPreview:
    terms: tuple[str, ...]
    matched: tuple[str, ...]
    derived: tuple[str, ...]
    owner_rows: int
    jarvis_rows: int
    projects: tuple[str, ...]
    digest: str


def _and_expression(terms):
    return " AND ".join(f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in terms)


def _mentioning(conn, terms):
    """Live rows whose text contains every term (FTS candidates, then an exact
    case-insensitive check so stemming never widens the match)."""
    rows = conn.execute(
        "SELECT e.event_id,e.role,e.text,w.title,t.thread_id,t.archive_revision "
        "FROM conversation_event_fts JOIN conversation_event e "
        "ON e.rowid=conversation_event_fts.rowid "
        "JOIN conversation_thread t ON t.thread_id=e.thread_id "
        "JOIN conversation_workspace w ON w.project_id=t.project_id "
        "WHERE conversation_event_fts MATCH ? AND w.forgotten_at IS NULL "
        "AND e.payload_sha256<>? LIMIT ?",
        (_and_expression(terms), REDACTED_DIGEST, MAX_FORGET_ROWS * 4 + 1),
    ).fetchall()
    return [r for r in rows if all(t in r[2].casefold() for t in terms)]


_DEPENDANTS = """
WITH RECURSIVE tainted(event_id) AS (
    SELECT value FROM json_each(:seed)
    UNION
    SELECT d.event_id FROM conversation_event_dependency d
    JOIN tainted ON tainted.event_id = d.source_event_id
    JOIN conversation_event e ON e.event_id = d.event_id
    WHERE e.role <> 'user' AND e.payload_sha256 <> :redacted
)
SELECT event_id FROM tainted
"""


def _mention_state(conn, terms):
    rows = _mentioning(conn, terms)
    if len(rows) > MAX_FORGET_ROWS:
        raise ForgetTooBroadError(
            "those words match too many saved messages; name it more specifically"
        )
    matched = tuple(sorted(r[0] for r in rows))
    tainted = {
        r[0]
        for r in conn.execute(
            _DEPENDANTS,
            {"seed": json.dumps(list(matched)), "redacted": REDACTED_DIGEST},
        )
    }
    derived = tuple(sorted(tainted - set(matched)))
    everything = (*matched, *derived)
    threads, owner, jarvis, titles = {}, 0, 0, set()
    for start in range(0, len(everything), 256):
        chunk = everything[start : start + 256]
        marks = ",".join("?" for _ in chunk)
        for role, title, thread_id, revision in conn.execute(
            "SELECT e.role,w.title,t.thread_id,t.archive_revision FROM conversation_event e "
            "JOIN conversation_thread t ON t.thread_id=e.thread_id "
            "JOIN conversation_workspace w ON w.project_id=t.project_id "
            f"WHERE e.event_id IN ({marks})",
            chunk,
        ):
            threads[thread_id] = revision
            titles.add(title)
            if role == "user":
                owner += 1
            else:
                jarvis += 1
    import hashlib

    digest = hashlib.sha256(
        json.dumps(
            [list(terms), list(matched), list(derived), sorted(threads.items())]
        ).encode()
    ).hexdigest()
    return (
        MentionForgetPreview(
            tuple(terms), matched, derived, owner, jarvis, tuple(sorted(titles)), digest
        ),
        tuple(sorted(threads)),
    )


def _forget_terms(terms):
    from .project_access import conversation_search_terms

    folded = conversation_search_terms(" ".join(terms))
    if not 1 <= len(folded) <= MAX_FORGET_TERMS:
        raise ValueError("one to six distinctive words required")
    return folded


@dataclass(frozen=True)
class MentionDeletionReceipt:
    owner_rows: int
    jarvis_rows: int
    projects: tuple[str, ...]
