"""Explicit Windows Task Scheduler guardian setup for jarvis-supervisor.

Task Scheduler provides the current-user interactive launch boundary. A tiny
bounded guardian wrapper owns jarvis.runtime_supervisor and restarts only
unexpected non-zero supervisor exits. This avoids relying on Task Scheduler's
RestartOnFailure interpretation of child/action exit codes while preserving a
strict outer restart budget.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "JARVIS Runtime Supervisor"
DEFAULT_RESTART_COUNT = 3
DEFAULT_RESTART_INTERVAL = "PT1M"
DEFAULT_RESTART_DELAY_SECONDS = 60.0

Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]


class WindowsGuardianError(RuntimeError):
    """The bounded Windows outer guardian could not be configured."""


@dataclass(frozen=True, slots=True)
class GuardianTaskSpec:
    task_name: str
    principal: str
    python_executable: Path
    repo_root: Path
    branch: str
    restart_count: int = DEFAULT_RESTART_COUNT
    restart_interval: str = DEFAULT_RESTART_INTERVAL

    def __post_init__(self) -> None:
        if not self.task_name.strip():
            raise ValueError("task_name must not be empty")
        if not self.principal.strip():
            raise ValueError("principal must not be empty")
        if not self.branch.strip():
            raise ValueError("branch must not be empty")
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
    branch = escape(spec.branch)
    description = escape(
        "Starts a bounded current-user JARVIS guardian at owner logon; the "
        "guardian owns and restarts only unexpected supervisor failures."
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
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>-m jarvis.self_repair.windows_guardian run --branch {branch}</Arguments>
      <WorkingDirectory>{working_directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def run_bounded_supervisor_guardian(
    *,
    branch: str,
    python_executable: Path | None = None,
    repo_root: Path | None = None,
    restart_count: int = DEFAULT_RESTART_COUNT,
    restart_delay_seconds: float = DEFAULT_RESTART_DELAY_SECONDS,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
) -> int:
    """Own the production supervisor and restart only unexpected failures.

    A clean supervisor exit (0) is authoritative and stops the guardian. This
    preserves production fail-closed semantics after the supervisor's own repair
    budget is exhausted. Non-zero exits receive a bounded outer restart budget.
    """

    normalized_branch = branch.strip()
    if not normalized_branch:
        raise ValueError("branch must not be empty")
    if not 1 <= restart_count <= 255:
        raise ValueError("restart_count must be between 1 and 255")
    if restart_delay_seconds < 0:
        raise ValueError("restart_delay_seconds must not be negative")

    python = Path(sys.executable) if python_executable is None else python_executable
    working_directory = Path.cwd() if repo_root is None else repo_root
    command = (
        str(python),
        "-m",
        "jarvis.runtime_supervisor",
        "--branch",
        normalized_branch,
    )

    failures = 0
    while True:
        try:
            result = runner(
                list(command),
                cwd=str(working_directory),
                check=False,
            )
            return_code = int(result.returncode)
        except OSError as exc:
            failures += 1
            return_code = 1
            print(
                f"JARVIS outer guardian could not launch the runtime supervisor: {exc}",
                file=sys.stderr,
            )
        else:
            if return_code == 0:
                print(
                    "JARVIS runtime supervisor exited cleanly; "
                    "outer guardian is stopping."
                )
                return 0
            failures += 1

        if failures > restart_count:
            print(
                "JARVIS outer guardian restart budget exhausted; "
                f"last supervisor exit code={return_code}.",
                file=sys.stderr,
            )
            return return_code if return_code != 0 else 1

        print(
            "JARVIS runtime supervisor exited unexpectedly with code "
            f"{return_code}; outer guardian restart "
            f"{failures}/{restart_count} in {restart_delay_seconds:g}s."
        )
        sleeper(restart_delay_seconds)


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


def current_repo_branch(*, runner: Runner = subprocess.run) -> str:
    result = _run_checked(
        ("git", "branch", "--show-current"),
        runner=runner,
    )
    branch = result.stdout.strip()
    if not branch:
        raise WindowsGuardianError("Git returned an empty current branch")
    return branch


def build_current_guardian_spec(
    *,
    runner: Runner = subprocess.run,
) -> GuardianTaskSpec:
    return GuardianTaskSpec(
        task_name=TASK_NAME,
        principal=current_windows_principal(runner=runner),
        python_executable=Path(sys.executable),
        repo_root=current_repo_root(runner=runner),
        branch=current_repo_branch(runner=runner),
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
        choices=("install", "remove", "start", "query", "run"),
    )
    parser.add_argument(
        "--branch",
        default="",
        help="Pinned local branch used by the internal guardian run operation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "run":
            branch = str(args.branch).strip() or current_repo_branch()
            return run_bounded_supervisor_guardian(branch=branch)
        if args.operation == "install":
            spec = build_current_guardian_spec()
            install_guardian_task(spec)
            print(
                f"Installed {spec.task_name!r} for {spec.principal}; "
                f"outer_restart_count={spec.restart_count} "
                f"outer_restart_interval={spec.restart_interval}."
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
