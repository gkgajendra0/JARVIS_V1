"""Persistent exact-name routing; transport identity never owns a project."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from uuid import uuid4

from jarvis.conversation import ConversationRole

from .project_conversations import ProjectSelection


def normalize_name(text):
    return " ".join(
        unicodedata.normalize("NFKC", text).casefold().strip(" .?!").split()
    )


@dataclass(frozen=True)
class ProjectRoutingDecision:
    status: str
    selection: ProjectSelection | None
    title: str
    expected_revision: int
    archive_revision: int = 0
    create: bool = False
    announcement: str = ""
    candidates: tuple[str, ...] = ()
    new_thread: bool = False

    def material(self):
        return {"operation": "select", **asdict(self)}


class ProjectRouter:
    def __init__(self, access):
        self.access = access
        self._announced = False

    async def resolve(self, conversation, turn, *, proposed_name=None):
        if turn.role is not ConversationRole.USER or not any(
            t is turn for t in conversation.turns
        ):
            raise PermissionError("accepted user routing source required")
        catalog = await self.access.catalog()
        text = turn.text.strip()
        explicit_id = re.fullmatch(
            r"select project (\S+)(?: thread (\S+))?", text, re.IGNORECASE
        )
        if explicit_id:
            owned = [
                e
                for e in catalog.entries
                if e.selection.project_id == explicit_id[1]
                and (explicit_id[2] is None or e.selection.thread_id == explicit_id[2])
            ]
            if not owned:
                raise ValueError("unknown owned project/thread identity")
            entry = next(
                (e for e in owned if e.selection == catalog.current), owned[-1]
            )
            return ProjectRoutingDecision(
                "ready",
                entry.selection,
                entry.title,
                catalog.selection_revision,
                entry.archive_revision,
                announcement=f"Selected {entry.title}.",
            )
        match = re.search(
            r"^(?:let['’]?s\s+plan|plan|new conversation in|switch to|continue|resume|open project|what(?:'s| is) the status of)\s+(?:my\s+|the\s+|a\s+)?(.+?)[.?!]*$",
            text,
            re.IGNORECASE,
        )
        name = match.group(1).strip(" .?!") if match else None
        if proposed_name is not None:
            # Model suggestions only refine an explicit project command. They
            # cannot silently reroute ordinary discussion or invent a label.
            if not name or normalize_name(proposed_name) != normalize_name(name):
                raise PermissionError("project proposal lacks exact explicit source")
            name = proposed_name
        if name:
            matches = [
                e
                for e in catalog.entries
                if normalize_name(name)
                in {normalize_name(e.title), *(normalize_name(a) for a in e.aliases)}
            ]
            projects = {e.selection.project_id for e in matches}
            if len(projects) > 1:
                return ProjectRoutingDecision(
                    "clarification",
                    None,
                    name,
                    catalog.selection_revision,
                    candidates=tuple(sorted(projects)),
                )
            if matches:
                entry = next(
                    (e for e in matches if e.selection == catalog.current), matches[-1]
                )
                if text.casefold().startswith("new conversation in "):
                    selection = ProjectSelection(
                        entry.selection.project_id,
                        str(uuid4()),
                        entry.selection.revision,
                    )
                    return ProjectRoutingDecision(
                        "ready",
                        selection,
                        entry.title,
                        catalog.selection_revision,
                        announcement=f"New conversation in {entry.title}.",
                        new_thread=True,
                    )
                return ProjectRoutingDecision(
                    "ready",
                    entry.selection,
                    entry.title,
                    catalog.selection_revision,
                    entry.archive_revision,
                    announcement=f"Selected {entry.title}.",
                )
            return ProjectRoutingDecision(
                "ready",
                ProjectSelection(str(uuid4()), str(uuid4()), 0),
                name,
                catalog.selection_revision,
                create=True,
                announcement=f"Selected {name}.",
            )
        question = text.endswith(("?", "？")) or bool(
            re.match(
                r"^(?:what|which|how|when|where|tell me|status)\b", text, re.IGNORECASE
            )
        )
        negated_switch = bool(
            re.search(
                r"(?:do not|don't|मत)\s+(?:switch|select|resume|open)\b",
                text,
                re.IGNORECASE,
            )
        )
        if question and not negated_switch:
            normalized = normalize_name(text)
            named = [
                e
                for e in catalog.entries
                if normalize_name(e.title) != "general"
                and any(
                    re.search(
                        r"(?<!\w)" + re.escape(normalize_name(label)) + r"(?!\w)",
                        normalized,
                    )
                    for label in (e.title, *e.aliases)
                )
            ]
            project_ids = {e.selection.project_id for e in named}
            if len(project_ids) > 1:
                return ProjectRoutingDecision(
                    "clarification",
                    None,
                    "named projects",
                    catalog.selection_revision,
                    candidates=tuple(sorted(project_ids)),
                )
            if named:
                entry = next(
                    (e for e in named if e.selection == catalog.current), named[-1]
                )
                return ProjectRoutingDecision(
                    "ready",
                    entry.selection,
                    entry.title,
                    catalog.selection_revision,
                    entry.archive_revision,
                    announcement=f"Selected {entry.title}.",
                )
        if catalog.current:
            entry = next(e for e in catalog.entries if e.selection == catalog.current)
            return ProjectRoutingDecision(
                "ready",
                entry.selection,
                entry.title,
                catalog.selection_revision,
                entry.archive_revision,
                announcement=f"Resuming {entry.title}." if not self._announced else "",
            )
        general = [e for e in catalog.entries if normalize_name(e.title) == "general"]
        if len(general) > 1:
            raise PermissionError("ambiguous General workspace")
        if general:
            e = general[0]
            return ProjectRoutingDecision(
                "ready",
                e.selection,
                e.title,
                catalog.selection_revision,
                e.archive_revision,
                announcement="Selected General.",
            )
        return ProjectRoutingDecision(
            "ready",
            ProjectSelection(str(uuid4()), str(uuid4()), 0),
            "General",
            catalog.selection_revision,
            create=True,
            announcement="Selected General.",
        )

    async def select(self, decision):
        if decision.status != "ready":
            raise ValueError("project clarification required")
        await self.access.select(decision)
        self._announced = True
        return decision

    async def commit_selection(self, decision, *, permit, expected_revision):
        return await self.access.commit_selection(
            decision, permit=permit, expected_revision=expected_revision
        )
