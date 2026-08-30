from __future__ import annotations

import json
import subprocess
from dataclasses import replace

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    AuthoritySession,
    SessionSecurityEvent,
    StrongVerificationStatus,
    WindowsHelloVerifier,
    WindowsSessionGuard,
)


def proposal() -> ActionProposal:
    return ActionProposal.create(
        session_id="s1",
        capability="security",
        operation="verify",
        target={},
        parameters={},
        material_summary="confirm this protected action",
        attributes=ActionAttributes(financial_or_legal=True),
        origin=ActionOrigin.DIRECT_USER,
        now_monotonic=100.0,
    )


def test_windows_hello_is_unavailable_off_windows(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("jarvis.authority.verifier.sys.platform", "linux")
    result = WindowsHelloVerifier(helper).verify(proposal=proposal(), session_id="s1")
    assert result.status is StrongVerificationStatus.UNAVAILABLE
    assert result.reason_codes == ("not_windows",)


def test_windows_hello_maps_helper_result(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("jarvis.authority.verifier.sys.platform", "win32")

    completed = subprocess.CompletedProcess(
        args=[str(helper)],
        returncode=0,
        stdout=json.dumps({"status": "verified", "reason": "verified"}),
        stderr="",
    )
    monkeypatch.setattr(
        "jarvis.authority.verifier.subprocess.run", lambda *a, **k: completed
    )

    result = WindowsHelloVerifier(helper).verify(proposal=proposal(), session_id="s1")
    assert result.status is StrongVerificationStatus.VERIFIED
    assert result.verified


def test_windows_hello_rejects_session_mismatch(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "helper.exe"
    helper.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("jarvis.authority.verifier.sys.platform", "win32")
    result = WindowsHelloVerifier(helper).verify(
        proposal=proposal(), session_id="other"
    )
    assert result.status is StrongVerificationStatus.ERROR
    assert result.reason_codes == ("session_mismatch",)


class FakeProvider:
    def __init__(self, states: list[AuthoritySession]) -> None:
        self._states = iter(states)

    def current_session(self) -> AuthoritySession:
        return next(self._states)


def session(*, windows_id: int, unlocked: bool) -> AuthoritySession:
    return AuthoritySession(
        session_id=f"wts:{windows_id}",
        windows_session_id=windows_id,
        windows_user_sid_hash=None,
        active_unlocked=unlocked,
        generation=0,
        created_at_monotonic=100.0,
    )


def test_windows_session_guard_invalidates_on_lock() -> None:
    events: list[tuple[str, SessionSecurityEvent]] = []
    provider = FakeProvider(
        [
            session(windows_id=1, unlocked=True),
            session(windows_id=1, unlocked=False),
        ]
    )
    guard = WindowsSessionGuard(
        provider=provider, on_invalidate=lambda *event: events.append(event)
    )
    guard.poll()
    guard.poll()
    assert events == [("wts:1", SessionSecurityEvent.LOCK)]


def test_windows_session_guard_invalidates_on_user_switch() -> None:
    events: list[tuple[str, SessionSecurityEvent]] = []
    first = session(windows_id=1, unlocked=True)
    second = replace(first, session_id="wts:2", windows_session_id=2)
    guard = WindowsSessionGuard(
        provider=FakeProvider([first, second]),
        on_invalidate=lambda *event: events.append(event),
    )
    guard.poll()
    guard.poll()
    assert events == [("wts:1", SessionSecurityEvent.USER_SWITCH)]
