"""Owner-machine PI-1C Gemini/LiveKit live context acceptance probe.

Never touches canonical JARVIS memory, microphones, cameras, Work, or actions.
Synthetic test persona only. Actual provider calls require an explicit CLI
flag; standard invocation is offline and prints configuration diagnostics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

_SYNTHETIC_FACT = (
    "FICTIONAL TEST DATA ONLY. Synthetic person Rhea previously stated: "
    "My imaginary holiday codeword is brackenfold."
)
_QUESTION = (
    "For fictional person Rhea only, what is the exact holiday codeword "
    "from prior provided context? If unknown, reply 'unknown'."
)
_CANARY = "brackenfold"


def evaluate_probe_response(response: str) -> str:
    """No numeric quality claim without a captured, transcribed answer."""
    if not isinstance(response, str) or not response.strip():
        return "NO_TEXT_TRANSCRIPT"
    normalized = " ".join(re.findall(r"[a-z]+", response.lower()))
    if _CANARY in normalized.replace(" ", ""):
        return "SYNTHETIC_CANARY_OBSERVED"
    return "CANARY_NOT_OBSERVED"


async def run_live_probe(*, timeout_seconds: float = 60.0) -> dict[str, Any]:
    """One isolated live Gemini session, no owner data and no persistence."""
    from livekit.agents.llm import ChatContext, ChatMessage

    from jarvis.config import JarvisConfig
    from jarvis.voice.agent import JarvisVoiceAgent
    from jarvis.voice.context_sync import provider_context_sync_capability
    from jarvis.voice.livekit_session import create_voice_session

    config = JarvisConfig.from_environment()
    if config.ai_provider != "gemini":
        raise RuntimeError("live acceptance probe requires configured Gemini")
    capability = provider_context_sync_capability(config)
    if not capability.automatic_mid_session_sync_supported:
        raise RuntimeError("configured model does not support mid-session context sync")
    session, bridge = create_voice_session(config)
    observed: list[str] = []

    def record(event: Any) -> None:
        item = getattr(event, "item", None)
        if (
            isinstance(item, ChatMessage)
            and item.role == "assistant"
            and not item.interrupted
        ):
            text = item.text_content.strip()
            if text:
                observed.append(text)

    session.on("conversation_item_added", record)
    bridge.conversation.start()
    try:
        session.input.set_audio_enabled(False)
        await asyncio.wait_for(
            session.start(agent=JarvisVoiceAgent(tools=[])), timeout_seconds
        )
        # The synthetic data are sent as ordinary previous user context, not
        # as system instructions. Tool calls and real personal memories are absent.
        ctx = ChatContext()
        ctx.add_message(role="user", content=_SYNTHETIC_FACT)
        await asyncio.wait_for(session.update_chat_ctx(ctx), timeout_seconds)
        handle = session.generate_reply(
            instructions=_QUESTION,
            allow_interruptions=True,
            input_modality="text",
        )
        await asyncio.wait_for(handle.wait_for_playout(), timeout_seconds)
        error = handle.exception()
        if error is not None:
            raise RuntimeError(type(error).__name__)
        result = evaluate_probe_response(" ".join(observed))
        return {
            "status": "completed",
            "result": result,
            "expected_synthetic_canary": _CANARY,
            "assistant_transcript_present": bool(observed),
            "memory_write": False,
            "owner_data_access": False,
            "voice_runtime_modified": False,
            "provider": capability.provider,
            "model": capability.model,
        }
    finally:
        await session.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-one-real-provider-test",
        action="store_true",
        help="Explicitly allow one synthetic Gemini realtime provider session",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not 5.0 <= args.timeout_seconds <= 120.0:
        parser.error("timeout-seconds must be 5 to 120")
    if not args.allow_one_real_provider_test:
        print(
            json.dumps(
                {
                    "status": "OFFLINE_PREFLIGHT_ONLY",
                    "would_run_live_provider": False,
                    "fictional_only": True,
                    "owner_memory_access": False,
                    "context_delivery_test": "NOT_RUN",
                    "next": "Explicit opt-in flag and owner-machine Gemini credentials required",
                },
                indent=2,
            )
        )
        return 0
    try:
        result = asyncio.run(run_live_probe(timeout_seconds=args.timeout_seconds))
    except Exception as exc:  # noqa: BLE001 - sanitize all provider failures
        # Never print model turns or API key; preserve only exception class.
        print(
            json.dumps(
                {
                    "status": "INCONCLUSIVE_OR_FAILED",
                    "exception_type": type(exc).__name__,
                    "fictional_only": True,
                    "no_production_memory_access": True,
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["result"] == "SYNTHETIC_CANARY_OBSERVED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
