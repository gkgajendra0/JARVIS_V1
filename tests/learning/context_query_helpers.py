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
