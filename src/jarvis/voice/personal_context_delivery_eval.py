"""Opt-in fictional PI-1C comparison, never a production memory bridge.

Uses the pinned JARVIS provider factory and Agent APIs. Four isolated sessions
compare an absent-context control, initial history, mid-session updates and
model-requested tool results. No devices, canonical memory or action tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from livekit.agents import function_tool
from livekit.agents.llm import ChatContext, ChatMessage

from jarvis.config import JarvisConfig
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.context_sync import provider_context_sync_capability
from jarvis.voice.livekit_session import create_voice_session


@dataclass(frozen=True)
class DeliveryCase:
    language: str
    fact: str
    question: str
    canary: str
    spoken_aliases: tuple[str, ...] = ()


DELIVERY_CASES = (
    DeliveryCase(
        "english",
        "FICTIONAL ONLY: Rhea's imaginary holiday codeword is brackenfold.",
        "For fictional Rhea, what exact holiday codeword was previously provided? "
        "Say unknown if it is unavailable. Reply in English.",
        "brackenfold",
    ),
    DeliveryCase(
        "hindi",
        "FICTIONAL ONLY: Rhea's imaginary recipe label is amberwhistle.",
        "काल्पनिक रिया की पहले बताई गई recipe का exact label क्या है? "
        "जानकारी नहीं है तो अज्ञात कहो। हिंदी में उत्तर दो।",
        "amberwhistle",
        ("एम्बरव्हिसल", "अम्बरव्हिसल"),
    ),
    DeliveryCase(
        "hinglish",
        "FICTIONAL ONLY: Rhea's imaginary reading stamp is cedarloop.",
        "Fictional Rhea ka pehle bataya reading stamp kya tha? "
        "Available nahi hai toh unknown bolo. Hinglish mein jawab do.",
        "cedarloop",
    ),
)
DELIVERY_PATHS = ("baseline", "initial_history", "mid_session_update", "tool_result")


def observe_canary(case: DeliveryCase, answer: str) -> tuple[bool, bool]:
    """Recognize fixed spoken-script aliases while preserving the literal result.

    This measures delivery only; token occurrence is not a usefulness score.
    """
    literal = bool(re.search(rf"\b{case.canary}\b", answer, re.IGNORECASE))
    return literal or any(alias in answer for alias in case.spoken_aliases), literal


def _minimal_config(config: JarvisConfig) -> JarvisConfig:
    if config.ai_provider != "gemini":
        raise ValueError("comparison requires the configured Gemini provider")
    # Do not copy owner machine routing preferences or memory settings into tests.
    return JarvisConfig(
        ai_provider=config.ai_provider,
        gemini_realtime_model=config.gemini_realtime_model,
        gemini_realtime_voice=config.gemini_realtime_voice,
        show_transcript=False,
    )


async def _run_path(
    path: str, config: JarvisConfig, timeout_seconds: float
) -> dict[str, Any]:
    session, bridge = create_voice_session(config)
    row: dict[str, Any] = {
        "path": path,
        "status": "INCONCLUSIVE",
        "turns": [],
        "session_metrics": [],
        "usage_capture_complete": False,
    }
    answers: list[str] = []
    metrics: list[dict[str, Any]] = []
    tool_calls = 0
    active_case = DELIVERY_CASES[0]
    turn_started = False

    def record(event: Any) -> None:
        item = getattr(event, "item", None)
        if (
            isinstance(item, ChatMessage)
            and item.role == "assistant"
            and not item.interrupted
            and item.text_content.strip()
        ):
            answers.append(item.text_content.strip())

    def record_metrics(event: Any) -> None:
        metric = event.metrics
        if getattr(metric, "type", None) == "realtime_model_metrics":
            metrics.append(
                {
                    name: getattr(metric, name, None)
                    for name in (
                        "ttft",
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                    )
                }
            )
            row["session_metrics"].append(metrics[-1])

    @function_tool
    async def lookup_fictional_profile() -> dict[str, Any]:
        """Retrieve Rhea's fictional saved fact relevant to the current question."""
        nonlocal tool_calls
        tool_calls += 1
        if tool_calls > 2:
            return {"status": "unavailable"}
        return {"status": "available", "fictional_only": True, "fact": active_case.fact}

    session.on("conversation_item_added", record)
    session.on("metrics_collected", record_metrics)
    try:
        async with asyncio.timeout(timeout_seconds):
            bridge.conversation.start()
            session.input.set_audio_enabled(False)
            agent = JarvisVoiceAgent(
                tools=[lookup_fictional_profile] if path == "tool_result" else []
            )
            if path == "initial_history":
                ctx = ChatContext()
                for case in DELIVERY_CASES:
                    ctx.add_message(role="user", content=case.fact)
                await agent.update_chat_ctx(ctx)
            await session.start(agent=agent)
            for case in DELIVERY_CASES:
                active_case = case
                tool_calls = 0
                answers.clear()
                metrics.clear()
                turn_started = True
                started = time.monotonic()
                if path == "mid_session_update":
                    ctx = agent.chat_ctx.copy()
                    ctx.add_message(role="user", content=case.fact)
                    await agent.update_chat_ctx(ctx)
                # A run tracks separate automatic post-tool generations too.
                await session.run(
                    user_input=case.question,
                    input_modality="text",
                )
                answer = " ".join(answers)
                observed, literal = observe_canary(case, answer)
                row["turns"].append(
                    {
                        "language": case.language,
                        "question": case.question,
                        "answer": answer,
                        "canary_observed": observed,
                        "literal_canary_observed": literal,
                        "tool_calls": tool_calls,
                        "whole_turn_seconds": round(time.monotonic() - started, 4),
                        "metrics": list(metrics),
                    }
                )
                turn_started = False
            row["status"] = "COMPLETED"
            row["usage_capture_complete"] = True
    except Exception as exc:  # noqa: BLE001 - no provider payload/credential output
        row["exception_type"] = type(exc).__name__
        if turn_started:
            row["failed_turn"] = {
                "language": active_case.language,
                "question": active_case.question,
                "answer": " ".join(answers),
                "metrics": list(metrics),
                "tool_calls": tool_calls,
                "usage_capture_complete": False,
            }
    finally:
        try:
            await asyncio.wait_for(session.aclose(), timeout=5)
        except Exception as exc:  # noqa: BLE001
            row["status"] = "INCONCLUSIVE"
            row["usage_capture_complete"] = False
            row["close_exception_type"] = type(exc).__name__
    return row


async def compare_delivery_paths(
    *, config: JarvisConfig, timeout_seconds: float = 90
) -> dict[str, Any]:
    """At most four sequential sessions; stop on the first transport failure."""
    if not 0 < timeout_seconds <= 120:
        raise ValueError("timeout must be positive and no greater than 120 seconds")
    config = _minimal_config(config)
    capability = provider_context_sync_capability(config)
    if not capability.automatic_mid_session_sync_supported:
        raise ValueError("configured adapter does not declare mid-session support")
    paths = []
    for path in DELIVERY_PATHS:
        try:
            row = await _run_path(path, config, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - also sanitize factory failures
            row = {
                "path": path,
                "status": "INCONCLUSIVE",
                "exception_type": type(exc).__name__,
                "turns": [],
            }
        paths.append(row)
        if row["status"] != "COMPLETED":
            break
    passed = len(paths) == 4 and all(
        row["status"] == "COMPLETED"
        and len(row["turns"]) == len(DELIVERY_CASES)
        and all(
            turn["answer"]
            and turn["canary_observed"] == (row["path"] != "baseline")
            and (row["path"] != "tool_result" or turn["tool_calls"] >= 1)
            for turn in row["turns"]
        )
        for row in paths
    )
    return {
        "status": "DELIVERY_OBSERVED" if passed else "INCONCLUSIVE",
        "provider": config.ai_provider,
        "model": config.gemini_realtime_model,
        "paths": paths,
        "fictional_only": True,
        "owner_memory_access": False,
        "production_runtime_modified": False,
        "microphone_or_camera": False,
        "billed_cost": None,
        "personalization_quality": "NOT_MEASURED",
        "deletion_revocation": "NOT_PROVEN_BY_CONTEXT_REMOVAL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-four-real-provider-tests", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    args = parser.parse_args()
    if not 5 <= args.timeout_seconds <= 120:
        parser.error("timeout-seconds must be between 5 and 120")
    if not args.allow_four_real_provider_tests:
        print(
            json.dumps(
                {
                    "status": "OFFLINE_PREFLIGHT_ONLY",
                    "provider_sessions": 0,
                    "fictional_only": True,
                }
            )
        )
        return 0
    # Standalone diagnostic process only: SDK exceptions can contain request data.
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(
            compare_delivery_paths(
                config=JarvisConfig.from_environment(),
                timeout_seconds=args.timeout_seconds,
            )
        )
    except Exception as exc:  # noqa: BLE001
        result = {"status": "INCONCLUSIVE", "exception_type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "DELIVERY_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
