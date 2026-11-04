"""Built-in Windows Hello consent (replaces the compiled .NET helper).

Smart App Control blocks a locally compiled, unsigned helper. The built-in
helper runs in the signed Python runtime and calls the same Windows API. These
tests cover its contract, its wiring into the verifier and preflight, and the
OPA probe diagnostics. The WinRT calls themselves run on the Windows CI job
(``windows-hello-helper``) and in the owner's live check.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.authority import tooling
from jarvis.authority import windows_hello_consent as consent
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.types import ActionAttributes, ActionOrigin
from jarvis.authority.verifier import StrongVerificationStatus, WindowsHelloVerifier


def _proposal() -> ActionProposal:
    return ActionProposal.create(
        session_id="s1",
        capability="memory:history.forget",
        operation="forget",
        target={},
        parameters={},
        material_summary="forget what was said about the Thar",
        attributes=ActionAttributes(financial_or_legal=True),
        origin=ActionOrigin.DIRECT_USER,
        now_monotonic=100.0,
    )


def _run_helper(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(tooling.builtin_windows_hello_command()),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


# -- the helper process --------------------------------------------------------


def test_builtin_command_is_the_signed_runtime_in_isolated_mode():
    command = tooling.builtin_windows_hello_command()
    assert command[0] == sys.executable
    assert command[1] == "-I"
    assert Path(command[2]) == Path(consent.__file__)


def test_helper_imports_only_the_standard_library():
    # Required by ``-I`` (no project path) and by the trust argument: the
    # child loads nothing except the signed runtime and Windows DLLs.
    tree = ast.parse(Path(consent.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "ctypes", "json", "sys", "time", "uuid"}


def test_contract_probe_runs_the_real_helper_without_a_prompt():
    completed = _run_helper("{}")
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "status": "error",
        "reason": "invalid_request",
    }
    tooling.probe_windows_hello_helper_contract()  # the default is the built-in


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        '{"message": ""}',
        '{"message": "   "}',
        '{"message": 5}',
        '{"message": "ok", "extra": 1}',
        '{"action": "availability", "message": "x"}',
        '{"action": "verify"}',
    ],
)
def test_invalid_requests_are_refused(raw):
    assert consent.parse_request(raw) is None


def test_off_windows_the_helper_reports_unavailable(monkeypatch):
    if sys.platform == "win32":
        pytest.skip("covered by the Windows CI job")
    completed = _run_helper(json.dumps({"message": "Authorize JARVIS action: x"}))
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "status": "unavailable",
        "reason": "not_windows",
    }


def test_only_windows_verified_maps_to_verified():
    assert consent.verification_response(0) == ("verified", "verified")
    for value in range(1, 7):
        assert consent.verification_response(value)[0] != "verified"
    assert consent.verification_response(99) == ("failed", "verification_failed")
    assert consent.availability_response(0) == ("available", "available")
    assert consent.availability_response(2) == (
        "not_configured",
        "not_configured_for_user",
    )
    assert consent.availability_response(42)[0] == "unavailable"


def test_winrt_interface_ids():
    # IAsyncOperation<UserConsentVerificationResult>, as in the Windows SDK
    # (the Windows CI job also compares every IID with the SDK headers).
    assert str(consent.IID_ASYNC_VERIFICATION_RESULT) == (
        "fd596ffd-2318-558f-9dbe-d21df43764a5"
    )
    assert str(consent.IID_USER_CONSENT_VERIFIER_INTEROP) == (
        "39e050c3-4e74-441a-8dc0-b81104df949c"
    )
    assert str(consent.IID_USER_CONSENT_VERIFIER_STATICS) == (
        "af4f3f91-564c-4ddc-b8b5-973447627c65"
    )


class _FakeWinRt:
    def __init__(self, log):
        self.log = log

    def initialize(self):
        self.log.append("init")

    def uninitialize(self):
        self.log.append("uninit")

    def owner_window(self):
        self.log.append("window")
        return 1234

    def destroy_window(self, hwnd):
        self.log.append(("destroy", hwnd))


@pytest.mark.parametrize(
    ("availability", "expected", "prompted"),
    [
        (0, ("verified", "verified"), True),
        (2, ("not_configured", "not_configured_for_user"), False),
        (1, ("unavailable", "device_not_present"), False),
    ],
)
def test_run_prompts_only_when_hello_is_available(
    monkeypatch, availability, expected, prompted
):
    log = []
    monkeypatch.setattr(consent, "_WinRt", lambda: _FakeWinRt(log))
    monkeypatch.setattr(consent, "_set_dpi_awareness", lambda: None)
    monkeypatch.setattr(consent, "check_availability", lambda w, **k: availability)

    def request(winrt, hwnd, message, **kwargs):
        log.append(("request", hwnd, message))
        return 0

    monkeypatch.setattr(consent, "request_verification", request)
    assert consent.run({"message": "Authorize JARVIS action: x"}) == expected
    assert ("request", 1234, "Authorize JARVIS action: x") in log or not prompted
    assert ("window" in log) is prompted
    assert log[0] == "init" and log[-1] == "uninit"


def test_the_owner_window_is_destroyed_when_the_request_fails(monkeypatch):
    log = []
    monkeypatch.setattr(consent, "_WinRt", lambda: _FakeWinRt(log))
    monkeypatch.setattr(consent, "_set_dpi_awareness", lambda: None)
    monkeypatch.setattr(consent, "check_availability", lambda w, **k: 0)

    def request(*args, **kwargs):
        raise consent.WinRtError("request_verification", 0x80070005)

    monkeypatch.setattr(consent, "request_verification", request)
    with pytest.raises(consent.WinRtError):
        consent.run({"message": "x"})
    assert ("destroy", 1234) in log and log[-1] == "uninit"


def test_availability_action_never_prompts(monkeypatch):
    log = []
    monkeypatch.setattr(consent, "_WinRt", lambda: _FakeWinRt(log))
    monkeypatch.setattr(consent, "check_availability", lambda w, **k: 0)
    monkeypatch.setattr(
        consent, "request_verification", lambda *a, **k: pytest.fail("prompted")
    )
    assert consent.run({"action": "availability"}) == ("available", "available")
    assert "window" not in log


def test_winrt_failures_are_errors_never_verified(monkeypatch):
    import io

    monkeypatch.setattr(consent.sys, "platform", "win32")

    def fail(request):
        raise consent.WinRtError("activation_factory", -2147221164)

    monkeypatch.setattr(consent, "run", fail)
    out = io.StringIO()
    code = consent.main(io.StringIO('{"message": "x"}'), out)
    assert code == 1
    assert json.loads(out.getvalue()) == {
        "status": "error",
        "reason": "activation_factory_hresult_0x80040154",
    }


# -- the verifier and preflight use it -------------------------------------------


def test_verifier_runs_the_builtin_helper_end_to_end(monkeypatch):
    if sys.platform == "win32":
        pytest.skip("would show a real Windows Hello prompt")
    # The verifier believes it is on Windows; the real child process (this
    # Linux runtime) answers "not_windows" through the same JSON contract.
    monkeypatch.setattr("jarvis.authority.verifier.sys.platform", "win32")
    result = WindowsHelloVerifier().verify(proposal=_proposal(), session_id="s1")
    assert result.status is StrongVerificationStatus.UNAVAILABLE
    assert result.reason_codes == ("not_windows",)
    assert result.verifier_id == "windows-hello-userconsentverifier-v1"


def test_verifier_default_command_and_message(monkeypatch):
    monkeypatch.setattr("jarvis.authority.verifier.sys.platform", "win32")
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"], seen["input"] = args, kwargs["input"]
        return subprocess.CompletedProcess(
            args, 0, '{"status":"verified","reason":"verified"}', ""
        )

    monkeypatch.setattr("jarvis.authority.verifier.subprocess.run", fake_run)
    result = WindowsHelloVerifier().verify(proposal=_proposal(), session_id="s1")
    assert result.verified
    assert seen["args"] == list(tooling.builtin_windows_hello_command())
    assert json.loads(seen["input"]) == {
        "message": "Authorize JARVIS action: forget what was said about the Thar"
    }


def test_preflight_uses_builtin_and_notes_the_legacy_setting(monkeypatch, tmp_path):
    opa = tmp_path / "opa.exe"
    opa.write_bytes(b"x")
    monkeypatch.setattr(tooling, "probe_opa_binary", lambda path: "Version: 1.21.4")
    checks = tooling.authority_tool_readiness(
        machine_settings={
            "JARVIS_OPA_PATH": str(opa),
            "JARVIS_WINDOWS_HELLO_HELPER": r"E:\old\Jarvis.WindowsHelloVerifier.exe",
        }
    )
    hello = {c.label: c for c in checks}["Windows Hello helper"]
    assert hello.ok, hello.detail
    assert "built-in Windows Hello consent ready" in hello.detail
    assert "JARVIS_WINDOWS_HELLO_HELPER is no longer used" in hello.detail
    assert hello.path == Path(sys.executable)


def test_installed_profile_with_the_old_helper_key_still_loads(tmp_path):
    from jarvis.machine_config import load_machine_settings, save_machine_settings

    path = tmp_path / "machine.json"
    old = {"JARVIS_WINDOWS_HELLO_HELPER": r"E:\x\Jarvis.WindowsHelloVerifier.exe"}
    save_machine_settings(old, path)
    assert load_machine_settings(path) == old


def test_setup_no_longer_needs_dotnet_or_writes_a_helper_path(monkeypatch, tmp_path):
    from jarvis.authority import tool_setup

    opa = tmp_path / "opa.exe"
    opa.write_bytes(b"x")
    monkeypatch.setattr(tool_setup, "discover_opa_for_setup", lambda existing: opa)
    monkeypatch.setattr(tool_setup, "probe_opa_binary", lambda path: "Version: 1")
    checked = []
    monkeypatch.setattr(
        tool_setup, "check_builtin_windows_hello", lambda: checked.append(True)
    )
    assert tool_setup.configure_authority_tool_settings({}) == {
        "JARVIS_OPA_PATH": str(opa)
    }
    assert checked == [True]


# -- OPA probe: cause and one retry ------------------------------------------------


def _opa(tmp_path) -> Path:
    path = tmp_path / "opa.exe"
    path.write_bytes(b"x")
    return path


def _ok(args, **kwargs):
    return subprocess.CompletedProcess(args, 0, "Version: 1.21.4\nBuild: x\n", "")


def test_opa_slow_first_start_is_retried_once(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return _ok(args)

    monkeypatch.setattr(tooling.subprocess, "run", run)
    monkeypatch.setattr(tooling.time, "sleep", lambda s: None)
    assert tooling.probe_opa_binary(_opa(tmp_path)) == "Version: 1.21.4"
    assert calls == [tooling.OPA_PROBE_TIMEOUT_SECONDS] * 2
    assert tooling.OPA_PROBE_TIMEOUT_SECONDS >= 30


def test_opa_policy_block_reports_its_cause(monkeypatch, tmp_path):
    def blocked(args, **kwargs):
        error = OSError(22, "blocked")
        error.winerror = 4551
        raise error

    monkeypatch.setattr(tooling.subprocess, "run", blocked)
    monkeypatch.setattr(tooling.time, "sleep", lambda s: None)
    with pytest.raises(tooling.AuthorityToolError) as error:
        tooling.probe_opa_binary(_opa(tmp_path))
    message = str(error.value)
    assert "code integrity policy" in message and "WinError 4551" in message
    assert message.count("WinError 4551") == 2  # tried twice, then failed closed


def test_opa_wrong_output_is_not_retried(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append(1)
        return subprocess.CompletedProcess(args, 1, "", "boom")

    monkeypatch.setattr(tooling.subprocess, "run", run)
    with pytest.raises(tooling.AuthorityToolError, match="exit code 1"):
        tooling.probe_opa_binary(_opa(tmp_path))
    assert calls == [1]


def test_opa_timeout_cause_is_reported(monkeypatch, tmp_path):
    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(tooling.subprocess, "run", run)
    monkeypatch.setattr(tooling.time, "sleep", lambda s: None)
    with pytest.raises(tooling.AuthorityToolError, match="no response within 30 s"):
        tooling.probe_opa_binary(_opa(tmp_path))


def test_slow_opa_start_is_visible_in_preflight(monkeypatch, tmp_path):
    clock = iter([0.0, 12.5])
    monkeypatch.setattr(tooling.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(tooling, "probe_opa_binary", lambda path: "Version: 1.21.4")
    monkeypatch.setattr(tooling, "probe_windows_hello_helper_contract", lambda: None)
    checks = tooling.authority_tool_readiness(
        machine_settings={"JARVIS_OPA_PATH": str(_opa(tmp_path))}
    )
    assert checks[0].detail == "Version: 1.21.4 (slow start: 12.5 s)"


def test_managed_opa_server_reports_a_policy_block(monkeypatch, tmp_path):
    from jarvis.authority import local_opa

    policy = tmp_path / "p.rego"
    policy.write_text("package x", encoding="utf-8")
    monkeypatch.setattr(local_opa, "_resolve_opa_binary", lambda: _opa(tmp_path))

    def blocked(*args, **kwargs):
        error = OSError(22, "blocked")
        error.winerror = 4551
        raise error

    monkeypatch.setattr(local_opa.subprocess, "Popen", blocked)
    server = local_opa.ManagedOpaServer(policy_path=policy)
    with pytest.raises(local_opa.LocalOpaError, match="code integrity policy"):
        server.start()
    assert local_opa.ManagedOpaServer()._startup_timeout_seconds >= 30
