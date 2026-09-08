"""Same-provider web research adapters for Gemini and OpenAI."""

from __future__ import annotations

from google import genai
from openai import OpenAI

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key
from jarvis.knowledge.provider_evidence import as_payload, extract_provider_evidence
from jarvis.knowledge.research import (
    CurrentResearchService,
    ProviderResearchEvidence,
    ResearchMode,
    ResearchProvider,
    utc_now,
)

DEFAULT_RESEARCH_MODELS = {
    "gemini": "gemini-3.7-flash",
    "openai": "gpt-5.2",
}


def _research_instructions(mode: ResearchMode) -> str:
    base = (
        "Research the user's exact question using live web search before answering. "
        "Do not claim you searched unless search actually ran. Prefer primary sources "
        "and current information where relevant. Keep the synthesis concise but "
        "complete. Do not invent URLs or source names."
    )
    if mode is ResearchMode.FACT_CHECK:
        return (
            f"{base} This is a fact-check. Corroborate important claims across more "
            "than one independent source when practical and state material disagreement."
        )
    if mode is ResearchMode.AUTHORITATIVE:
        return (
            f"{base} This requires authoritative evidence. Prioritize official "
            "government, regulator, standards body, academic, manufacturer, or other "
            "primary-domain sources appropriate to the question. If authoritative "
            "evidence cannot be found, say so plainly."
        )
    return f"{base} Prioritize fresh sources for time-sensitive claims."


class GeminiWebResearchProvider:
    provider_name = "gemini"

    def __init__(self, *, model: str, api_key: str) -> None:
        self.model_name = model
        self._client = genai.Client(api_key=api_key)

    def research(self, query: str, mode: ResearchMode) -> ProviderResearchEvidence:
        interaction = self._client.interactions.create(
            model=self.model_name,
            input=f"{_research_instructions(mode)}\n\nUSER QUESTION:\n{query}",
            tools=[{"type": "google_search"}],
            store=False,
        )
        return extract_provider_evidence(
            as_payload(getattr(interaction, "steps", ())),
            answer=str(getattr(interaction, "output_text", "") or ""),
            retrieved_at=utc_now(),
        )

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


class OpenAIWebResearchProvider:
    provider_name = "openai"

    def __init__(self, *, model: str, api_key: str) -> None:
        self.model_name = model
        self._client = OpenAI(api_key=api_key)

    def research(self, query: str, mode: ResearchMode) -> ProviderResearchEvidence:
        response = self._client.responses.create(
            model=self.model_name,
            instructions=_research_instructions(mode),
            input=query,
            tools=[{"type": "web_search"}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            store=False,
        )
        return extract_provider_evidence(
            as_payload(getattr(response, "output", ())),
            answer=str(getattr(response, "output_text", "") or ""),
            retrieved_at=utc_now(),
        )

    def close(self) -> None:
        self._client.close()


def build_current_research_service(
    *,
    provider: str,
    model: str | None = None,
    timeout_seconds: float = 60.0,
) -> CurrentResearchService:
    normalized = normalize_ai_provider(provider)
    resolved_model = (model or DEFAULT_RESEARCH_MODELS[normalized]).strip()
    if not resolved_model:
        raise ValueError("research model must not be empty")
    api_key = require_provider_api_key(normalized, purpose="web research")
    adapter: ResearchProvider
    if normalized == "gemini":
        adapter = GeminiWebResearchProvider(model=resolved_model, api_key=api_key)
    else:
        adapter = OpenAIWebResearchProvider(model=resolved_model, api_key=api_key)
    return CurrentResearchService(adapter, timeout_seconds=timeout_seconds)
