"""Explicit Windows Task Scheduler guardian setup for jarvis-supervisor.

This is owner-invoked installation tooling. Importing this module never creates,
changes or starts a scheduled task.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "JARVIS Runtime Supervisor"
DEFAULT_RESTART_COUNT = 3
DEFAULT_RESTART_INTERVAL = "PT1M"

Runner = Callable[..., subprocess.CompletedProcess[str]]


class WindowsGuardianError(RuntimeError):
    """The bounded Windows outer guardian could not be configured."""


@dataclass(frozen=True, slots=True)
class GuardianTaskSpec:
    task_name: str
    principal: str
    python_executable: Path
    repo_root: Path
    restart_count: int = DEFAULT_RESTART_COUNT
    restart_interval: str = DEFAULT_RESTART_INTERVAL

    def __post_init__(self) -> None:
        if not self.task_name.strip():
            raise ValueError("task_name must not be empty")
        if not self.principal.strip():
            raise ValueError("principal must not be empty")
        if not 1 <= self.restart_count <= 255:
            raise ValueError("restart_count must be between 1 and 255")
        if self.restart_interval != "PT1M":
            raise ValueError(
                "Phase 1H guardian uses the Task Scheduler minimum PT1M interval"
            )


def render_guardian_task_xml(spec: GuardianTaskSpec) -> str:
    principal = escape(spec.principal)
    command = escape(str(spec.python_executable))
    working_directory = escape(str(spec.repo_root))
    description = escape(
        "Starts the local-only JARVIS runtime supervisor at owner logon and "
        "restarts only supervisor process failures under a bounded outer budget."
    )
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{principal}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{principal}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>{spec.restart_interval}</Interval>
      <Count>{spec.restart_count}</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>-m jarvis.runtime_supervisor</Arguments>
      <WorkingDirectory>{working_directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsGuardianError("Task Scheduler guardian setup requires Windows")


def _run_checked(
    args: Sequence[str],
    *,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            list(args),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WindowsGuardianError(
            f"Windows guardian command failed: {' '.join(args)}"
        ) from exc


def current_windows_principal(*, runner: Runner = subprocess.run) -> str:
    _require_windows()
    result = _run_checked(("whoami",), runner=runner)
    principal = result.stdout.strip()
    if not principal:
        raise WindowsGuardianError("whoami returned an empty Windows principal")
    return principal


def current_repo_root(*, runner: Runner = subprocess.run) -> Path:
    result = _run_checked(
        ("git", "rev-parse", "--show-toplevel"),
        runner=runner,
    )
    root_text = result.stdout.strip()
    if not root_text:
        raise WindowsGuardianError("Git returned an empty repository root")
    return Path(root_text)


def build_current_guardian_spec(
    *,
    runner: Runner = subprocess.run,
) -> GuardianTaskSpec:
    return GuardianTaskSpec(
        task_name=TASK_NAME,
        principal=current_windows_principal(runner=runner),
        python_executable=Path(sys.executable),
        repo_root=current_repo_root(runner=runner),
    )


def install_guardian_task(
    spec: GuardianTaskSpec,
    *,
    runner: Runner = subprocess.run,
) -> None:
    _require_windows()
    xml = render_guardian_task_xml(spec)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="jarvis-supervisor-",
            suffix=".xml",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        temporary_path.write_text(xml, encoding="utf-16")
        _run_checked(
            (
                "schtasks",
                "/Create",
                "/TN",
                spec.task_name,
                "/XML",
                str(temporary_path),
                "/F",
            ),
            runner=runner,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def remove_guardian_task(*, runner: Runner = subprocess.run) -> None:
    _require_windows()
    _run_checked(
        ("schtasks", "/Delete", "/TN", TASK_NAME, "/F"),
        runner=runner,
    )


def start_guardian_task(*, runner: Runner = subprocess.run) -> None:
    _require_windows()
    _run_checked(
        ("schtasks", "/Run", "/TN", TASK_NAME),
        runner=runner,
    )


def query_guardian_task(*, runner: Runner = subprocess.run) -> str:
    _require_windows()
    result = _run_checked(
        ("schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"),
        runner=runner,
    )
    return result.stdout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the bounded Windows guardian for jarvis-supervisor."
    )
    parser.add_argument(
        "operation",
        choices=("install", "remove", "start", "query"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "install":
            spec = build_current_guardian_spec()
            install_guardian_task(spec)
            print(
                f"Installed {spec.task_name!r} for {spec.principal}; "
                f"restart_count={spec.restart_count} "
                f"restart_interval={spec.restart_interval}."
            )
        elif args.operation == "remove":
            remove_guardian_task()
            print(f"Removed {TASK_NAME!r}.")
        elif args.operation == "start":
            start_guardian_task()
            print(f"Started {TASK_NAME!r}.")
        else:
            print(query_guardian_task())
    except (ValueError, WindowsGuardianError) as exc:
        print(f"jarvis-supervisor-task error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
