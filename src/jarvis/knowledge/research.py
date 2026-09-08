"""Provider-neutral current research contracts and truth status for JARVIS."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

LOGGER = logging.getLogger(__name__)

MAX_TOOL_ANSWER_CHARS = 12_000
MAX_TOOL_SOURCES = 12
MAX_TOOL_QUERIES = 12

# This is deliberately a bounded trust registry, not a claim that every page on the
# internet can be classified authoritatively from its TLD. Government namespaces are
# strong deterministic signals; common first-party product/standards documentation
# used by JARVIS is curated explicitly. Unknown domains fail closed in authoritative
# mode until a later evidence-driven policy extension is approved.
_AUTHORITATIVE_GOVERNMENT_SUFFIXES = (".gov", ".gov.in", ".nic.in")
_AUTHORITATIVE_BASE_DOMAINS = frozenset(
    {
        "who.int",
        "rbi.org.in",
        "sebi.gov.in",
        "ai.google.dev",
        "developers.google.com",
        "cloud.google.com",
        "developers.openai.com",
        "platform.openai.com",
        "docs.livekit.io",
        "docs.snowflake.com",
        "docs.aws.amazon.com",
        "learn.microsoft.com",
        "developer.apple.com",
        "developer.android.com",
        "developer.nvidia.com",
        "docs.nvidia.com",
        "ietf.org",
        "w3.org",
        "nist.gov",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchMode(str, Enum):
    CURRENT = "current"
    FACT_CHECK = "fact_check"
    AUTHORITATIVE = "authoritative"

    @classmethod
    def parse(cls, value: str) -> ResearchMode:
        if not isinstance(value, str):
            raise TypeError("research mode must be a string")
        normalized = value.strip().casefold().replace("-", "_")
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                "unsupported research mode; use current, fact_check, or authoritative"
            ) from exc


class ResearchStatus(str, Enum):
    WEB_RESEARCHED = "web_researched"
    MULTI_SOURCE_RESEARCHED = "multi_source_researched"
    AUTHORITATIVE_SOURCE_PRESENT = "authoritative_source_present"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RESEARCH_UNAVAILABLE = "research_unavailable"


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    source_id: str
    url: str
    title: str
    domain: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    source_id: str
    start_index: int | None = None
    end_index: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderResearchEvidence:
    answer: str
    sources: tuple[EvidenceSource, ...]
    citations: tuple[EvidenceCitation, ...] = ()
    executed_queries: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchResult:
    status: ResearchStatus
    mode: ResearchMode
    answer: str
    sources: tuple[EvidenceSource, ...]
    citations: tuple[EvidenceCitation, ...]
    executed_queries: tuple[str, ...]
    researched_at: datetime
    provider: str
    model: str
    reason_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {
            ResearchStatus.WEB_RESEARCHED,
            ResearchStatus.MULTI_SOURCE_RESEARCHED,
            ResearchStatus.AUTHORITATIVE_SOURCE_PRESENT,
        }

    def to_tool_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "operation": "research_current",
            "status": self.status.value,
            "mode": self.mode.value,
            "answer": self.answer[:MAX_TOOL_ANSWER_CHARS],
            "sources": [
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "domain": source.domain,
                    "url": source.url,
                }
                for source in self.sources[:MAX_TOOL_SOURCES]
            ],
            "executed_queries": list(self.executed_queries[:MAX_TOOL_QUERIES]),
            "researched_at": self.researched_at.isoformat(),
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason_code,
            "truth_note": (
                "Captured web evidence is evidence, not automatic proof of every "
                "generated claim. If ok=false, do not present the result as verified."
            ),
        }


class ResearchProvider(Protocol):
    provider_name: str
    model_name: str

    def research(self, query: str, mode: ResearchMode) -> ProviderResearchEvidence: ...

    def close(self) -> None: ...


def _matches_base_domain(domain: str, base_domain: str) -> bool:
    return domain == base_domain or domain.endswith(f".{base_domain}")


def _is_authoritative_domain(domain: str) -> bool:
    normalized = domain.casefold().removeprefix("www.")
    if any(
        normalized.endswith(suffix)
        for suffix in _AUTHORITATIVE_GOVERNMENT_SUFFIXES
    ):
        return True
    return any(
        _matches_base_domain(normalized, base_domain)
        for base_domain in _AUTHORITATIVE_BASE_DOMAINS
    )


def _status_for_evidence(
    evidence: ProviderResearchEvidence,
    *,
    mode: ResearchMode,
) -> tuple[ResearchStatus, str | None]:
    if not evidence.answer:
        return ResearchStatus.RESEARCH_UNAVAILABLE, "research_answer_missing"
    if not evidence.sources:
        return ResearchStatus.INSUFFICIENT_EVIDENCE, "research_sources_missing"

    domains = {source.domain for source in evidence.sources}
    if mode is ResearchMode.AUTHORITATIVE:
        if not any(_is_authoritative_domain(domain) for domain in domains):
            return (
                ResearchStatus.INSUFFICIENT_EVIDENCE,
                "authoritative_source_not_observed",
            )
        return ResearchStatus.AUTHORITATIVE_SOURCE_PRESENT, None
    if mode is ResearchMode.FACT_CHECK and len(domains) < 2:
        return (
            ResearchStatus.INSUFFICIENT_EVIDENCE,
            "fact_check_requires_multiple_source_domains",
        )
    if len(domains) >= 2:
        return ResearchStatus.MULTI_SOURCE_RESEARCHED, None
    return ResearchStatus.WEB_RESEARCHED, None


class CurrentResearchService:
    """Use one active provider for web research without owning conversation truth."""

    def __init__(
        self, provider: ResearchProvider, *, timeout_seconds: float = 60.0
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("research timeout_seconds must be greater than zero")
        self._provider = provider
        self._timeout_seconds = float(timeout_seconds)

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    async def research(
        self,
        query: str,
        *,
        mode: ResearchMode = ResearchMode.CURRENT,
    ) -> ResearchResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("research query must not be empty")
        researched_at = utc_now()
        try:
            evidence = await asyncio.wait_for(
                asyncio.to_thread(self._provider.research, query.strip(), mode),
                timeout=self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            LOGGER.warning(
                "Current research timed out | provider=%s | model=%s",
                self.provider_name,
                self.model_name,
            )
            return self._unavailable(mode, researched_at, "research_timeout")
        except Exception:
            LOGGER.exception(
                "Current research provider failed | provider=%s | model=%s",
                self.provider_name,
                self.model_name,
            )
            return self._unavailable(mode, researched_at, "research_provider_error")

        status, reason = _status_for_evidence(evidence, mode=mode)
        return ResearchResult(
            status=status,
            mode=mode,
            answer=evidence.answer,
            sources=evidence.sources,
            citations=evidence.citations,
            executed_queries=evidence.executed_queries,
            researched_at=researched_at,
            provider=self.provider_name,
            model=self.model_name,
            reason_code=reason,
        )

    def _unavailable(
        self,
        mode: ResearchMode,
        researched_at: datetime,
        reason_code: str,
    ) -> ResearchResult:
        return ResearchResult(
            status=ResearchStatus.RESEARCH_UNAVAILABLE,
            mode=mode,
            answer="",
            sources=(),
            citations=(),
            executed_queries=(),
            researched_at=researched_at,
            provider=self.provider_name,
            model=self.model_name,
            reason_code=reason_code,
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._provider.close)
