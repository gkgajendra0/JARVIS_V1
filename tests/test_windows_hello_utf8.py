from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import jarvis.authority.verifier as verifier_module
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.types import ActionAttributes, ActionOrigin
from jarvis.authority.verifier import StrongVerificationStatus, WindowsHelloVerifier


def _proposal(message: str) -> ActionProposal:
    return ActionProposal.create(
        session_id="unicode-session",
        capability="visual:desktop.control",
        operation="execute_visual_desktop_task",
        target={"app": "Apple Music"},
        parameters={"task": message},
        material_summary=message,
        attributes=ActionAttributes(generic_visual_control=True),
        origin=ActionOrigin.DIRECT_USER,
        ttl_seconds=120,
        now_monotonic=100.0,
        proposal_id="unicode-proposal",
        nonce="unicode-nonce",
    )


def test_windows_hello_verifier_sends_unicode_material_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = tmp_path / "Jarvis.WindowsHelloVerifier.exe"
    helper.write_bytes(b"test")
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"status":"verified","reason":"verified"}',
            stderr="",
        )

    monkeypatch.setattr(verifier_module.sys, "platform", "win32")
    monkeypatch.setattr(verifier_module.subprocess, "run", fake_run)

    message = "एप्पल म्यूजिक में रेट्रो बॉलीवुड प्लेलिस्ट शफल पर चलाओ"
    result = WindowsHelloVerifier(helper).verify(
        proposal=_proposal(message),
        session_id="unicode-session",
    )

    assert result.status is StrongVerificationStatus.VERIFIED
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "strict"
    assert captured["text"] is True
    assert message in str(captured["input"])
