"""Resume an existing exact-source text lab with content-free failure diagnostics.

Extract this companion to a temporary file. PYTHONPATH selects the existing lab's
unchanged source; its own main verifies that commit, marked profile and OS lock.
No retry, provider fallback, source edit or additional model call is introduced.
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager, suppress
from functools import wraps


def _identifier(value):
    return (
        value if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.<>]{0,127}", value) else "redacted"
    )


def failure_report(exc):
    reasons = {
        "one memory tool or answer per model step required": "mixed_answer_or_tools",
        "empty project answer": "empty_answer",
    }
    frames = []
    trace = exc.__traceback__
    while trace is not None:
        frame = trace.tb_frame
        frames.append(
            {
                "module": _identifier(str(frame.f_globals.get("__name__", "unknown"))),
                "function": _identifier(frame.f_code.co_name),
                "line": trace.tb_lineno,
            }
        )
        trace = trace.tb_next
    return {
        "error": _identifier(type(exc).__name__),
        "reason": reasons.get(str(exc), "unclassified"),
        "frames": frames[-12:],
    }


@contextmanager
def trace_calls(provider_type, coordinator_type, *, emit=print):
    original_step = provider_type.step
    original_respond = coordinator_type.respond

    @wraps(original_step)
    async def step(self, *args, **kwargs):
        result = await original_step(self, *args, **kwargs)
        # Observation must never change normal results or failure behavior.
        with suppress(Exception):
            parsed = result.parsed
            shape = {
                "answer_present": bool(parsed.answer),
                "search_present": bool(parsed.search_query),
                "source_count": len(parsed.source_ids),
                "personal_count": len(parsed.personal_requests),
                "action_count": sum(
                    bool(v)
                    for v in (
                        parsed.search_query,
                        parsed.source_ids,
                        parsed.personal_requests,
                    )
                ),
            }
            emit("PROJECT_PROBE_STEP " + json.dumps(shape))
        return result

    @wraps(original_respond)
    async def respond(self, *args, **kwargs):
        try:
            return await original_respond(self, *args, **kwargs)
        except Exception as exc:
            with suppress(Exception):
                emit("PROJECT_PROBE_FAILURE " + json.dumps(failure_report(exc)))
            raise

    provider_type.step, coordinator_type.respond = step, respond
    try:
        yield
    finally:
        provider_type.step, coordinator_type.respond = original_step, original_respond


def main():
    if "--resume-lab" not in sys.argv[1:]:
        raise SystemExit(
            "Failure probe requires --resume-lab; preserve the existing profile."
        )
    from jarvis.voice.project_answer_provider import ProjectAnswerProvider
    from jarvis.voice.project_conversation import ProjectConversationCoordinator
    from jarvis.voice.project_memory_lab import main as lab_main

    print(
        "PROJECT PROBE: existing source/profile; response shapes and code locations only; no automatic retry."
    )
    with trace_calls(ProjectAnswerProvider, ProjectConversationCoordinator):
        lab_main()


if __name__ == "__main__":
    main()
