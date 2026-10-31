"""Request-bound project tools; a model never supplies its own read scope."""

from __future__ import annotations


class ProjectMemoryTools:
    def __init__(self, access, *, selection, request_id, is_current):
        self.access, self.selection, self.request_id = access, selection, request_id
        self._current = is_current
        self._searched = self._read = False
        self._allowed = set()

    def _check(self):
        if self._current() is not True or not self.access.current():
            raise PermissionError("project request no longer current")

    async def search_conversation_memory(self, project_id: str, query: str):
        self._check()
        if project_id != self.selection.project_id:
            raise PermissionError("cross-project search denied")
        if self._searched:
            raise PermissionError("archive search budget exhausted")
        self._searched = True
        result = await self.access.snapshot(
            self.selection, query=query, limit=8, project_wide=True
        )
        self._check()
        self._allowed.update(s.event.event_id for s in result.sources)
        return result

    async def read_conversation_sources(self, source_ids: tuple[str, ...]):
        self._check()
        if not set(source_ids) <= self._allowed:
            raise PermissionError("source outside this request's results")
        if self._read:
            raise PermissionError("source read budget exhausted")
        self._read = True
        result = await self.access.snapshot(
            self.selection, source_ids=source_ids, limit=16, project_wide=True
        )
        self._check()
        return result
