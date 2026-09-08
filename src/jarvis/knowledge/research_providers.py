"""Replaceable live-web search provider adapters for JARVIS Step 6."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from urllib.parse import urlparse

from exa_py import Exa

from jarvis.knowledge.research import (
    CurrentResearchService,
    EvidenceSource,
    ProviderResearchEvidence,
    ResearchMode,
    ResearchProvider,
    utc_now,
)

EXA_API_KEY_ENV = "EXA_API_KEY"


def _required_exa_api_key() -> str:
    value = os.getenv(EXA_API_KEY_ENV)
    if value is None or not value.strip():
        raise RuntimeError(
            f"{EXA_API_KEY_ENV} is required for the configured web-search provider"
        )
    return value.strip()


def _value(item: object, name: str) -> object | None:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _source_id(url: str) -> str:
    return f"web_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def _clean_domain(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.netloc.casefold().split("@")[-1].split(":")[0].removeprefix("www.")


def _excerpt(item: object) -> str:
    highlights = _value(item, "highlights")
    if isinstance(highlights, Sequence) and not isinstance(
        highlights, (str, bytes, bytearray)
    ):
        parts = [
            value.strip()
            for value in highlights
            if isinstance(value, str) and value.strip()
        ]
        if parts:
            return " [...] ".join(parts)
    text = _value(item, "text")
    return text.strip() if isinstance(text, str) else ""


def _published_at(item: object) -> str | None:
    for name in ("published_date", "publishedDate"):
        value = _value(item, name)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class ExaWebResearchProvider:
    """Retrieve source excerpts from Exa; never synthesize the final JARVIS answer."""

    provider_name = "exa"
    model_name = "exa-search"

    def __init__(self, *, num_results: int = 8) -> None:
        if not 1 <= num_results <= 10:
            raise ValueError("num_results must be between 1 and 10")
        self._num_results = num_results
        self._client: Exa | None = None

    def _get_client(self) -> Exa:
        if self._client is None:
            self._client = Exa(api_key=_required_exa_api_key())
        return self._client

    def research(self, query: str, mode: ResearchMode) -> ProviderResearchEvidence:
        del mode  # JARVIS applies evidence sufficiency after provider retrieval.
        response = self._get_client().search(
            query,
            type="auto",
            num_results=self._num_results,
            contents={"highlights": True},
        )
        retrieved_at = utc_now()
        raw_results = _value(response, "results")
        if not isinstance(raw_results, Sequence) or isinstance(
            raw_results, (str, bytes, bytearray)
        ):
            return ProviderResearchEvidence(sources=())

        sources: list[EvidenceSource] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            raw_url = _value(item, "url")
            if not isinstance(raw_url, str):
                continue
            url = raw_url.strip()
            if not url or url in seen_urls:
                continue
            domain = _clean_domain(url)
            if domain is None:
                continue
            title_value = _value(item, "title")
            title = (
                title_value.strip()
                if isinstance(title_value, str) and title_value.strip()
                else domain
            )
            sources.append(
                EvidenceSource(
                    source_id=_source_id(url),
                    url=url,
                    title=title,
                    domain=domain,
                    retrieved_at=retrieved_at,
                    excerpt=_excerpt(item),
                    published_at=_published_at(item),
                )
            )
            seen_urls.add(url)

        return ProviderResearchEvidence(sources=tuple(sources))

    def close(self) -> None:
        # exa-py exposes no sync client close requirement for this search path.
        self._client = None


def build_current_research_service(
    *,
    timeout_seconds: float = 30.0,
) -> CurrentResearchService:
    adapter: ResearchProvider = ExaWebResearchProvider()
    return CurrentResearchService(adapter, timeout_seconds=timeout_seconds)
