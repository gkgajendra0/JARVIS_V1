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


# Words too generic to identify a project on their own.
_GENERIC_NAME_WORDS = frozenset(
    {
        "trip", "trips", "plan", "plans", "planning", "project", "projects",
        "preparation", "prep", "notes", "note", "list", "ideas", "idea", "work",
        "home", "general", "new", "meeting", "meetings", "stuff", "things",
        "task", "tasks", "travel", "holiday", "vacation",
    }
)  # fmt: skip


def _distinctive_words(label):
    return {
        w for w in _name_words(label) if w not in _GENERIC_NAME_WORDS and len(w) > 2
    }


def _partial_matches(name, entries):
    """Similar names, in either direction: every word of one name is in the
    other ("the trip" -> "Nepal trip", "nepal trip" -> "nepal"). Several
    matches need a clarification; no match never creates anything."""
    words = set(_name_words(name))
    if not words:
        return []
    matches = []
    for e in entries:
        if normalize_name(e.title) == "general":
            continue
        for label in (e.title, *e.aliases):
            label_words = set(_name_words(label))
            if label_words and (words <= label_words or label_words <= words):
                matches.append(e)
                break
    return matches


class ProjectClarificationRequired(ValueError):
    """No project was created or switched; the owner must say which one."""

    def __init__(self, question):
        # The owner-facing question can name projects; keep it off the
        # exception text that generic handlers may log.
        super().__init__("project clarification required")
        self.question = question


_SELECT_COMMAND = re.compile(
    r"^(?:let['’]?s\s+plan|plan|new conversation in|switch to|continue|resume|open project)\s+(?:my\s+|the\s+|a\s+)?(.+?)[.?!]*$",
    re.IGNORECASE,
)
_POLITE = (
    r"^(?:(?:can|could|would|will)\s+(?:you|we)\s+|please\s+|let['’]?s\s+"
    r"|i\s+(?:want|would\s+like|['’]d\s+like|wanna)\s+to\s+|go\s+ahead\s+and\s+)*"
)
# Spoken commands often open with a discourse marker ("Okay. Create a project
# called X", "Hey Jarvis, switch to Y"). Only this closed set of lead-ins is
# removed, and only at the very start, so a command still has to be the whole
# remaining sentence: "I told him to create a project" is never a command.
_LEAD_IN = re.compile(
    r"^(?:(?:okay|ok|alright|all\s+right|right|so|well|um+|uh+|hmm+|hey|hi|hello"
    r"|jarvis|yes|yeah|yep|now|and|then|great|cool|fine|sure|thanks|thank\s+you|oh"
    r"|actually|acha|accha|achha|theek\s+hai|thik\s+hai|haan|chalo)"
    r"(?=$|[\s,.!;:\u2014-])[\s,.!;:\u2014-]*){1,4}",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def strip_lead_in(text: str) -> str:
    """Remove a short conversational lead-in, e.g. "Okay." or "Hey Jarvis,"."""
    return _LEAD_IN.sub("", text.strip(), count=1).strip()


def embedded_project_command(text: str):
    """A project command in a later sentence, e.g. "It went well. Create a
    project called Goa." Routing asks rather than guessing either way."""
    sentences = _SENTENCE_BREAK.split(text.strip())
    for sentence in sentences[1:]:
        name, kind = parse_project_command(sentence)
        if name is not None:
            return name, kind
    return None, None


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
    text = strip_lead_in(text)
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
    # What routing actually commits: created, switched, continued, resumed or
    # new_thread. Announcements and the model's routing note come from this.
    action: str = "continued"
    # Other existing projects a question names. Their history is read as
    # labelled evidence; the selection itself does not change.
    references: tuple[ProjectSelection, ...] = ()
    reference_titles: tuple[str, ...] = ()
    # Existing projects a question names only ambiguously ("Nepal" with both
    # "Nepal trip" and "Nepal trek"): neither is read; the answer asks which.
    ambiguous_reference_titles: tuple[str, ...] = ()
    # Shown to the owner when status is "clarification".
    question: str = ""

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
        command_text = strip_lead_in(text)
        if name is None and (
            _UNPARSED_PROJECT_COMMAND.match(command_text)
            or _CREATE_PROJECT_PREFIX.match(command_text)
        ):
            # A project command we could not read must not fall through to
            # the current project as if it had succeeded.
            return self._clarify(catalog, "")
        if name is None:
            embedded, embedded_kind = embedded_project_command(text)
            if embedded is not None:
                verb = (
                    "switch to"
                    if embedded_kind == "select"
                    else "create project called"
                )
                return self._clarify(
                    catalog,
                    f"Nothing was changed. If you want a project change, say just: "
                    f"'{verb} {embedded}'.",
                )
        if proposed_name is not None:
            # Model suggestions only refine an explicit project command. They
            # cannot silently reroute ordinary discussion or invent a label.
            if not name or normalize_name(proposed_name) != normalize_name(name):
                raise PermissionError("project proposal lacks exact explicit source")
            name = proposed_name
        if name:
            return self._command(catalog, text, name, kind)
        # Not a project command: questions and ordinary messages never change
        # the selection. Existing projects a message names are read as
        # labelled evidence for this answer only.
        current = self._current_or_general(catalog)
        references, ambiguous = self._named_projects(catalog, text, current)
        if current is None:
            return ProjectRoutingDecision(
                "ready",
                ProjectSelection(str(uuid4()), str(uuid4()), 0),
                "General",
                catalog.selection_revision,
                create=True,
                # Implicit default workspace is internal routing, not a spoken
                # project-create request. Keep the committed action for audit.
                announcement="",
                action="created",
                references=tuple(e.selection for e in references),
                reference_titles=tuple(e.title for e in references),
                ambiguous_reference_titles=ambiguous,
            )
        action = "resumed" if not self._announced and catalog.current else "continued"
        if catalog.current is None:
            # First use of an existing General workspace after no selection.
            action = "switched"
        return ProjectRoutingDecision(
            "ready",
            current.selection,
            current.title,
            catalog.selection_revision,
            current.archive_revision,
            # Ordinary speech must not announce an implicit General switch
            # or resume. Explicit project commands use _command below and
            # retain their spoken announcements.
            announcement=(
                "" if normalize_name(current.title) == "general"
                else self._announce(action, current.title)
            ),
            action=action,
            references=tuple(e.selection for e in references),
            reference_titles=tuple(e.title for e in references),
            ambiguous_reference_titles=ambiguous,
        )

    @staticmethod
    def _announce(action, title):
        return {
            "created": f"Created project {title}.",
            "switched": f"Switched to {title}.",
            "resumed": f"Resuming {title}.",
            "new_thread": f"New conversation in {title}.",
        }.get(action, "")

    def _clarify(self, catalog, question, candidates=()):
        return ProjectRoutingDecision(
            "clarification",
            None,
            "",
            catalog.selection_revision,
            candidates=tuple(sorted({e.selection.project_id for e in candidates})),
            question=question,
        )

    def _current_or_general(self, catalog):
        if catalog.current:
            return next(e for e in catalog.entries if e.selection == catalog.current)
        general = [e for e in catalog.entries if normalize_name(e.title) == "general"]
        if len(general) > 1:
            raise PermissionError("ambiguous General workspace")
        return general[0] if general else None

    @staticmethod
    def _named_projects(catalog, text, current):
        """Other existing projects a message names, read as evidence only.

        Exact title/alias mentions first. Otherwise a project is named when
        every DISTINCTIVE word of its title/alias appears in the message
        ("Nepal" -> "Nepal trip"); generic words ("trip", "plan") never name a
        project on their own. A word that would name several projects names
        none of them: they are returned as ambiguous, never guessed.
        """
        normalized = normalize_name(text)
        message_words = set(_words(normalized))
        candidates = [
            e
            for e in catalog.entries
            if normalize_name(e.title) != "general"
            and not (
                current is not None
                and e.selection.project_id == current.selection.project_id
            )
        ]
        named = {}
        for e in candidates:
            if any(
                re.search(
                    r"(?<!\w)" + re.escape(normalize_name(label)) + r"(?!\w)",
                    normalized,
                )
                for label in (e.title, *e.aliases)
            ):
                named.setdefault(e.selection.project_id, e)
        # Words the owner used for a project named exactly belong to it.
        exact_words = set().union(
            *(
                _distinctive_words(label)
                for e in named.values()
                for label in (e.title, *e.aliases)
            )
        )
        partial = {}
        for e in candidates:
            if e.selection.project_id in named:
                continue
            for label in (e.title, *e.aliases):
                distinctive = _distinctive_words(label)
                if distinctive and distinctive <= message_words:
                    if not distinctive & exact_words:
                        partial[e.selection.project_id] = (e, distinctive)
                    break
        # A distinctive word another (not exactly named) project also uses
        # makes the mention ambiguous: "Nepal" with "Nepal trip" and "Nepal
        # trek" names neither, even though only the trip fully matches.
        owners = {}
        for e in candidates:
            if e.selection.project_id in named:
                continue
            for label in (e.title, *e.aliases):
                for word in _distinctive_words(label) & message_words:
                    owners.setdefault(word, {})[e.selection.project_id] = e
        ambiguous = {}
        for project_id, (e, distinctive) in partial.items():
            sharers = {
                other_id: other
                for word in distinctive
                for other_id, other in owners.get(word, {}).items()
            }
            if len(sharers) > 1:
                ambiguous.update(sharers)
            else:
                named.setdefault(project_id, e)
        return (
            list(named.values())[:3],
            tuple(sorted({e.title for e in ambiguous.values()}))[:3],
        )

    def _command(self, catalog, text, name, kind):
        exact = [
            e
            for e in catalog.entries
            if normalize_name(name)
            in {normalize_name(e.title), *(normalize_name(a) for a in e.aliases)}
        ]
        similar = [] if exact else _partial_matches(name, catalog.entries)
        if len({e.selection.project_id for e in exact}) > 1:
            return self._clarify(catalog, "", exact)
        if kind == "create" and not exact:
            # Explicit creation creates only when the name is not taken.
            return self._create(catalog, name)
        if kind == "plan" and not exact:
            if similar:
                # "Plan my Nepal trip" while "nepal" exists: ask rather than
                # silently duplicating it.
                return self._clarify(catalog, "", similar)
            return self._create(catalog, name)
        matches = exact or similar
        if len({e.selection.project_id for e in matches}) > 1:
            return self._clarify(catalog, "", matches)
        if not matches:
            return self._clarify(
                catalog,
                f"No project called '{name}'. Say 'create project called {name}' "
                "to make one, or /projects to list them.",
            )
        entry = next(
            (e for e in matches if e.selection == catalog.current), matches[-1]
        )
        if strip_lead_in(text).casefold().startswith("new conversation in "):
            return ProjectRoutingDecision(
                "ready",
                ProjectSelection(
                    entry.selection.project_id, str(uuid4()), entry.selection.revision
                ),
                entry.title,
                catalog.selection_revision,
                announcement=self._announce("new_thread", entry.title),
                new_thread=True,
                action="new_thread",
            )
        already = (
            catalog.current is not None
            and entry.selection.project_id == catalog.current.project_id
        )
        action = (
            ("resumed" if not self._announced else "continued")
            if already
            else "switched"
        )
        return ProjectRoutingDecision(
            "ready",
            entry.selection,
            entry.title,
            catalog.selection_revision,
            entry.archive_revision,
            announcement=self._announce(action, entry.title),
            action=action,
        )

    def _create(self, catalog, name):
        return ProjectRoutingDecision(
            "ready",
            ProjectSelection(str(uuid4()), str(uuid4()), 0),
            name,
            catalog.selection_revision,
            create=True,
            announcement=self._announce("created", name),
            action="created",
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
