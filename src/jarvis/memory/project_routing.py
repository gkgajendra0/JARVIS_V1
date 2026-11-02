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
    return [w for w in _words(normalize_name(text)) if w not in _NAME_FILLER]


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
        # The owner-facing question can name projects; keep it off the
        # exception text that generic handlers may log.
        super().__init__("project clarification required")
        self.question = question


_SELECT_COMMAND = re.compile(
    r"^(?:let['’]?s\s+plan|plan|new conversation in|switch to|continue|resume|open project|what(?:'s| is) the status of)\s+(?:my\s+|the\s+|a\s+)?(.+?)[.?!]*$",
    re.IGNORECASE,
)
_POLITE = r"^(?:(?:can|could|would|will)\s+you\s+|please\s+)*"
_KEYWORD = r"(?P<kw>called|named)\s+"
_CREATE_COMMANDS = (
    # "create project Nepal", "create a new project called Nepal",
    # "can you create a project for Nepal?"
    re.compile(
        _POLITE + r"(?:create|add)\s+(?:a\s+|an\s+)?(?:new\s+)?project"
        r"\s+(?:" + _KEYWORD + r"|for\s+)?(?:my\s+|the\s+)?(?P<name>.+?)[.?!]*$",
        re.IGNORECASE,
    ),
    # "start a project for Goa trip"; start/make need an explicit name keyword
    # so "start a new project at work" is not read as a project named "at work".
    re.compile(
        _POLITE + r"(?:make|start)\s+(?:a\s+|an\s+)?(?:new\s+)?project"
        r"\s+(?:" + _KEYWORD + r"|for\s+)(?:my\s+|the\s+)?(?P<name>.+?)[.?!]*$",
        re.IGNORECASE,
    ),
    # "create a nepal project" (create only: "make progress on my thesis
    # project" and "add this to the project" are not commands)
    re.compile(
        _POLITE
        + r"create\s+(?:a\s+|an\s+|my\s+|the\s+)?(?:new\s+)?(?P<name>.+?)\s+project[.?!]*$",
        re.IGNORECASE,
    ),
    # "new project called Nepal" ("new project ideas are welcome" is not)
    re.compile(
        r"^new\s+project\s+" + _KEYWORD + r"(?P<name>.+?)[.?!]*$", re.IGNORECASE
    ),
)
# Text that is plainly a create-project command. If its name cannot be read,
# routing asks instead of letting the turn fall through as conversation.
_CREATE_PROJECT_PREFIX = re.compile(
    _POLITE
    + r"(?:(?:create|add)\s+(?:a\s+|an\s+)?(?:new\s+)?project|new\s+project\s+(?:called|named))\b",
    re.IGNORECASE,
)
_UNPARSED_PROJECT_COMMAND = re.compile(
    _POLITE
    + r"(?:(?:create|start|add)\s+(?:a\s+|an\s+)?(?:new\s+)?project|new\s+project)[.?!]*$",
    re.IGNORECASE,
)
# Words that show a captured "name" is really part of a sentence.
_NOT_A_NAME = frozenset(
    [
        "a",
        "an",
        "the",
        "my",
        "new",
        "for",
        "to",
        "on",
        "with",
        "of",
        "at",
        "in",
        "into",
        "from",
        "about",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "and",
        "or",
        "but",
        "so",
        "if",
        "when",
        "then",
        "will",
        "would",
        "can",
        "could",
        "should",
        "sure",
        "please",
        "me",
        "you",
        "we",
        "i",
    ]
)


def _words(text):
    """Letters, combining marks and digits stay together (Devanagari-safe)."""
    words, current = [], []
    for character in unicodedata.normalize("NFKC", text):
        if unicodedata.category(character)[0] in "LMN":
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return [w.casefold() for w in words]


def _project_name(raw, *, explicit=False):
    """A plausible project name, else None.

    After "called"/"named" any 1-8 words are accepted ("Sure Shot", "Trip to
    Nepal"). Otherwise 1-4 words without sentence words, so "create a timeline
    for the project" is not read as a project.
    """
    text = re.sub(r"\s+please$", "", raw.strip(" .?!,"), flags=re.IGNORECASE)
    words = _words(text)
    if explicit:
        return text if 1 <= len(words) <= 8 else None
    if not 1 <= len(words) <= 4 or any(w in _NOT_A_NAME for w in words):
        return None
    return text


def parse_project_command(text):
    """Return (name, kind) for an explicit project command, else (None, None).

    kind is "create" or "plan" (asks for a new project) or "select".
    """
    for pattern in _CREATE_COMMANDS:
        match = pattern.match(text)
        if match:
            explicit = bool(match.groupdict().get("kw"))
            name = _project_name(match.group("name"), explicit=explicit)
            if name:
                return name, "create"
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
        if name is None and (
            _UNPARSED_PROJECT_COMMAND.match(text) or _CREATE_PROJECT_PREFIX.match(text)
        ):
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
