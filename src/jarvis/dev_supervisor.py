"""Development supervisor for owner-approved JARVIS updates and restarts."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DevSupervisorConfig:
    remote: str = "origin"
    branch: str = "main"
    poll_seconds: float = 5.0
    shutdown_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if self.shutdown_timeout_seconds <= 0:
            raise ValueError("shutdown_timeout_seconds must be positive")


class GitRepo:
    """Small, explicit Git boundary used by the development supervisor."""

    def __init__(self, root: Path, config: DevSupervisorConfig) -> None:
        self.root = root
        self.config = config

    def _run(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=check,
            capture_output=True,
            text=True,
        )

    def current_branch(self) -> str:
        return self._run("branch", "--show-current").stdout.strip()

    def is_clean(self) -> bool:
        return not self._run("status", "--porcelain").stdout.strip()

    def local_sha(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def remote_sha(self) -> str:
        ref = f"{self.config.remote}/{self.config.branch}"
        return self._run("rev-parse", ref).stdout.strip()

    def fetch(self) -> None:
        self._run(
            "fetch",
            "--quiet",
            self.config.remote,
            self.config.branch,
        )

    def remote_is_fast_forward(self) -> bool:
        result = self._run(
            "merge-base",
            "--is-ancestor",
            self.local_sha(),
            self.remote_sha(),
            check=False,
        )
        return result.returncode == 0

    def pull_fast_forward(self) -> None:
        self._run(
            "pull",
            "--ff-only",
            self.config.remote,
            self.config.branch,
        )


def _find_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _start_jarvis(root: Path) -> subprocess.Popen[bytes]:
    kwargs: dict[str, object] = {"cwd": root}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "-m", "jarvis.voice.runtime"],
        **kwargs,
    )
    print(f"JARVIS started (pid={process.pid}).")
    return process


def _stop_jarvis(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
) -> None:
    if process.poll() is not None:
        return

    print("Stopping JARVIS gracefully...")
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=timeout_seconds)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    print("Graceful shutdown timed out; terminating child process.")
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


def _owner_approves_update(local_sha: str, remote_sha: str) -> bool:
    print()
    print("New validated JARVIS update detected:")
    print(f"  current: {local_sha[:10]}")
    print(f"  remote : {remote_sha[:10]}")
    answer = input("Apply update and restart JARVIS now? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def run_supervisor(config: DevSupervisorConfig | None = None) -> int:
    config = config or DevSupervisorConfig()
    root = _find_repo_root()
    repo = GitRepo(root, config)

    if repo.current_branch() != config.branch:
        raise RuntimeError(
            f"jarvis-dev must run on {config.branch!r}; "
            f"current branch is {repo.current_branch()!r}"
        )
    if not repo.is_clean():
        raise RuntimeError(
            "jarvis-dev will not run with uncommitted local changes; "
            "commit or stash them first"
        )

    print("JARVIS development supervisor")
    print(f"Watching {config.remote}/{config.branch} every {config.poll_seconds:g}s.")
    print("Updates require one explicit owner Yes/No decision.")
    print("Anything except y/yes is treated as No.")

    process = _start_jarvis(root)
    declined_sha: str | None = None

    try:
        while True:
            if process.poll() is not None:
                print(
                    f"JARVIS exited unexpectedly with code {process.returncode}; "
                    "automatic crash-loop restart is disabled."
                )
                return int(process.returncode or 1)

            time.sleep(config.poll_seconds)
            try:
                repo.fetch()
            except subprocess.CalledProcessError as exc:
                print(f"Git fetch failed; keeping current JARVIS running: {exc}")
                continue

            local_sha = repo.local_sha()
            remote_sha = repo.remote_sha()
            if local_sha == remote_sha:
                declined_sha = None
                continue
            if remote_sha == declined_sha:
                continue

            if not repo.is_clean():
                print(
                    "Remote update detected, but local working tree is dirty. "
                    "JARVIS will keep running without pulling."
                )
                declined_sha = remote_sha
                continue
            if not repo.remote_is_fast_forward():
                print(
                    "Remote update is not a fast-forward from the local commit. "
                    "JARVIS will keep running without changing the repository."
                )
                declined_sha = remote_sha
                continue

            if not _owner_approves_update(local_sha, remote_sha):
                print("Update declined. Current JARVIS keeps running.")
                declined_sha = remote_sha
                continue

            _stop_jarvis(
                process,
                timeout_seconds=config.shutdown_timeout_seconds,
            )
            try:
                repo.pull_fast_forward()
            except subprocess.CalledProcessError as exc:
                print(f"Update failed: {exc}")
                print("Restarting the existing local JARVIS version.")
                process = _start_jarvis(root)
                declined_sha = remote_sha
                continue

            print(f"Updated JARVIS to {repo.local_sha()[:10]}.")
            process = _start_jarvis(root)
            declined_sha = None
    except KeyboardInterrupt:
        print("\nStopping JARVIS development supervisor...")
        return 0
    finally:
        _stop_jarvis(
            process,
            timeout_seconds=config.shutdown_timeout_seconds,
        )


def main() -> int:
    try:
        return run_supervisor()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"jarvis-dev error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
