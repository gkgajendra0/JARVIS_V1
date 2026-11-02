"""Content-free per-response voice measurements for lab comparisons.

Records, per wake session: response latency (end of owner speech -> Jarvis
starts speaking), Gemini Live response count, per-response token usage from
LiveKit's ``session_usage_updated`` (the deprecated ``metrics_collected`` is not
used), and tool calls. No transcript or tool payload is written.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import monotonic

LOGGER = logging.getLogger(__name__)

# Our name -> LLMModelUsage attribute (livekit.agents.metrics.usage, 1.8.x).
_USAGE_FIELDS = {
    "input": "input_tokens",
    "input_cached": "input_cached_tokens",
    "input_audio": "input_audio_tokens",
    "input_text": "input_text_tokens",
    "output": "output_tokens",
    "output_audio": "output_audio_tokens",
    "output_text": "output_text_tokens",
}


class VoiceUsageMeter:
    def __init__(self, path: Path, *, mode: str, allowed_tools=None) -> None:
        if mode not in {"baseline", "project_memory"}:
            raise ValueError("mode must be baseline or project_memory")
        self._allowed = None if allowed_tools is None else frozenset(allowed_tools)
        self._path = Path(path)
        self._mode = mode
        self._sessions = 0

    def attach(self, session, bridge) -> None:
        self._sessions += 1
        state = {
            "mode": self._mode,
            "session": self._sessions,
            "responses": 0,
            "latency_ms": [],
            "tool_calls": {},
            "tokens": dict.fromkeys(_USAGE_FIELDS, 0),
            "per_response_input": [],
            "usage_updates": 0,
            "disallowed_tool_calls": 0,
        }
        user_stopped = {"at": None}

        def on_user_state(event) -> None:
            if event.new_state == "listening" and event.old_state == "speaking":
                user_stopped["at"] = monotonic()
            elif event.new_state == "speaking":
                user_stopped["at"] = None

        def on_agent_state(event) -> None:
            if event.new_state != "speaking":
                return
            state["responses"] += 1
            if user_stopped["at"] is not None:
                state["latency_ms"].append(
                    round((monotonic() - user_stopped["at"]) * 1000, 1)
                )
                user_stopped["at"] = None

        previous: dict[tuple, dict[str, int]] = {}

        def on_usage(event) -> None:
            """LiveKit 1.8 ``session_usage_updated``: cumulative per model.

            Gemini Live reports each response's prompt as the WHOLE session
            context so far, so the cumulative input grows ~quadratically with
            turns. The per-response deltas show that growth; their sum is input
            processed across responses, not unique text and not a billing claim.
            """
            usage = getattr(event, "usage", None)
            for model in getattr(usage, "model_usage", ()) or ():
                if getattr(model, "type", None) != "llm_usage":
                    continue
                key = (getattr(model, "provider", ""), getattr(model, "model", ""))
                current = {
                    name: getattr(model, attr, 0) or 0
                    for name, attr in _USAGE_FIELDS.items()
                }
                before = previous.get(key, dict.fromkeys(_USAGE_FIELDS, 0))
                delta = {name: current[name] - before[name] for name in _USAGE_FIELDS}
                previous[key] = current
                if not any(delta.values()):
                    continue
                state["usage_updates"] += 1
                for name, value in delta.items():
                    state["tokens"][name] += value
                state["per_response_input"].append(delta["input"])

        def on_tools(event) -> None:
            for call in getattr(event, "function_calls", ()) or ():
                name = getattr(call, "name", "unknown")
                state["tool_calls"][name] = state["tool_calls"].get(name, 0) + 1
                if self._allowed is not None and name not in self._allowed:
                    # Cannot happen when restrict_tools holds; recorded loudly if it does.
                    state["disallowed_tool_calls"] += 1
                    LOGGER.error("Disallowed tool call in isolated lab | tool=%s", name)

        def on_close() -> None:
            latencies = sorted(state["latency_ms"])
            row = dict(state)
            row["user_turns"] = sum(
                1 for t in bridge.conversation.turns if t.role.value == "user"
            )
            inputs = row.pop("per_response_input")
            row["input_per_response"] = {
                "values": inputs,
                "first": inputs[0] if inputs else None,
                "peak": max(inputs) if inputs else None,
            }
            row["latency_ms"] = {
                "count": len(latencies),
                "median": latencies[len(latencies) // 2] if latencies else None,
                "max": latencies[-1] if latencies else None,
                "values": latencies,
            }
            try:
                with self._path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
            except OSError:
                LOGGER.warning("Voice usage row could not be written")
            LOGGER.info("Voice usage | %s", json.dumps(row, sort_keys=True))

        session.on("user_state_changed", on_user_state)
        session.on("agent_state_changed", on_agent_state)
        session.on("session_usage_updated", on_usage)
        session.on("function_tools_executed", on_tools)
        bridge.add_close_observer(on_close)
