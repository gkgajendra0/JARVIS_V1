"""Development supervisor for owner-approved JARVIS updates and restarts."""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.dev_control import (
    DEV_CONTROL_HOST_ENV,
    DEV_CONTROL_PORT_ENV,
    DEV_CONTROL_TOKEN_ENV,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.self_awareness import default_incident_store_path
from jarvis.self_repair import RepairVerdict
from jarvis.self_repair.supervisor import (
    SupervisorRepairController,
    build_runtime_child_exit_policy,
)

_BRANCH_ENV = "JARVIS_DEV_BRANCH"


@dataclass(frozen=True, slots=True)
class DevSupervisorConfig:
    remote: str = "origin"
    branch: str = "main"
    poll_seconds: float = 5.0
    shutdown_timeout_seconds: float = 10.0
    approval_timeout_seconds: float = 45.0
    startup_timeout_seconds: float = 45.0
    crash_restart_max_attempts: int = 3
    crash_restart_window_seconds: float = 300.0
    crash_restart_cooldown_seconds: float = 2.0
    crash_restart_backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if not self.remote.strip():
            raise ValueError("remote must not be empty")
        if not self.branch.strip():
            raise ValueError("branch must not be empty")
        if self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if self.shutdown_timeout_seconds <= 0:
            raise ValueError("shutdown_timeout_seconds must be positive")
        if self.approval_timeout_seconds <= 0:
            raise ValueError("approval_timeout_seconds must be positive")
        if self.startup_timeout_seconds <= 0:
            raise ValueError("startup_timeout_seconds must be positive")
        if (
            isinstance(self.crash_restart_max_attempts, bool)
            or not isinstance(self.crash_restart_max_attempts, int)
            or self.crash_restart_max_attempts <= 0
        ):
            raise ValueError("crash_restart_max_attempts must be a positive integer")
        if self.crash_restart_window_seconds <= 0:
            raise ValueError("crash_restart_window_seconds must be positive")
        if self.crash_restart_cooldown_seconds < 0:
            raise ValueError("crash_restart_cooldown_seconds must not be negative")
        if self.crash_restart_backoff_multiplier < 1:
            raise ValueError("crash_restart_backoff_multiplier must be at least 1")


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

    def reset_hard(self, sha: str) -> None:
        """Restore the clean repository to a previously known-good revision."""
        self._run("reset", "--hard", sha)


class VoiceControlServer:
    """Loopback-only supervisor endpoint used by the running voice child."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._host, self._port = self._listener.getsockname()
        self._token = secrets.token_urlsafe(32)
        self._connection: socket.socket | None = None
        self._stream: Any = None
        self._request_sequence = 0

    def child_environment(self) -> dict[str, str]:
        return {
            DEV_CONTROL_HOST_ENV: str(self._host),
            DEV_CONTROL_PORT_ENV: str(self._port),
            DEV_CONTROL_TOKEN_ENV: self._token,
        }

    def _next_request_id(self) -> str:
        self._request_sequence += 1
        return str(self._request_sequence)

    def _reset_child(self) -> None:
        stream = self._stream
        connection = self._connection
        self._stream = None
        self._connection = None
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _send(self, payload: dict[str, object]) -> None:
        if self._stream is None:
            raise RuntimeError("JARVIS voice control connection is unavailable")
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        self._stream.write(data)
        self._stream.flush()

    def _receive(self) -> dict[str, object]:
        if self._stream is None:
            raise RuntimeError("JARVIS voice control connection is unavailable")
        line = self._stream.readline()
        if not line:
            raise RuntimeError("JARVIS voice control connection closed")
        payload = json.loads(line.decode())
        if not isinstance(payload, dict):
            raise TypeError("invalid JARVIS voice control response")
        return payload

    def _ensure_child(self, *, timeout_seconds: float) -> None:
        if self._connection is not None:
            self._connection.settimeout(timeout_seconds)
            return
        self._listener.settimeout(timeout_seconds)
        connection, _ = self._listener.accept()
        connection.settimeout(timeout_seconds)
        stream = connection.makefile("rwb")
        self._connection = connection
        self._stream = stream
        try:
            hello = self._receive()
            if hello.get("type") != "hello" or hello.get("token") != self._token:
                raise RuntimeError("JARVIS voice control authentication failed")
        except Exception:
            self._reset_child()
            raise

    def wait_for_child_ready(self, *, timeout_seconds: float) -> None:
        """Require the child to establish its authenticated control connection."""
        try:
            self._ensure_child(timeout_seconds=timeout_seconds)
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            self._reset_child()
            raise RuntimeError(f"JARVIS startup readiness failed: {exc}") from exc

    def request_update_approval(
        self,
        local_sha: str,
        remote_sha: str,
        *,
        timeout_seconds: float,
    ) -> bool:
        try:
            self._ensure_child(timeout_seconds=timeout_seconds)
            request_id = self._next_request_id()
            self._send(
                {
                    "type": "update_approval_request",
                    "request_id": request_id,
                    "local_sha": local_sha,
                    "remote_sha": remote_sha,
                }
            )
            response = self._receive()
            if (
                response.get("type") != "update_approval_response"
                or response.get("request_id") != request_id
            ):
                raise RuntimeError("unexpected JARVIS update approval response")
            return response.get("approved") is True
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            self._reset_child()
            raise RuntimeError(f"voice approval failed: {exc}") from exc

    def request_shutdown(self, *, timeout_seconds: float = 3.0) -> bool:
        try:
            self._ensure_child(timeout_seconds=timeout_seconds)
            request_id = self._next_request_id()
            self._send({"type": "shutdown_request", "request_id": request_id})
            response = self._receive()
            return (
                response.get("type") == "shutdown_ack"
                and response.get("request_id") == request_id
            )
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            TypeError,
            json.JSONDecodeError,
        ):
            self._reset_child()
            return False

    def child_stopped(self) -> None:
        self._reset_child()

    def close(self) -> None:
        self._reset_child()
        self._listener.close()


def _config_from_environment() -> DevSupervisorConfig:
    branch = os.environ.get(_BRANCH_ENV, "main").strip() or "main"
    return DevSupervisorConfig(branch=branch)


def _find_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _start_jarvis(
    root: Path,
    control: VoiceControlServer,
) -> subprocess.Popen[bytes]:
    child_env = os.environ.copy()
    child_env.update(control.child_environment())
    kwargs: dict[str, object] = {"cwd": root, "env": child_env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "-m", "jarvis.voice.production_runtime"],
        **kwargs,
    )
    print(f"JARVIS started (pid={process.pid}).")
    return process


def _stop_jarvis(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    control: VoiceControlServer,
) -> None:
    if process.poll() is not None:
        control.child_stopped()
        return

    print("Stopping JARVIS gracefully...")
    if control.request_shutdown():
        try:
            process.wait(timeout=timeout_seconds)
            control.child_stopped()
            return
        except subprocess.TimeoutExpired:
            pass

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=timeout_seconds)
        control.child_stopped()
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
    finally:
        control.child_stopped()


def _build_supervisor_repair_controller(
    config: DevSupervisorConfig,
) -> tuple[SupervisorRepairController | None, SqliteIncidentStore | None]:
    """Build durable crash recovery; persistence failure disables auto-restart."""

    try:
        store = SqliteIncidentStore(default_incident_store_path())
    except (OSError, sqlite3.Error) as exc:
        print(
            "Self-Repair incident persistence is unavailable; "
            f"automatic runtime restart is disabled: {type(exc).__name__}"
        )
        return None, None

    policy = build_runtime_child_exit_policy(
        max_attempts=config.crash_restart_max_attempts,
        rolling_window_seconds=config.crash_restart_window_seconds,
        cooldown_seconds=config.crash_restart_cooldown_seconds,
        backoff_multiplier=config.crash_restart_backoff_multiplier,
    )
    return SupervisorRepairController(
        IncidentService(store),
        policy=policy,
    ), store


def _recover_unexpected_exit(
    repo: GitRepo,
    root: Path,
    process: subprocess.Popen[bytes],
    control: VoiceControlServer,
    config: DevSupervisorConfig,
    repair: SupervisorRepairController,
    *,
    sleep_fn: Any = time.sleep,
    now_fn: Any = time.time,
) -> subprocess.Popen[bytes] | None:
    """Perform the single supervisor-owned bounded same-version restart loop."""

    exit_code = process.returncode
    control.child_stopped()
    commit_sha = repo.local_sha()

    while True:
        plan = repair.plan_unexpected_exit(
            exit_code=exit_code,
            commit_sha=commit_sha,
            now_epoch=float(now_fn()),
        )
        if plan.exhausted:
            print(
                "JARVIS runtime restart budget exhausted for crash "
                f"{plan.fingerprint.fingerprint_id[:12]}; stopping automatic "
                "restart and escalating."
            )
            return None

        wait_seconds = plan.budget.wait_seconds
        attempt_number = plan.budget.attempt_number
        print(
            f"JARVIS exited unexpectedly with code {exit_code}; "
            f"bounded same-version restart attempt {attempt_number}/"
            f"{plan.policy.max_attempts} is eligible after {wait_seconds:g}s."
        )
        if wait_seconds > 0:
            sleep_fn(wait_seconds)

        if repo.local_sha() != commit_sha:
            print(
                "Local revision changed while crash recovery was waiting; "
                "automatic restart aborted rather than repairing a different revision."
            )
            return None

        attempt = repair.start_attempt(plan, now_epoch=float(now_fn()))
        try:
            restarted = _start_jarvis(root, control)
        except OSError:
            repair.complete_attempt(
                plan,
                attempt,
                execution_result="same-version child restart failed to start",
                verifier_result="process_start_failed",
                verdict=RepairVerdict.NOT_RECOVERED,
                post_repair_evidence=("supervisor:process_start_failed",),
                now_epoch=float(now_fn()),
            )
            continue

        try:
            control.wait_for_child_ready(
                timeout_seconds=config.startup_timeout_seconds
            )
        except RuntimeError:
            _stop_jarvis(
                restarted,
                timeout_seconds=config.shutdown_timeout_seconds,
                control=control,
            )
            repair.complete_attempt(
                plan,
                attempt,
                execution_result="same-version child restart attempted",
                verifier_result="startup_readiness_failed",
                verdict=RepairVerdict.NOT_RECOVERED,
                post_repair_evidence=("supervisor:startup_readiness_failed",),
                now_epoch=float(now_fn()),
            )
            continue

        repair.complete_attempt(
            plan,
            attempt,
            execution_result="same-version child restart started",
            verifier_result=(
                "startup readiness confirmed; liveness stabilization pending"
            ),
            verdict=RepairVerdict.INCONCLUSIVE,
            post_repair_evidence=("supervisor:startup_readiness_confirmed",),
            now_epoch=float(now_fn()),
        )
        print(
            "Same-version JARVIS restart reached startup readiness. "
            "Liveness stabilization remains a separate verification phase."
        )
        return restarted


def _apply_approved_update(
    repo: GitRepo,
    root: Path,
    process: subprocess.Popen[bytes],
    control: VoiceControlServer,
    config: DevSupervisorConfig,
    *,
    previous_sha: str,
    remote_sha: str,
) -> tuple[subprocess.Popen[bytes], bool]:
    """Apply an approved update and restore the previous revision if startup fails."""
    _stop_jarvis(
        process,
        timeout_seconds=config.shutdown_timeout_seconds,
        control=control,
    )
    try:
        repo.pull_fast_forward()
    except subprocess.CalledProcessError as exc:
        print(f"Update failed: {exc}")
        print("Restarting the existing local JARVIS version.")
        process = _start_jarvis(root, control)
        try:
            control.wait_for_child_ready(timeout_seconds=config.startup_timeout_seconds)
        except RuntimeError as ready_exc:
            _stop_jarvis(
                process,
                timeout_seconds=config.shutdown_timeout_seconds,
                control=control,
            )
            raise RuntimeError(
                "existing JARVIS version failed to restart after update failure"
            ) from ready_exc
        return process, False

    updated_sha = repo.local_sha()
    print(f"Updated JARVIS to {updated_sha[:10]}.")
    process = _start_jarvis(root, control)
    try:
        control.wait_for_child_ready(timeout_seconds=config.startup_timeout_seconds)
    except RuntimeError:
        print(
            f"Updated JARVIS {remote_sha[:10]} failed startup readiness; "
            "restoring the last-known-good revision."
        )
        _stop_jarvis(
            process,
            timeout_seconds=config.shutdown_timeout_seconds,
            control=control,
        )
        try:
            repo.reset_hard(previous_sha)
        except subprocess.CalledProcessError as rollback_exc:
            raise RuntimeError(
                f"failed to restore last-known-good JARVIS {previous_sha[:10]}"
            ) from rollback_exc

        print(f"Rolled back JARVIS to {previous_sha[:10]}.")
        process = _start_jarvis(root, control)
        try:
            control.wait_for_child_ready(timeout_seconds=config.startup_timeout_seconds)
        except RuntimeError as rollback_ready_exc:
            _stop_jarvis(
                process,
                timeout_seconds=config.shutdown_timeout_seconds,
                control=control,
            )
            raise RuntimeError(
                "last-known-good JARVIS failed to restart after rollback"
            ) from rollback_ready_exc
        print("Last-known-good JARVIS startup readiness confirmed.")
        return process, False

    print("JARVIS update startup readiness confirmed.")
    return process, True


def run_supervisor(config: DevSupervisorConfig | None = None) -> int:
    config = config or _config_from_environment()
    root = _find_repo_root()
    repo = GitRepo(root, config)

    if repo.current_branch() != config.branch:
        raise RuntimeError(
            f"jarvis-dev must run on {config.branch!r}; "
            f"current branch is {repo.current_branch()!r}. "
            f"For an intentional development-branch test, set {_BRANCH_ENV}."
        )
    if not repo.is_clean():
        raise RuntimeError(
            "jarvis-dev will not run with uncommitted local changes; "
            "commit or stash them first"
        )

    print("JARVIS development supervisor")
    print(f"Watching {config.remote}/{config.branch} every {config.poll_seconds:g}s.")
    print("Updates require one explicit spoken owner Yes/No decision.")
    print("Ambiguous speech, timeout, or unavailable voice approval means No.")

    control = VoiceControlServer()
    repair, repair_store = _build_supervisor_repair_controller(config)
    process = _start_jarvis(root, control)
    declined_sha: str | None = None

    try:
        while True:
            if process.poll() is not None:
                if repair is None:
                    print(
                        f"JARVIS exited unexpectedly with code {process.returncode}; "
                        "durable Self-Repair is unavailable, so automatic restart "
                        "fails closed."
                    )
                    return int(process.returncode or 1)
                restarted = _recover_unexpected_exit(
                    repo,
                    root,
                    process,
                    control,
                    config,
                    repair,
                )
                if restarted is None:
                    return int(process.returncode or 1)
                process = restarted
                continue

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

            print()
            print("New JARVIS update detected; requesting spoken owner approval.")
            try:
                approved = control.request_update_approval(
                    local_sha,
                    remote_sha,
                    timeout_seconds=config.approval_timeout_seconds,
                )
            except RuntimeError as exc:
                print(
                    f"{exc}. Current JARVIS keeps running; "
                    "the update will be offered again."
                )
                declined_sha = None
                continue

            if not approved:
                print("Update declined. Current JARVIS keeps running.")
                declined_sha = remote_sha
                continue

            print("Spoken update approval accepted.")
            process, update_healthy = _apply_approved_update(
                repo,
                root,
                process,
                control,
                config,
                previous_sha=local_sha,
                remote_sha=remote_sha,
            )
            if not update_healthy:
                declined_sha = remote_sha
                continue
            declined_sha = None
    except KeyboardInterrupt:
        print("\nStopping JARVIS development supervisor...")
        return 0
    finally:
        _stop_jarvis(
            process,
            timeout_seconds=config.shutdown_timeout_seconds,
            control=control,
        )
        control.close()
        if repair_store is not None:
            repair_store.close()


def main() -> int:
    try:
        return run_supervisor()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"jarvis-dev error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
