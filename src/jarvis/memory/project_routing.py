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


_NAME_FILLER = frozenset({"my", "the", "a", "an", "our", "that", "this", "project"})


def _name_words(text):
    return [
        w for w in re.findall(r"\w+", normalize_name(text)) if w not in _NAME_FILLER
    ]


def _partial_matches(name, entries):
    """Soft routing: a short name selects a project whose title or alias holds
    all of its words ("the trip" -> "Nepal trip"). Several matches still need a
    clarification; no match still creates a project, as before."""
    words = set(_name_words(name))
    if not words:
        return []
    return [
        e
        for e in entries
        if normalize_name(e.title) != "general"
        and any(words <= set(_name_words(label)) for label in (e.title, *e.aliases))
    ]


class ProjectClarificationRequired(ValueError):
    """No project was created or switched; the owner must say which one."""

    def __init__(self, question):
        super().__init__("project clarification required: " + question)
        self.question = question


_SELECT_COMMAND = re.compile(
    r"^(?:let['’]?s\s+plan|plan|new conversation in|switch to|continue|resume|open project|what(?:'s| is) the status of)\s+(?:my\s+|the\s+|a\s+)?(.+?)[.?!]*$",
    re.IGNORECASE,
)
_CREATE_COMMANDS = (
    # "create a new project called Nepal", "start project for Goa trip"
    re.compile(
        r"^(?:please\s+)?(?:create|make|start|add)\s+(?:a\s+|an\s+)?(?:new\s+)?project"
        r"\s+(?:called\s+|named\s+|for\s+)?(?:my\s+|the\s+)?(.+?)[.?!]*$",
        re.IGNORECASE,
    ),
    # "create a nepal project", "make my Goa trip project"
    re.compile(
        r"^(?:please\s+)?(?:create|make|start|add)\s+(?:a\s+|an\s+|my\s+|the\s+)?(?:new\s+)?"
        r"(.+?)\s+project[.?!]*$",
        re.IGNORECASE,
    ),
    # "new project Nepal", "new project called Nepal"
    re.compile(r"^new\s+project\s+(?:called\s+|named\s+)?(.+?)[.?!]*$", re.IGNORECASE),
)
_UNPARSED_PROJECT_COMMAND = re.compile(
    r"\b(?:create|make|start|add|new|switch|open)\b.*\bproject\b", re.IGNORECASE
)


def parse_project_command(text):
    """Return (name, kind) for an explicit project command, else (None, None).

    kind is "create" or "plan" (asks for a new project) or "select".
    """
    for pattern in _CREATE_COMMANDS:
        match = pattern.match(text)
        if match and _name_words(match.group(1).strip(" .?!")):
            return match.group(1).strip(" .?!"), "create"
    match = _SELECT_COMMAND.search(text)
    if match:
        kind = (
            "plan"
            if re.match(r"^(?:let['’]?s\s+plan|plan)\b", text, re.IGNORECASE)
            else "select"
        )
        return match.group(1).strip(" .?!"), kind
    return None, None


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
        name, kind = parse_project_command(text)
        if name is None and _UNPARSED_PROJECT_COMMAND.search(text):
            # A project command we could not read must not fall through to
            # the current project as if it had succeeded.
            return ProjectRoutingDecision(
                "clarification",
                None,
                "",
                catalog.selection_revision,
            )
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
            if not matches and kind == "select":
                # "Plan/create ..." asks for a new project; switch/continue/
                # resume/open/status ask for an existing one, so only they
                # match partially.
                matches = _partial_matches(name, catalog.entries)
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
