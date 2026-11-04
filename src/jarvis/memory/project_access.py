"""Server-owned authorized project operations; no query text is SQL or authority."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

from jarvis.authority.conversation_history import HistoryActionBinding

from .project_conversation_store import archive_digest
from .project_conversations import ConversationEvent, ProjectSelection
from .retrieval import _STOPWORDS

CATALOG = ProjectSelection("*", "*", 0)
MAX_SEARCH_TERMS = 24


def conversation_search_terms(text: str) -> tuple[str, ...]:
    """Unicode-aware search words for the conversation index.

    Letters, combining marks and digits stay together, so Devanagari words keep
    their vowel signs (the shared ``build_fts5_query`` splits them apart).
    """
    if not isinstance(text, str):
        raise TypeError("search text must be a string")
    words, current = [], []
    for character in unicodedata.normalize("NFKC", text):
        if unicodedata.category(character)[0] in "LMN":
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    terms = []
    for word in words:
        folded = word.casefold()
        if len(folded) >= 2 and folded not in _STOPWORDS and folded not in terms:
            terms.append(folded)
    return tuple(terms[:MAX_SEARCH_TERMS])


def conversation_match_expression(terms: tuple[str, ...]) -> str:
    """FTS5 MATCH text built only from quoted letter/digit words; never raw input."""
    if not terms:
        raise ValueError("search terms required")
    # Prefix matching keeps "permit" finding "permits" (and porter stems both),
    # which the previous substring search also allowed.
    return " OR ".join(f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in terms)


@dataclass(frozen=True)
class ProjectEntry:
    selection: ProjectSelection
    title: str
    aliases: tuple[str, ...]
    archive_revision: int


@dataclass(frozen=True)
class ProjectCatalog:
    entries: tuple[ProjectEntry, ...]
    current: ProjectSelection | None
    selection_revision: int


@dataclass(frozen=True)
class ArchivedSource:
    event: ConversationEvent
    sequence: int
    revision: int
    thread_id: str = ""
    search_priority: int = 0
    project_title: str = ""
    project_id: str = ""


@dataclass(frozen=True)
class ArchiveSnapshot:
    selection: ProjectSelection
    title: str
    archive_revision: int
    last_sequence: int
    sources: tuple[ArchivedSource, ...]
    status: str
    retention_paused: bool = False
    omissions: int = 0
    store_revision: int = 0


def _sources(rows):
    return tuple(
        ArchivedSource(
            ConversationEvent(
                r[0], r[3], r[4], r[5], r[6], datetime.fromisoformat(r[7]), r[8]
            ),
            r[1],
            r[2],
            r[9] if len(r) > 9 else "",
            r[10] if len(r) > 10 else 0,
            r[11] if len(r) > 11 else "",
            r[12] if len(r) > 12 else "",
        )
        for r in rows
    )


class ProjectArchiveAccess:
    def __init__(self, store, *, authority, grant):
        store.bind_authority(authority)
        self.store, self.authority, self.grant = store, authority, grant
        self.local_revision = 0
        self._invalidators = []

    def current(self):
        return self.authority.validate(self.grant).status == "active"

    async def _perform(self, selection, material, operation, run):
        source_id = str(uuid4())
        self.authority.register_source(self.grant, source_id)
        try:
            permit = self.authority.issue_child(
                self.grant,
                HistoryActionBinding(
                    operation,
                    source_id,
                    archive_digest(material),
                    targets=(
                        ("project", selection.project_id),
                        ("thread", selection.thread_id),
                    ),
                ),
            )
            return await run(permit)
        finally:
            self.authority.release_source(self.grant, source_id)

    async def create_project(self, selection, title):
        material = self.store.creation_material(selection, title)
        await self._perform(
            selection,
            material,
            "admit",
            lambda p: self.store.create_project(selection, title, permit=p),
        )
        self.local_revision += 1

    async def catalog(self):
        material = {"operation": "catalog"}

        def read(conn):
            rows = conn.execute(
                "SELECT w.project_id,t.thread_id,w.epoch,w.title,w.aliases_json,t.archive_revision "
                "FROM conversation_workspace w JOIN conversation_thread t ON t.project_id=w.project_id "
                "WHERE w.forgotten_at IS NULL ORDER BY w.rowid,t.rowid"
            ).fetchall()
            entries = tuple(
                ProjectEntry(
                    ProjectSelection(r[0], r[1], r[2]),
                    r[3],
                    tuple(json.loads(r[4])),
                    r[5],
                )
                for r in rows
            )
            selected = conn.execute(
                "SELECT project_id,thread_id,revision FROM conversation_selection WHERE owner_scope='owner'"
            ).fetchone()
            current = next(
                (
                    e.selection
                    for e in entries
                    if selected
                    and (e.selection.project_id, e.selection.thread_id) == selected[:2]
                ),
                None,
            )
            return ProjectCatalog(entries, current, selected[2] if selected else 0)

        return await self._perform(
            CATALOG,
            material,
            "read",
            lambda p: self.store._bound_read(CATALOG, material, permit=p, read=read),
        )

    async def commit_selection(self, decision, *, permit, expected_revision):
        if (
            decision.status != "ready"
            or expected_revision != decision.expected_revision
        ):
            raise ValueError("ready exact routing decision required")
        selection = decision.selection
        material = decision.material()

        def write(conn):
            row = conn.execute(
                "SELECT revision FROM conversation_selection WHERE owner_scope='owner'"
            ).fetchone()
            if (row[0] if row else 0) != expected_revision:
                raise PermissionError("selection revision changed")
            if decision.create:
                conn.execute(
                    "INSERT INTO conversation_workspace(project_id,title) VALUES (?,?)",
                    (selection.project_id, decision.title),
                )
                conn.execute(
                    "INSERT INTO conversation_thread(thread_id,project_id) VALUES (?,?)",
                    (selection.thread_id, selection.project_id),
                )
            elif decision.new_thread:
                conn.execute(
                    "INSERT INTO conversation_thread(thread_id,project_id) VALUES (?,?)",
                    (selection.thread_id, selection.project_id),
                )
            state = conn.execute(
                "SELECT w.epoch FROM conversation_workspace w JOIN conversation_thread t "
                "ON t.project_id=w.project_id WHERE w.project_id=? AND t.thread_id=? AND w.forgotten_at IS NULL",
                (selection.project_id, selection.thread_id),
            ).fetchone()
            if state != (selection.revision,):
                raise PermissionError("selected project changed")
            conn.execute(
                "INSERT INTO conversation_selection VALUES ('owner',?,?,?) ON CONFLICT(owner_scope) "
                "DO UPDATE SET project_id=excluded.project_id,thread_id=excluded.thread_id,revision=excluded.revision",
                (selection.project_id, selection.thread_id, expected_revision + 1),
            )
            return selection

        result = await self.store._bound_write(
            selection, material, permit=permit, write=write
        )
        self.local_revision += 1
        return result

    async def select(self, decision):
        return await self._perform(
            decision.selection,
            decision.material(),
            "admit",
            lambda p: self.commit_selection(
                decision, permit=p, expected_revision=decision.expected_revision
            ),
        )

    async def snapshot(
        self,
        selection,
        *,
        limit=32,
        query=None,
        source_ids=None,
        project_wide=False,
        exclude_request_id=None,
        all_projects=False,
    ):
        if type(project_wide) is not bool or type(all_projects) is not bool:
            raise ValueError("explicit project scope required")
        if all_projects and (query is None) == (source_ids is None):
            raise ValueError("all-project scope is only for one search or source read")
        if type(limit) is not int or not 1 <= limit <= 512:
            raise ValueError("bounded source limit required")
        if query is not None and (
            not isinstance(query, str) or not 1 <= len(query.strip()) <= 512
        ):
            raise ValueError("bounded search text required")
        if exclude_request_id is not None and (
            query is None
            or not isinstance(exclude_request_id, str)
            or not 1 <= len(exclude_request_id) <= 128
        ):
            raise ValueError("bounded search request exclusion required")
        if source_ids is not None and (
            type(source_ids) is not tuple
            or not 1 <= len(source_ids) <= 16
            or any(not isinstance(x, str) for x in source_ids)
        ):
            raise ValueError("bounded source identities required")
        material = {
            "operation": "snapshot",
            "selection": asdict(selection),
            "limit": limit,
            "query": query,
            "source_ids": source_ids,
            "project_wide": project_wide,
            "exclude_request_id": exclude_request_id,
            "all_projects": all_projects,
        }
        terms = conversation_search_terms(query) if query is not None else ()

        def read(conn):
            row = conn.execute(
                "SELECT w.title,w.epoch,w.retention_paused,t.archive_revision,t.last_sequence "
                "FROM conversation_workspace w JOIN conversation_thread t ON t.project_id=w.project_id "
                "WHERE w.project_id=? AND t.thread_id=? AND w.forgotten_at IS NULL",
                (selection.project_id, selection.thread_id),
            ).fetchone()
            if row is None or row[1] != selection.revision:
                raise PermissionError("project deleted or epoch changed")
            # Rows removed by forget (in any project) remain only as tombstones
            # and are never context, search or read material. The zero digest
            # is set solely by forget; the column name is unambiguous in joins.
            live = (
                " AND e.payload_sha256<>'" + "0" * 64 + "'"
                # Upgrade quarantine: kept for the owner's decision, never used.
                " AND NOT EXISTS (SELECT 1 FROM conversation_event_quarantine q "
                "WHERE q.event_id=e.event_id)"
                # Jarvis replies and tool results generated with another
                # project's events in context are never fed back as context or
                # search material. The original sources stay findable with
                # their own project label, so knowledge is not lost, but a
                # restatement can never become the next reply's evidence. This
                # keeps forget's derived set to direct dependants only.
                " AND (e.role='user' OR NOT EXISTS (SELECT 1 FROM "
                "conversation_event_dependency d JOIN conversation_event s "
                "ON s.event_id=d.source_event_id JOIN conversation_thread st "
                "ON st.thread_id=s.thread_id JOIN conversation_thread et "
                "ON et.thread_id=e.thread_id WHERE d.event_id=e.event_id "
                "AND st.project_id<>et.project_id))"
            )
            if all_projects:
                # Soft separation: every project the owner has not forgotten.
                scope_sql = (
                    "thread_id IN (SELECT t.thread_id FROM conversation_thread t "
                    "JOIN conversation_workspace w ON w.project_id=t.project_id "
                    "WHERE w.forgotten_at IS NULL)"
                )
                scope_parameters = ()
            elif project_wide:
                scope_sql = "thread_id IN (SELECT thread_id FROM conversation_thread WHERE project_id=?)"
                scope_parameters = (selection.project_id,)
            else:
                scope_sql = "thread_id=?"
                scope_parameters = (selection.thread_id,)
            scope_sql = "(" + scope_sql + ")" + live
            parameters = list(scope_parameters)
            filters = scope_sql
            if query is not None:
                filters += " AND role IN ('user','assistant')"
                if exclude_request_id is not None:
                    filters += " AND request_id<>?"
                    parameters.append(exclude_request_id)
            if source_ids is not None:
                filters += (
                    " AND event_id IN (" + ",".join("?" for _ in source_ids) + ")"
                )
                parameters += list(source_ids)
            columns = "event_id,sequence,revision,segment_id,request_id,role,text,accepted_at,delivery,thread_id"
            title = (
                "(SELECT w.title FROM conversation_thread t JOIN conversation_workspace w "
                "ON w.project_id=t.project_id WHERE t.thread_id=e.thread_id) AS project_title, "
                "(SELECT t.project_id FROM conversation_thread t WHERE t.thread_id=e.thread_id) "
                "AS project_id"
            )
            if query is not None and not terms:
                rows = []
            elif query is not None:
                # BM25 relevance over the derived FTS5 index; the canonical row is
                # always re-read from conversation_event. Promote one best match
                # per role alongside its newest evidence; fill remaining slots by
                # recency so older full matches do not crowd out recent corrections.
                qualified = ",".join("e." + c for c in columns.split(","))
                sql = (
                    "WITH matched AS (SELECT "
                    + qualified
                    + ", -bm25(conversation_event_fts) AS term_matches FROM "
                    "conversation_event_fts JOIN conversation_event e "
                    "ON e.rowid=conversation_event_fts.rowid WHERE "
                    "conversation_event_fts MATCH ? AND "
                    + filters
                    + "), ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY role "
                    "ORDER BY accepted_at DESC,event_id DESC) AS recent_rank,"
                    "ROW_NUMBER() OVER (PARTITION BY role ORDER BY term_matches DESC,"
                    "accepted_at DESC,event_id DESC) AS relevance_rank FROM matched),"
                    " balanced AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY role "
                    "ORDER BY CASE WHEN recent_rank=1 THEN 0 "
                    "WHEN relevance_rank=1 THEN 1 ELSE 2 END,accepted_at DESC,event_id DESC) "
                    "AS role_rank FROM ranked) SELECT b."
                    + ",b.".join(columns.split(","))
                    + ", CASE WHEN recent_rank=1 THEN 2 WHEN relevance_rank=1 THEN 1 "
                    "ELSE 0 END AS search_priority, (SELECT w.title FROM conversation_thread t "
                    "JOIN conversation_workspace w ON w.project_id=t.project_id "
                    "WHERE t.thread_id=b.thread_id) AS project_title, (SELECT t.project_id FROM "
                    "conversation_thread t WHERE t.thread_id=b.thread_id) AS project_id "
                    "FROM balanced b"
                    + " ORDER BY role_rank,CASE role WHEN 'user' THEN 0 ELSE 1 END LIMIT ?"
                )
                parameters = [conversation_match_expression(terms), *parameters]
                rows = conn.execute(sql, (*parameters, limit + 1)).fetchall()
            else:
                sql = (
                    "SELECT "
                    + columns
                    + ", 0 AS search_priority, "
                    + title
                    + " FROM conversation_event e WHERE "
                    + filters
                    + (
                        # Equal timestamps (Windows' ~16 ms clock) keep their
                        # append order within a thread instead of a random id.
                        " ORDER BY accepted_at DESC,sequence DESC,event_id DESC LIMIT ?"
                        if project_wide or all_projects
                        else " ORDER BY sequence DESC LIMIT ?"
                    )
                )
                rows = conn.execute(sql, (*parameters, limit + 1)).fetchall()
            total = conn.execute(
                "SELECT count(*) FROM conversation_event e WHERE " + scope_sql,
                scope_parameters,
            ).fetchone()[0]
            truncated = len(rows) > limit
            rows = rows[:limit]
            if query is not None:
                rows.sort(key=lambda r: (r[7], r[0]), reverse=True)
            status = (
                "partial"
                if truncated
                or (query is None and source_ids is None and total > len(rows))
                else "complete"
            )
            if not rows and query is not None:
                status = "no_match"
            omissions = conn.execute(
                "SELECT count(*) FROM conversation_event e WHERE "
                + scope_sql
                + " AND role='tool' AND delivery='failed' AND instr(text,?)>0",
                (*scope_parameters, '"capture":"omitted"'),
            ).fetchone()[0]
            if omissions:
                status = "partial"
            if source_ids is not None and {r[0] for r in rows} != set(source_ids):
                raise PermissionError("source missing from selected project")
            return ArchiveSnapshot(
                selection,
                row[0],
                row[3],
                row[4],
                _sources(reversed(rows)),
                status,
                bool(row[2]),
                omissions,
                self.store.change_revision,
            )

        # An all-project read is bound to the whole owner catalog, never
        # presented as a read of the currently selected project.
        bound = CATALOG if all_projects else selection
        result = await self._perform(
            bound,
            material,
            "read",
            lambda p: self.store._bound_read(bound, material, permit=p, read=read),
        )

        if not self.current() or result.store_revision != self.store.change_revision:
            raise PermissionError("history changed before source release")
        return result
