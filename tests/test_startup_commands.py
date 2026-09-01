from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import jarvis.dev_supervisor as supervisor


class FakeControl:
    def child_environment(self) -> dict[str, str]:
        return {"JARVIS_TEST_CONTROL": "1"}


def test_dev_supervisor_launches_same_production_runtime_as_jarvis_voice(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = SimpleNamespace(pid=12345)

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)

    process = supervisor._start_jarvis(Path("."), FakeControl())  # type: ignore[arg-type]

    assert process is sentinel
    assert captured["args"] == [
        supervisor.sys.executable,
        "-m",
        "jarvis.voice.production_runtime",
    ]
    assert captured["kwargs"]["env"]["JARVIS_TEST_CONTROL"] == "1"  # type: ignore[index]
