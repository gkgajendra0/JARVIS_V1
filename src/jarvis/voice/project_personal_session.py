"""One owner approval per personal-fact session for project conversations.

The first personal question in a session opens Windows Hello once. Later
personal questions reuse that read-only grant until it expires (30 minutes
absolute, 10 minutes idle) or Windows is locked. Nothing is opened for
questions that never need personal facts.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4


class PersonalReadSession:
    """Holds the process's current read-only personal-context grant."""

    def __init__(self, issuer, *, provider="gemini"):
        # ``issuer`` may be the issuer itself or a callable returning it, so the
        # authority is only resolved when a personal read is actually needed.
        self._issuer = issuer
        self._provider = provider
        self._grant = None
        self._lock = asyncio.Lock()
        self.opened = 0

    @property
    def issuer(self):
        if callable(self._issuer) and not hasattr(self._issuer, "open"):
            self._issuer = self._issuer()
        return self._issuer

    async def active_grant(self):
        async with self._lock:
            if self._grant is not None:
                state = await asyncio.to_thread(self.issuer.validate, self._grant)
                if state.status == "active":
                    return self._grant
                self._grant = None
            # Raises PermissionError when the owner declines or Hello fails.
            self._grant = await asyncio.to_thread(
                self.issuer.open, str(uuid4()), self._provider
            )
            self.opened += 1
            return self._grant

    def close(self, reason="lab_closed"):
        grant, self._grant = self._grant, None
        if grant is not None:
            self.issuer.revoke(grant, reason)


class LazyPersonalContext:
    """Per-request personal context that asks for the session grant only on use."""

    def __init__(self, build, session):
        self._build = build
        self._session = session
        self._inner = None
        self._closed = False

    @property
    def _query_projection(self):
        return getattr(self._inner, "_query_projection", None)

    async def query_for_question(self, requests):
        if self._closed:
            return {"status": "denied", "facts": []}
        if self._inner is None:
            try:
                grant = await self._session.active_grant()
            except PermissionError:
                return {
                    "status": "denied",
                    "facts": [],
                    "reason": "personal_session_not_approved",
                }
            if self._closed:
                return {"status": "denied", "facts": []}
            self._inner = self._build(self._session.issuer, grant)
        return await self._inner.query_for_question(requests)

    async def _facts_current(self):
        return True if self._inner is None else await self._inner._facts_current()

    async def _validate(self):
        return False if self._inner is None else await self._inner._validate()

    def close(self, **kwargs):
        self._closed = True
        if self._inner is not None:
            self._inner.close(**kwargs)
