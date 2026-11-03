"""Which accepted turns may enter the project conversation archive.

Shared by the text lab, the voice lab and owner-activated production voice so
every path applies the same rule: bounded size, no restricted topics and no
recognisable secrets. An excluded turn is recorded only as an omission marker.
"""

from __future__ import annotations

from jarvis.conversation import ConversationTurn
from jarvis.memory.explicit import MemorySecretRejectedError, reject_prohibited_secret
from jarvis.memory.topic_continuity_policy import _RESTRICTED


def standard_history_source(turn):
    if (
        not isinstance(turn, ConversationTurn)
        or len(turn.text.encode("utf-8")) > 8000
        or _RESTRICTED.search(turn.text)
    ):
        return False
    try:
        reject_prohibited_secret(predicate="", value=turn.text)
    except MemorySecretRejectedError:
        return False
    return True
