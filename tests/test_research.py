from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.knowledge.research import (
    CurrentResearchService,
    EvidenceSource,
    ProviderResearchEvidence,
    ResearchMode,
    ResearchStatus,
)
from jarvis.knowledge.research_providers import (
    ExaWebResearchProvider,
    build_current_research_service,
)
from jarvis.voice.research_tools import ResearchAgentTools


def _source(
    domain: str, path: str = "/", *, excerpt: str = "evidence"
) -> EvidenceSource:
    return EvidenceSource(
        source_id=f"src-{domain}-{path}",
        url=f"https://{domain}{path}",
        title=domain,
        domain=domain,
        retrieved_at=datetime.now(UTC),
        excerpt=excerpt,
    )


class _FakeProvider:
    provider_name = "fake"
    model_name = "fake-search"

    def __init__(
        self,
        evidence: ProviderResearchEvidence | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.evidence = evidence or ProviderResearchEvidence(sources=())
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


class _QuotaError(RuntimeError):
    status_code = 429


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("current", ResearchMode.CURRENT),
        ("FACT-CHECK", ResearchMode.FACT_CHECK),
        (" authoritative ", ResearchMode.AUTHORITATIVE),
    ],
)
def test_research_mode_parses_bounded_values(
    value: str, expected: ResearchMode
) -> None:
    assert ResearchMode.parse(value) is expected


def test_research_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="unsupported research mode"):
        ResearchMode.parse("whatever")


@pytest.mark.asyncio
async def test_current_research_marks_one_source_as_web_researched() -> None:
    provider = _FakeProvider(
        ProviderResearchEvidence(sources=(_source("example.com"),))
    )
    service = CurrentResearchService(provider)

    result = await service.research("current example", mode=ResearchMode.CURRENT)

    assert result.status is ResearchStatus.WEB_RESEARCHED
    assert result.ok is True
    assert result.query == "current example"
    assert provider.calls == [("current example", ResearchMode.CURRENT)]


@pytest.mark.asyncio
async def test_fact_check_requires_multiple_source_domains() -> None:
    service = CurrentResearchService(
        _FakeProvider(ProviderResearchEvidence(sources=(_source("example.com"),)))
    )

    result = await service.research("Is this true?", mode=ResearchMode.FACT_CHECK)

    assert result.status is ResearchStatus.INSUFFICIENT_EVIDENCE
    assert result.reason_code == "fact_check_requires_multiple_source_domains"


@pytest.mark.asyncio
async def test_fact_check_accepts_multiple_source_domains() -> None:
    service = CurrentResearchService(
        _FakeProvider(
            ProviderResearchEvidence(
                sources=(_source("one.example"), _source("two.example"))
            )
        )
    )

    result = await service.research("Is this true?", mode=ResearchMode.FACT_CHECK)

    assert result.status is ResearchStatus.MULTI_SOURCE_RESEARCHED
    assert result.ok is True


@pytest.mark.asyncio
async def test_authoritative_mode_accepts_curated_first_party_docs() -> None:
    service = CurrentResearchService(
        _FakeProvider(
            ProviderResearchEvidence(
                sources=(_source("ai.google.dev", "/gemini-api/docs/models"),)
            )
        )
    )

    result = await service.research(
        "What does Google document?", mode=ResearchMode.AUTHORITATIVE
    )

    assert result.status is ResearchStatus.AUTHORITATIVE_SOURCE_PRESENT
    assert result.ok is True


@pytest.mark.asyncio
async def test_authoritative_mode_fails_closed_for_unknown_domain() -> None:
    service = CurrentResearchService(
        _FakeProvider(
            ProviderResearchEvidence(sources=(_source("random-university.edu"),))
        )
    )

    result = await service.research(
        "What does the regulator require?", mode=ResearchMode.AUTHORITATIVE
    )

    assert result.status is ResearchStatus.INSUFFICIENT_EVIDENCE
    assert result.reason_code == "authoritative_source_not_observed"


@pytest.mark.asyncio
async def test_provider_quota_failure_keeps_exact_failure_class() -> None:
    service = CurrentResearchService(
        _FakeProvider(error=_QuotaError("quota exceeded for this account"))
    )

    result = await service.research("What happened today?")

    assert result.status is ResearchStatus.RESEARCH_UNAVAILABLE
    assert result.reason_code == "research_quota_exhausted"
    assert result.sources == ()


def test_exa_provider_normalizes_realistic_sdk_results() -> None:
    class _FakeExa:
        def search(self, query: str, **kwargs: object):
            assert query == "latest Gemini API"
            assert kwargs["type"] == "auto"
            assert kwargs["contents"] == {"highlights": True}
            return {
                "results": [
                    {
                        "title": "Gemini API docs",
                        "url": "https://ai.google.dev/gemini-api/docs",
                        "publishedDate": "2026-09-02T00:00:00Z",
                        "highlights": ["Gemini 3.8 Flash is generally available."],
                    }
                ]
            }

    provider = ExaWebResearchProvider()
    provider._client = _FakeExa()  # type: ignore[assignment]

    evidence = provider.research("latest Gemini API", ResearchMode.CURRENT)

    assert len(evidence.sources) == 1
    source = evidence.sources[0]
    assert source.domain == "ai.google.dev"
    assert source.excerpt == "Gemini 3.8 Flash is generally available."
    assert source.published_at == "2026-09-02T00:00:00Z"


def test_research_builder_is_independent_of_active_ai_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    gemini_runtime = build_current_research_service(provider="gemini")
    openai_runtime = build_current_research_service(provider="openai")

    assert gemini_runtime.provider_name == "exa"
    assert openai_runtime.provider_name == "exa"
    assert gemini_runtime.model_name == "exa-search"
    assert openai_runtime.model_name == "exa-search"


@pytest.mark.asyncio
async def test_voice_brain_can_issue_subquery_but_canonical_turn_remains_anchored() -> (
    None
):
    provider = _FakeProvider(
        ProviderResearchEvidence(sources=(_source("docs.snowflake.com"),))
    )
    service = CurrentResearchService(provider)
    conversation = ConversationSession(session_id="research-session")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Old question")
    conversation.accept_turn(ConversationRole.ASSISTANT, "Old answer")
    latest = conversation.accept_turn(
        ConversationRole.USER,
        "Research what changed in Snowflake today and verify the release notes.",
    )
    tools = ResearchAgentTools(service, conversation)

    payload = await tools.research(
        "Snowflake release notes September 2026",
        mode="authoritative",
    )

    assert provider.calls == [
        ("Snowflake release notes September 2026", ResearchMode.AUTHORITATIVE)
    ]
    assert payload["ok"] is True
    assert payload["canonical_user_turn_id"] == latest.turn_id


@pytest.mark.asyncio
async def test_research_service_closes_provider() -> None:
    provider = _FakeProvider()
    service = CurrentResearchService(provider)

    await service.close()

    assert provider.closed is True
