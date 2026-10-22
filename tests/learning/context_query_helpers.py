from dataclasses import replace
from uuid import uuid4

from jarvis.memory.types import AuthorityClass, MemorySourceClass


async def seed_item(h, label="City", kind="vehicle", **changes):
    template = h.plan.mutations[0]
    value = {**template.draft.value, "label": label, "value": label, "kind": kind}
    draft = replace(
        template.draft,
        predicate=f"owned_item_{uuid4().hex}",
        value=value,
        normalized_text=f"{label}; state=owned",
        **changes,
    )
    source = replace(
        template.source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    return await h.lifecycle.create(draft, source)


import asyncio
from contextlib import asynccontextmanager

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.voice.personal_context import PersonalContextSession


@asynccontextmanager
async def context_session(
    h,
    question="What vehicles do I own?",
    *,
    delegated=True,
    history="PREVIOUS-PRIVATE-TURN",
):
    c = ConversationSession()
    c.start()
    c.accept_turn(ConversationRole.USER, history)
    c.accept_turn(ConversationRole.USER, question)
    retired = []
    s = PersonalContextSession(
        conversation=c,
        retrieval=SemanticRetrievalService(h.reader),
        authority=None,
        retire=lambda: retired.append(True),
        learning_authority=h.authority if delegated else None,
        learning_grant=h.grant if delegated else None,
    )
    try:
        yield s, c, retired
    finally:
        s.close()
        await asyncio.sleep(0)
