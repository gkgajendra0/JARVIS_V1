from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jarvis.authority import tool_setup, tooling
from jarvis.machine_config import load_machine_settings, save_machine_settings


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test")
    return path


def test_machine_profile_opa_path_wins_over_ambient_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    persisted = _touch(tmp_path / "persisted" / "opa.exe")
    ambient = _touch(tmp_path / "ambient" / "opa.exe")
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv("JARVIS_OPA_PATH", str(ambient))

    resolved = tooling.resolve_opa_binary(
        machine_settings={"JARVIS_OPA_PATH": str(persisted)}
    )

    assert resolved == persisted


def test_diagnostic_override_can_replace_persisted_opa_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    persisted = _touch(tmp_path / "persisted" / "opa.exe")
    diagnostic = _touch(tmp_path / "diagnostic" / "opa.exe")
    monkeypatch.setenv("JARVIS_RUNTIME_ENV_OVERRIDES", "true")
    monkeypatch.setenv("JARVIS_OPA_PATH", str(diagnostic))

    resolved = tooling.resolve_opa_binary(
        machine_settings={"JARVIS_OPA_PATH": str(persisted)}
    )

    assert resolved == diagnostic


def test_invalid_persisted_opa_path_fails_closed_without_path_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fallback = _touch(tmp_path / "fallback" / "opa.exe")
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.delenv("JARVIS_OPA_PATH", raising=False)
    monkeypatch.setattr(tooling.shutil, "which", lambda _name: str(fallback))

    with pytest.raises(tooling.AuthorityToolError, match="configured JARVIS_OPA_PATH"):
        tooling.resolve_opa_binary(
            machine_settings={"JARVIS_OPA_PATH": str(tmp_path / "missing.exe")}
        )


def test_windows_hello_falls_back_to_managed_helper_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = _touch(tmp_path / "managed" / "Jarvis.WindowsHelloVerifier.exe")
    monkeypatch.delenv("JARVIS_WINDOWS_HELLO_HELPER", raising=False)
    monkeypatch.setattr(tooling, "managed_windows_hello_helper_path", lambda: helper)

    assert tooling.resolve_windows_hello_helper(machine_settings={}) == helper


def test_opa_probe_requires_real_version_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opa = _touch(tmp_path / "opa.exe")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[str(opa), "version"],
            returncode=0,
            stdout="Version: 1.20.2\nBuild Commit: test\n",
            stderr="",
        )

    monkeypatch.setattr(tooling.subprocess, "run", fake_run)

    assert tooling.probe_opa_binary(opa) == "Version: 1.20.2"


def test_windows_hello_contract_probe_never_requests_biometrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = _touch(tmp_path / "Jarvis.WindowsHelloVerifier.exe")
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=2,
            stdout='{"status":"error","reason":"invalid_request"}',
            stderr="",
        )

    monkeypatch.setattr(tooling.subprocess, "run", fake_run)

    tooling.probe_windows_hello_helper_contract(helper)

    assert captured["args"] == [str(helper)]
    assert captured["input"] == "{}"


def test_authority_paths_are_valid_non_secret_machine_settings(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    opa = tmp_path / "opa.exe"
    hello = tmp_path / "hello.exe"

    save_machine_settings(
        {
            tooling.OPA_PATH_SETTING: str(opa),
            tooling.WINDOWS_HELLO_HELPER_SETTING: str(hello),
        },
        path,
    )

    assert load_machine_settings(path) == {
        tooling.OPA_PATH_SETTING: str(opa),
        tooling.WINDOWS_HELLO_HELPER_SETTING: str(hello),
    }


def test_hello_publish_command_is_self_contained_single_file(tmp_path: Path) -> None:
    command = tool_setup._publish_command(
        dotnet="dotnet",
        project=tmp_path / "helper.csproj",
        output=tmp_path / "publish",
        runtime_identifier="win-x64",
    )

    assert command[:2] == ["dotnet", "publish"]
    assert "--self-contained" in command
    assert "true" in command
    assert "-p:PublishSingleFile=true" in command
    assert "-p:IncludeNativeLibrariesForSelfExtract=true" in command
    assert "-p:PublishTrimmed=false" in command
    assert ["--runtime", "win-x64"] == command[
        command.index("--runtime") : command.index("--runtime") + 2
    ]


def test_windows_runtime_identifier_supports_current_desktop_architectures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tool_setup.platform, "machine", lambda: "AMD64")
    assert tool_setup._windows_runtime_identifier() == "win-x64"

    monkeypatch.setattr(tool_setup.platform, "machine", lambda: "ARM64")
    assert tool_setup._windows_runtime_identifier() == "win-arm64"
