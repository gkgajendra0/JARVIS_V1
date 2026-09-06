from __future__ import annotations

from pathlib import Path

PATH = Path("src/jarvis/memory/retrieval.py")


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    marker = """    async def retrieve_first_stage(\n"""
    if text.count(marker) != 1:
        raise RuntimeError("retrieve_first_stage marker changed")
    public_method = """    async def retrieve_exact_current_facet(\n        self,\n        facet: MemoryFacetKey,\n        *,\n        eligibility: RetrievalEligibility | None = None,\n    ) -> tuple[SemanticAssertionRecord, ...]:\n        \"\"\"Return all already-eligible current assertions for one exact facet.\"\"\"\n\n        if not isinstance(facet, MemoryFacetKey):\n            raise TypeError(\"facet must be a MemoryFacetKey\")\n        policy = eligibility or RetrievalEligibility.local()\n        if not isinstance(policy, RetrievalEligibility):\n            raise TypeError(\"eligibility must be RetrievalEligibility\")\n        return await self._worker.run(\n            lambda connection: self._retrieve_exact_current_facet_sync(\n                connection,\n                facet,\n                policy,\n            )\n        )\n\n"""
    text = text.replace(marker, public_method + marker)

    sync_marker = """    def _retrieve_sync(\n"""
    if text.count(sync_marker) != 1:
        raise RuntimeError("_retrieve_sync marker changed")
    sync_method = """    def _retrieve_exact_current_facet_sync(\n        self,\n        connection: Any,\n        facet: MemoryFacetKey,\n        eligibility: RetrievalEligibility,\n    ) -> tuple[SemanticAssertionRecord, ...]:\n        authorities = _enum_values(eligibility.authorities)\n        sensitivities = _enum_values(eligibility.sensitivities)\n        if not authorities or not sensitivities:\n            return ()\n        rows = connection.execute(\n            f\"\"\"\n            SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL}\n            FROM current_semantic_assertion\n            WHERE subject_scope = ?\n              AND subject = ?\n              AND predicate = ?\n              AND sensitivity IN ({_in_clause(sensitivities)})\n              AND source_id IN (\n                  SELECT source_id\n                  FROM memory_source\n                  WHERE authority_class IN ({_in_clause(authorities)})\n                    AND sensitivity IN ({_in_clause(sensitivities)})\n              )\n            ORDER BY assertion_id ASC\n            \"\"\",\n            (\n                facet.subject_scope,\n                facet.subject,\n                facet.predicate,\n                *sensitivities,\n                *authorities,\n                *sensitivities,\n            ),\n        ).fetchall()\n        return tuple(semantic_assertion_record_from_row(row) for row in rows)\n\n"""
    text = text.replace(sync_marker, sync_method + sync_marker)
    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
