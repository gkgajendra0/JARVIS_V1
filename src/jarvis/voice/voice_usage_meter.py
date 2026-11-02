"""Content-free per-response voice measurements for lab comparisons.

Records, per wake session: response latency (end of owner speech -> Jarvis
starts speaking), Gemini Live response count, token usage reported by the
realtime model, and tool calls. No transcript or tool payload is written.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import monotonic

LOGGER = logging.getLogger(__name__)


class VoiceUsageMeter:
    def __init__(self, path: Path, *, mode: str) -> None:
        if mode not in {"baseline", "project_memory"}:
            raise ValueError("mode must be baseline or project_memory")
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
            "tokens": {
                "input": 0,
                "output": 0,
                "total": 0,
                "audio_in": 0,
                "text_in": 0,
            },
            "metric_events": 0,
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

        def on_metrics(event) -> None:
            metric = getattr(event, "metrics", None)
            if getattr(metric, "type", None) != "realtime_model_metrics":
                return
            state["metric_events"] += 1
            tokens = state["tokens"]
            for key, name in (
                ("input", "input_tokens"),
                ("output", "output_tokens"),
                ("total", "total_tokens"),
            ):
                value = getattr(metric, name, None)
                if isinstance(value, int):
                    tokens[key] += value
            details = getattr(metric, "input_token_details", None)
            for key, name in (("audio_in", "audio_tokens"), ("text_in", "text_tokens")):
                value = getattr(details, name, None)
                if isinstance(value, int):
                    tokens[key] += value

        def on_tools(event) -> None:
            for call in getattr(event, "function_calls", ()) or ():
                name = getattr(call, "name", "unknown")
                state["tool_calls"][name] = state["tool_calls"].get(name, 0) + 1

        def on_close() -> None:
            latencies = sorted(state["latency_ms"])
            row = dict(state)
            row["user_turns"] = sum(
                1 for t in bridge.conversation.turns if t.role.value == "user"
            )
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
        session.on("metrics_collected", on_metrics)
        session.on("function_tools_executed", on_tools)
        bridge.add_close_observer(on_close)
