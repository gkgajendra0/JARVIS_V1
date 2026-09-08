"""Normalize provider-specific web-search outputs into JARVIS evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from urllib.parse import urlparse

from jarvis.knowledge.research import (
    EvidenceCitation,
    EvidenceSource,
    ProviderResearchEvidence,
)


def as_payload(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): as_payload(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [as_payload(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return as_payload(model_dump(exclude_none=True))
    return str(value)


def _source_id(url: str) -> str:
    return f"web_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def _source_from_node(
    node: dict[str, object],
    *,
    retrieved_at: datetime,
) -> EvidenceSource | None:
    raw_url = node.get("url")
    if not isinstance(raw_url, str):
        return None
    url = raw_url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    domain = parsed.netloc.casefold().split("@")[-1].split(":")[0].removeprefix("www.")
    raw_title = node.get("title") or node.get("name")
    title = raw_title.strip() if isinstance(raw_title, str) else domain
    return EvidenceSource(
        source_id=_source_id(url),
        url=url,
        title=title or domain,
        domain=domain,
        retrieved_at=retrieved_at,
    )


def extract_provider_evidence(
    payload: object,
    *,
    answer: str,
    retrieved_at: datetime,
) -> ProviderResearchEvidence:
    """Handle Gemini/OpenAI citation/search shapes without leaking SDK types."""

    sources_by_url: dict[str, EvidenceSource] = {}
    citations: list[EvidenceCitation] = []
    queries: list[str] = []

    def walk(node: object, *, parent_type: str = "") -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, parent_type=parent_type)
            return
        if not isinstance(node, dict):
            return

        node_type = str(node.get("type", parent_type) or "").casefold()
        source = _source_from_node(node, retrieved_at=retrieved_at)
        if source is not None:
            existing = sources_by_url.get(source.url)
            if existing is None or (
                existing.title == existing.domain and source.title != source.domain
            ):
                sources_by_url[source.url] = source
            if "citation" in node_type or "start_index" in node or "end_index" in node:
                start = node.get("start_index")
                end = node.get("end_index")
                citations.append(
                    EvidenceCitation(
                        source_id=source.source_id,
                        start_index=(
                            start
                            if isinstance(start, int) and not isinstance(start, bool)
                            else None
                        ),
                        end_index=(
                            end
                            if isinstance(end, int) and not isinstance(end, bool)
                            else None
                        ),
                    )
                )

        for key in ("queries", "search_queries"):
            values = node.get(key)
            if isinstance(values, list):
                queries.extend(
                    value.strip()
                    for value in values
                    if isinstance(value, str) and value.strip()
                )
        query = node.get("query")
        if isinstance(query, str) and query.strip() and "search" in node_type:
            queries.append(query.strip())

        skipped = {"url", "title", "name", "queries", "search_queries", "query"}
        for key, value in node.items():
            if key not in skipped:
                walk(value, parent_type=node_type)

    walk(as_payload(payload))
    return ProviderResearchEvidence(
        answer=answer.strip(),
        sources=tuple(sources_by_url.values()),
        citations=tuple(citations),
        executed_queries=tuple(dict.fromkeys(queries)),
    )
