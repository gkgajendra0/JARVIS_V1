from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.knowledge.provider_evidence import extract_provider_evidence
from jarvis.knowledge.research import (
    CurrentResearchService,
    EvidenceSource,
    ProviderResearchEvidence,
    ResearchMode,
    ResearchStatus,
)
from jarvis.knowledge.research_providers import build_current_research_service
from jarvis.voice.research_tools import ResearchAgentTools


def _source(domain: str, path: str = "/") -> EvidenceSource:
    return EvidenceSource(
        source_id=f"src-{domain}-{path}",
        url=f"https://{domain}{path}",
        title=domain,
        domain=domain,
        retrieved_at=datetime.now(UTC),
    )


class _FakeProvider:
    provider_name = "fake"
    model_name = "fake-research"

    def __init__(
        self,
        evidence: ProviderResearchEvidence | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.evidence = evidence or ProviderResearchEvidence(answer="", sources=())
        self.error = error
        self.calls: list[tuple[str, ResearchMode]] = []
        self.closed = False

    def research(self, query: str, mode: ResearchMode) -> ProviderResearchEvidence:
        self.calls.append((query, mode))
        if self.error is not None:
            raise self.error
        return self.evidence

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("current", ResearchMode.CURRENT),
        ("FACT-CHECK", ResearchMode.FACT_CHECK),
        (" authoritative ", ResearchMode.AUTHORITATIVE),
    ],
)
def test_research_mode_parses_bounded_values(
    value: str,
    expected: ResearchMode,
) -> None:
    assert ResearchMode.parse(value) is expected


def test_research_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="unsupported research mode"):
        ResearchMode.parse("whatever")


@pytest.mark.asyncio
async def test_current_research_marks_one_source_as_web_researched() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="A current answer.",
            sources=(_source("example.com"),),
            executed_queries=("current example",),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research("What is current?", mode=ResearchMode.CURRENT)

    assert result.status is ResearchStatus.WEB_RESEARCHED
    assert result.ok is True
    assert result.executed_queries == ("current example",)
    assert provider.calls == [("What is current?", ResearchMode.CURRENT)]


@pytest.mark.asyncio
async def test_fact_check_requires_multiple_source_domains() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="One-source answer.",
            sources=(_source("example.com"),),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research("Is this claim true?", mode=ResearchMode.FACT_CHECK)

    assert result.status is ResearchStatus.INSUFFICIENT_EVIDENCE
    assert result.ok is False
    assert result.reason_code == "fact_check_requires_multiple_source_domains"


@pytest.mark.asyncio
async def test_fact_check_accepts_multi_source_research() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="Corroborated answer.",
            sources=(_source("one.example"), _source("two.example")),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research("Is this claim true?", mode=ResearchMode.FACT_CHECK)

    assert result.status is ResearchStatus.MULTI_SOURCE_RESEARCHED
    assert result.ok is True


@pytest.mark.asyncio
async def test_authoritative_mode_fails_closed_without_authoritative_domain() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="Secondary-only answer.",
            sources=(_source("random-blog.example"), _source("news.example")),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research(
        "What does the regulator require?",
        mode=ResearchMode.AUTHORITATIVE,
    )

    assert result.status is ResearchStatus.INSUFFICIENT_EVIDENCE
    assert result.reason_code == "authoritative_source_not_observed"


@pytest.mark.asyncio
async def test_authoritative_mode_accepts_observed_primary_domain() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="Official answer.",
            sources=(_source("example.gov"),),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research(
        "What does the regulator require?",
        mode=ResearchMode.AUTHORITATIVE,
    )

    assert result.status is ResearchStatus.AUTHORITATIVE_SOURCE_PRESENT
    assert result.ok is True


@pytest.mark.asyncio
async def test_authoritative_mode_accepts_curated_first_party_docs() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="Official product documentation.",
            sources=(_source("ai.google.dev", "/gemini-api/docs/models"),),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research(
        "What does Google document about Gemini?",
        mode=ResearchMode.AUTHORITATIVE,
    )

    assert result.status is ResearchStatus.AUTHORITATIVE_SOURCE_PRESENT
    assert result.ok is True


@pytest.mark.asyncio
async def test_authoritative_mode_does_not_trust_arbitrary_academic_domain() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="Academic page only.",
            sources=(_source("random-university.edu"),),
        )
    )
    service = CurrentResearchService(provider)

    result = await service.research(
        "What does the regulator require?",
        mode=ResearchMode.AUTHORITATIVE,
    )

    assert result.status is ResearchStatus.INSUFFICIENT_EVIDENCE
    assert result.reason_code == "authoritative_source_not_observed"


@pytest.mark.asyncio
async def test_provider_failure_becomes_research_unavailable() -> None:
    service = CurrentResearchService(
        _FakeProvider(error=RuntimeError("provider exploded"))
    )

    result = await service.research("What happened today?")

    assert result.status is ResearchStatus.RESEARCH_UNAVAILABLE
    assert result.ok is False
    assert result.reason_code == "research_provider_error"
    assert result.sources == ()


def test_provider_evidence_normalizes_queries_sources_and_citations() -> None:
    payload = [
        {
            "type": "google_search_call",
            "arguments": {"queries": ["first query", "second query"]},
        },
        {
            "type": "google_search_result",
            "result": [{"search_suggestions": [{"query": "first query"}]}],
        },
        {
            "type": "model_output",
            "content": [
                {
                    "type": "text",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://example.gov/report",
                            "title": "Official example",
                            "start_index": 4,
                            "end_index": 15,
                        }
                    ],
                }
            ],
        },
    ]

    evidence = extract_provider_evidence(
        payload,
        answer="Grounded answer.",
        retrieved_at=datetime.now(UTC),
    )

    assert evidence.answer == "Grounded answer."
    assert evidence.executed_queries == ("first query", "second query")
    assert len(evidence.sources) == 1
    assert evidence.sources[0].domain == "example.gov"
    assert len(evidence.citations) == 1
    assert evidence.citations[0].source_id == evidence.sources[0].source_id
    assert evidence.citations[0].start_index == 4
    assert evidence.citations[0].end_index == 15


def test_openai_style_search_sources_are_normalized() -> None:
    payload = [
        {
            "type": "web_search_call",
            "action": {
                "type": "search",
                "query": "latest source",
                "sources": [
                    {
                        "type": "url",
                        "url": "https://docs.example.com/latest",
                        "title": "Latest docs",
                    }
                ],
            },
        }
    ]

    evidence = extract_provider_evidence(
        payload,
        answer="Latest answer.",
        retrieved_at=datetime.now(UTC),
    )

    assert evidence.executed_queries == ("latest source",)
    assert [source.domain for source in evidence.sources] == ["docs.example.com"]


def test_research_builder_follows_active_ai_provider_without_needing_key_at_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    gemini = build_current_research_service(provider="gemini")
    openai = build_current_research_service(provider="openai")

    assert gemini.provider_name == "gemini"
    assert gemini.model_name == "gemini-3.8-flash"
    assert openai.provider_name == "openai"
    assert openai.model_name == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_voice_research_tool_uses_exact_latest_canonical_user_question() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(
            answer="Researched.",
            sources=(_source("example.com"),),
        )
    )
    service = CurrentResearchService(provider)
    conversation = ConversationSession(session_id="research-session")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Old question")
    conversation.accept_turn(ConversationRole.ASSISTANT, "Old answer")
    latest = conversation.accept_turn(
        ConversationRole.USER,
        "What changed in Snowflake today?",
    )
    tools = ResearchAgentTools(service, conversation)

    payload = await tools.research(mode="current")

    assert provider.calls == [
        ("What changed in Snowflake today?", ResearchMode.CURRENT)
    ]
    assert payload["ok"] is True
    assert latest.text == "What changed in Snowflake today?"


@pytest.mark.asyncio
async def test_research_service_closes_provider() -> None:
    provider = _FakeProvider()
    service = CurrentResearchService(provider)

    await service.close()

    assert provider.closed is True
