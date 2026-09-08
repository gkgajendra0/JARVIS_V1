"""Owner-machine real-network smoke for the Step-6 research boundary.

This diagnostic uses the active JARVIS_AI_PROVIDER from the normal machine profile,
performs one real source-backed research call, and prints only bounded evidence.
It does not start voice, mutate memory, or switch providers.
"""

from __future__ import annotations

import argparse
import asyncio

from jarvis.config import JarvisConfig
from jarvis.knowledge.research import ResearchMode
from jarvis.knowledge.research_providers import build_current_research_service

_DEFAULT_QUERY = (
    "What is the current recommended Gemini API interface for new applications, "
    "and what does Google document about Google Search grounding in that interface?"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=_DEFAULT_QUERY)
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ResearchMode],
        default=ResearchMode.CURRENT.value,
    )
    return parser.parse_args()


async def _run(query: str, mode: ResearchMode) -> int:
    config = JarvisConfig.from_environment()
    service = build_current_research_service(provider=config.ai_provider)
    print(f"STEP6_SMOKE_PROVIDER: {service.provider_name}")
    print(f"STEP6_SMOKE_MODEL: {service.model_name}")
    print(f"STEP6_SMOKE_MODE: {mode.value}")
    try:
        result = await service.research(query, mode=mode)
    finally:
        await service.close()

    print(f"STEP6_SMOKE_RESEARCH_STATUS: {result.status.value}")
    print(f"STEP6_SMOKE_SOURCE_COUNT: {len(result.sources)}")
    print(f"STEP6_SMOKE_QUERY_COUNT: {len(result.executed_queries)}")
    for index, source in enumerate(result.sources[:10], start=1):
        print(
            f"STEP6_SMOKE_SOURCE_{index}: "
            f"{source.title} | {source.domain} | {source.url}"
        )
    for index, executed_query in enumerate(result.executed_queries[:10], start=1):
        print(f"STEP6_SMOKE_SEARCH_QUERY_{index}: {executed_query}")

    answer_preview = " ".join(result.answer.split())[:800]
    if answer_preview:
        print(f"STEP6_SMOKE_ANSWER_PREVIEW: {answer_preview}")
    if not result.ok:
        print(f"STEP6_SMOKE_REASON: {result.reason_code}")
        print("STEP6_SMOKE_STATUS: FAIL")
        return 1

    print("STEP6_SMOKE_STATUS: PASS")
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args.query, ResearchMode.parse(args.mode)))


if __name__ == "__main__":
    raise SystemExit(main())
