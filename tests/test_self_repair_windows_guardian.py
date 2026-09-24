from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.self_repair import windows_guardian
from jarvis.self_repair.windows_guardian import (
    GuardianTaskSpec,
    WindowsGuardianError,
    render_guardian_task_xml,
    run_bounded_supervisor_guardian,
)


def _spec() -> GuardianTaskSpec:
    return GuardianTaskSpec(
        task_name="JARVIS Runtime Supervisor",
        principal=r"WORKSTATION\gajendra",
        python_executable=Path(r"C:\jarvis\.venv\Scripts\python.exe"),
        repo_root=Path(r"C:\jarvis"),
        branch="fix/self-repair-phase1h-foundation-hardening",
        restart_count=3,
        restart_interval="PT1M",
    )


def test_guardian_xml_is_interactive_bounded_and_local_only() -> None:
    xml = render_guardian_task_xml(_spec())

    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<RestartOnFailure>" not in xml
    assert (
        "-m jarvis.self_repair.windows_guardian run "
        "--branch fix/self-repair-phase1h-foundation-hardening"
    ) in xml
    assert "<WorkingDirectory>C:\\jarvis</WorkingDirectory>" in xml
    assert "jarvis-dev" not in xml


def test_guardian_spec_rejects_unbounded_or_subminute_restart_configuration() -> None:
    with pytest.raises(ValueError, match="between 1 and 255"):
        GuardianTaskSpec(
            task_name="x",
            principal="user",
            python_executable=Path("python.exe"),
            repo_root=Path("."),
            branch="main",
            restart_count=0,
        )

    with pytest.raises(ValueError, match="minimum PT1M"):
        GuardianTaskSpec(
            task_name="x",
            principal="user",
            python_executable=Path("python.exe"),
            repo_root=Path("."),
            branch="main",
            restart_interval="PT10S",
        )


def test_bounded_guardian_stops_on_clean_supervisor_exit() -> None:
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        calls.append([str(item) for item in args])
        return subprocess.CompletedProcess(args, 0)

    result = run_bounded_supervisor_guardian(
        branch="main",
        python_executable=Path(r"C:\jarvis\.venv\Scripts\python.exe"),
        repo_root=Path(r"C:\jarvis"),
        runner=fake_run,
        sleeper=sleeps.append,
    )

    assert result == 0
    assert len(calls) == 1
    assert sleeps == []


def test_bounded_guardian_restarts_unexpected_supervisor_exit_then_recovers() -> None:
    return_codes = iter((17, 0))
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        calls.append([str(item) for item in args])
        return subprocess.CompletedProcess(args, next(return_codes))

    result = run_bounded_supervisor_guardian(
        branch="main",
        python_executable=Path(r"C:\jarvis\.venv\Scripts\python.exe"),
        repo_root=Path(r"C:\jarvis"),
        restart_count=3,
        restart_delay_seconds=60.0,
        runner=fake_run,
        sleeper=sleeps.append,
    )

    assert result == 0
    assert len(calls) == 2
    assert sleeps == [60.0]
    assert calls[0][-3:] == ["jarvis.runtime_supervisor", "--branch", "main"]


def test_bounded_guardian_exhausts_without_unbounded_restart() -> None:
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        calls.append([str(item) for item in args])
        return subprocess.CompletedProcess(args, 23)

    result = run_bounded_supervisor_guardian(
        branch="main",
        python_executable=Path(r"C:\jarvis\.venv\Scripts\python.exe"),
        repo_root=Path(r"C:\jarvis"),
        restart_count=3,
        restart_delay_seconds=60.0,
        runner=fake_run,
        sleeper=sleeps.append,
    )

    assert result == 23
    assert len(calls) == 4
    assert sleeps == [60.0, 60.0, 60.0]


def test_install_guardian_uses_schtasks_xml_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    xml_paths: list[Path] = []

    def fake_run(args, **kwargs):
        call = [str(item) for item in args]
        calls.append(call)
        if call[0] == "schtasks" and "/XML" in call:
            path = Path(call[call.index("/XML") + 1])
            xml_paths.append(path)
            assert path.exists()
            xml = path.read_text(encoding="utf-16")
            assert "jarvis.self_repair.windows_guardian run" in xml
            assert "RestartOnFailure" not in xml
        return subprocess.CompletedProcess(call, 0, stdout="", stderr="")

    monkeypatch.setattr(windows_guardian, "os", SimpleNamespace(name="nt"))
    windows_guardian.install_guardian_task(_spec(), runner=fake_run)

    assert calls[0][:4] == [
        "schtasks",
        "/Create",
        "/TN",
        "JARVIS Runtime Supervisor",
    ]
    assert xml_paths and not xml_paths[0].exists()


def test_guardian_setup_fails_closed_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows_guardian, "os", SimpleNamespace(name="posix"))

    with pytest.raises(WindowsGuardianError, match="requires Windows"):
        windows_guardian.install_guardian_task(_spec())
