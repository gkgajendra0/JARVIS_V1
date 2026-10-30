"""Original event archive on the existing encrypted memory workers.

SQLite is used only in tests. This component neither opens a connection nor
creates a key. Its authority is explicitly bound by the runtime; absent binding
all operations fail closed. A caller's boolean callback is not a history permit.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC

from jarvis.authority.conversation_history import ConversationHistoryAuthority
from jarvis.authority.proposal import canonical_json

from .project_conversations import (
    ConversationEvent,
    ConversationReceipt,
    ProjectSelection,
)
from .worker import SerialConnectionWorker


def archive_digest(material: dict) -> str:
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _event_material(event: ConversationEvent) -> dict:
    material = asdict(event)
    material["accepted_at"] = event.accepted_at.astimezone(UTC).isoformat(
        timespec="microseconds"
    )
    return material


class ProjectConversationStore:
    def __init__(
        self,
        *,
        writer: SerialConnectionWorker,
        reader: SerialConnectionWorker,
        authority: ConversationHistoryAuthority | None = None,
    ) -> None:
        if not isinstance(writer, SerialConnectionWorker) or not isinstance(
            reader, SerialConnectionWorker
        ):
            raise TypeError("canonical encrypted memory workers required")
        self._writer, self._reader = writer, reader
        self._authority = None
        if authority is not None:
            self.bind_authority(authority)

    def bind_authority(self, authority: ConversationHistoryAuthority) -> None:
        if not isinstance(authority, ConversationHistoryAuthority):
            raise TypeError("explicit conversation history issuer required")
        if self._authority is not None and self._authority is not authority:
            raise PermissionError("history issuer already bound")
        self._authority = authority

    @staticmethod
    def creation_material(selection: ProjectSelection, title: str) -> dict:
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise ValueError("invalid project title")
        return {
            "operation": "create_project",
            "selection": asdict(selection),
            "title": title.strip(),
        }

    @staticmethod
    def append_material(
        selection: ProjectSelection, event: ConversationEvent, expected_revision: int
    ) -> dict:
        if not isinstance(event, ConversationEvent):
            raise TypeError("canonical event required")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("archive revision required")
        return {
            "operation": "append",
            "selection": asdict(selection),
            "event": _event_material(event),
            "expected_revision": expected_revision,
        }

    def _issuer(self) -> ConversationHistoryAuthority:
        if self._authority is None:
            raise PermissionError("history authority not bound")
        return self._authority

    def _validate(self, permit, selection, material, *, source=None) -> None:
        issuer = self._issuer()
        issuer.validate_write(permit)
        binding = issuer.child_binding(permit)
        if (
            binding.operation != "admit"
            or binding.payload_sha256 != archive_digest(material)
            or binding.targets
            != (("project", selection.project_id), ("thread", selection.thread_id))
        ):
            raise PermissionError("history action binding changed")
        if source is not None and (
            issuer.source_for(permit) is not source
            or binding.source_receipt_id != source.event_id
        ):
            raise PermissionError("history source identity changed")

    async def create_project(
        self, selection: ProjectSelection, title: str, *, permit
    ) -> None:
        material = self.creation_material(selection, title)
        if selection.revision != 0:
            raise ValueError("new project must start at epoch zero")
        issuer = self._issuer()

        def create(connection):
            with issuer.commit_scope(permit):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._validate(permit, selection, material)
                    existing = connection.execute(
                        "SELECT title,epoch,forgotten_at FROM conversation_workspace WHERE project_id=?",
                        (selection.project_id,),
                    ).fetchone()
                    if existing is not None and existing != (
                        material["title"],
                        0,
                        None,
                    ):
                        raise PermissionError("project identity already exists")
                    connection.execute(
                        "INSERT OR IGNORE INTO conversation_workspace(project_id,title) VALUES (?,?)",
                        (selection.project_id, material["title"]),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO conversation_thread(thread_id,project_id) VALUES (?,?)",
                        (selection.thread_id, selection.project_id),
                    )
                    if connection.execute(
                        "SELECT project_id FROM conversation_thread WHERE thread_id=?",
                        (selection.thread_id,),
                    ).fetchone() != (selection.project_id,):
                        raise PermissionError("thread belongs to a different project")
                    self._validate(permit, selection, material)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

        await self._writer.run(create)

    async def append_event(
        self,
        selection: ProjectSelection,
        event: ConversationEvent,
        *,
        permit,
        expected_revision: int,
    ) -> ConversationReceipt:
        material = self.append_material(selection, event, expected_revision)
        content = _event_material(event)
        digest = archive_digest(
            content
        )  # retry identity excludes expected archive revision
        issuer = self._issuer()

        def append(connection):
            with issuer.commit_scope(permit):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._validate(permit, selection, material, source=event)
                    row = connection.execute(
                        "SELECT w.epoch,w.retention_paused,w.forgotten_at,t.archive_revision,t.last_sequence "
                        "FROM conversation_thread t JOIN conversation_workspace w ON w.project_id=t.project_id "
                        "WHERE t.thread_id=? AND w.project_id=?",
                        (selection.thread_id, selection.project_id),
                    ).fetchone()
                    if (
                        row is None
                        or row[0] != selection.revision
                        or row[1]
                        or row[2] is not None
                    ):
                        raise PermissionError(
                            "project missing, paused, forgotten or epoch changed"
                        )
                    previous = connection.execute(
                        "SELECT thread_id,sequence,revision,payload_sha256 FROM conversation_event WHERE event_id=?",
                        (event.event_id,),
                    ).fetchone()
                    if previous is not None:
                        if previous[0] != selection.thread_id or previous[3] != digest:
                            raise PermissionError(
                                "event identity reused with different content or project"
                            )
                        receipt = ConversationReceipt(
                            event.event_id,
                            previous[0],
                            previous[1],
                            previous[2],
                            "duplicate",
                        )
                    else:
                        if row[3] != expected_revision:
                            raise PermissionError("archive revision changed")
                        sequence, revision = row[4] + 1, row[3] + 1
                        connection.execute(
                            "INSERT INTO conversation_event(event_id,thread_id,sequence,revision,segment_id,request_id,"
                            "role,text,accepted_at,delivery,payload_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                event.event_id,
                                selection.thread_id,
                                sequence,
                                revision,
                                event.segment_id,
                                event.request_id,
                                event.role,
                                event.text,
                                content["accepted_at"],
                                event.delivery,
                                digest,
                            ),
                        )
                        connection.execute(
                            "UPDATE conversation_thread SET archive_revision=?,last_sequence=? WHERE thread_id=?",
                            (revision, sequence, selection.thread_id),
                        )
                        receipt = ConversationReceipt(
                            event.event_id,
                            selection.thread_id,
                            sequence,
                            revision,
                            "committed",
                        )
                    self._validate(permit, selection, material, source=event)
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise

        return await self._writer.run(append)
