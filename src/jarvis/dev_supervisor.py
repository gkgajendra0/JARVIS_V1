"""Development supervisor for owner-approved JARVIS updates and restarts."""

from __future__ import annotations

import json
import os
import queue
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from jarvis.dev_control import (
    DEV_CONTROL_HOST_ENV,
    DEV_CONTROL_PORT_ENV,
    DEV_CONTROL_TOKEN_ENV,
    RuntimeReleaseIdentity,
)
from jarvis.engineering_change.store import ChangeStore
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.promotion.deployment import DeploymentCoordinator, DeploymentError
from jarvis.promotion.models import PromotionAttemptState, PromotionEvidenceV1
from jarvis.promotion.release import (
    DeploymentMetadataStore,
    GitReleaseStager,
    RecoveryPhase,
    default_deployment_root,
    default_releases_root,
    load_active_release_for_startup,
)
from jarvis.promotion.store import PromotionStore
from jarvis.self_awareness import default_incident_store_path
from jarvis.self_repair import RepairVerificationStatus
from jarvis.self_repair.supervisor import (
    SupervisorRepairController,
    build_runtime_child_exit_policy,
    build_runtime_liveness_policy,
)
from jarvis.self_repair.windows_job import (
    WindowsJobObjectError,
    WindowsRuntimeJob,
)
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path

_BRANCH_ENV = "JARVIS_DEV_BRANCH"


@dataclass(frozen=True, slots=True)
class DevSupervisorConfig:
    remote: str = "origin"
    branch: str = "main"
    poll_seconds: float = 5.0
    shutdown_timeout_seconds: float = 10.0
    approval_timeout_seconds: float = 45.0
    startup_timeout_seconds: float = 120.0
    crash_restart_max_attempts: int = 3
    crash_restart_window_seconds: float = 300.0
    crash_restart_cooldown_seconds: float = 2.0
    crash_restart_backoff_multiplier: float = 2.0
    liveness_timeout_seconds: float = 3.0
    stabilization_seconds: float = 10.0
    liveness_interval_seconds: float = 2.0
    liveness_failure_threshold: int = 3
    git_fetch_timeout_seconds: float = 10.0
    git_updates_enabled: bool = True

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
        if self.liveness_timeout_seconds <= 0:
            raise ValueError("liveness_timeout_seconds must be positive")
        if self.stabilization_seconds <= 0:
            raise ValueError("stabilization_seconds must be positive")
        if self.liveness_interval_seconds <= 0:
            raise ValueError("liveness_interval_seconds must be positive")
        if (
            isinstance(self.liveness_failure_threshold, bool)
            or not isinstance(self.liveness_failure_threshold, int)
            or self.liveness_failure_threshold <= 0
        ):
            raise ValueError("liveness_failure_threshold must be a positive integer")
        if self.git_fetch_timeout_seconds <= 0:
            raise ValueError("git_fetch_timeout_seconds must be positive")


class GitRepo:
    """Small, explicit Git boundary used by the development supervisor."""

    def __init__(self, root: Path, config: DevSupervisorConfig) -> None:
        self.root = root
        self.config = config

    def _run(
        self,
        *args: str,
        check: bool = True,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
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
            timeout_seconds=self.config.git_fetch_timeout_seconds,
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


@dataclass(frozen=True, slots=True)
class RemotePollSnapshot:
    sequence: int
    local_sha: str | None
    remote_sha: str | None
    error: str | None = None


class RemoteUpdatePoller:
    """Run network-backed Git polling away from the watchdog control loop."""

    def __init__(self, root: Path, config: DevSupervisorConfig) -> None:
        self._repo = GitRepo(root, config)
        self._config = config
        self._stop = threading.Event()
        self._results: queue.SimpleQueue[RemotePollSnapshot] = queue.SimpleQueue()
        self._thread = threading.Thread(
            target=self._run,
            name="jarvis-update-poller",
            daemon=True,
        )

    @property
    def thread(self) -> threading.Thread:
        return self._thread

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> RemotePollSnapshot | None:
        latest: RemotePollSnapshot | None = None
        while True:
            try:
                latest = self._results.get_nowait()
            except queue.Empty:
                return latest

    def _run(self) -> None:
        sequence = 0
        while not self._stop.is_set():
            sequence += 1
            try:
                self._repo.fetch()
                snapshot = RemotePollSnapshot(
                    sequence=sequence,
                    local_sha=self._repo.local_sha(),
                    remote_sha=self._repo.remote_sha(),
                )
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as exc:
                snapshot = RemotePollSnapshot(
                    sequence=sequence,
                    local_sha=None,
                    remote_sha=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            self._results.put(snapshot)
            self._stop.wait(self._config.poll_seconds)


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
        self._child_release_identity: RuntimeReleaseIdentity | None = None
        self._receive_buffer = bytearray()
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
        connection = self._connection
        self._connection = None
        self._child_release_identity = None
        self._receive_buffer.clear()
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _send(self, payload: dict[str, object]) -> None:
        connection = self._connection
        if connection is None:
            raise RuntimeError("JARVIS voice control connection is unavailable")
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        connection.sendall(data)

    def _receive(self) -> dict[str, object]:
        connection = self._connection
        if connection is None:
            raise RuntimeError("JARVIS voice control connection is unavailable")

        while b"\n" not in self._receive_buffer:
            chunk = connection.recv(4096)
            if not chunk:
                raise RuntimeError("JARVIS voice control connection closed")
            self._receive_buffer.extend(chunk)
            if len(self._receive_buffer) > 65536:
                raise RuntimeError("JARVIS voice control frame exceeded 64 KiB")

        line, _, remainder = self._receive_buffer.partition(b"\n")
        self._receive_buffer[:] = remainder
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
        self._connection = connection
        self._receive_buffer.clear()
        try:
            hello = self._receive()
            if hello.get("type") != "hello" or hello.get("token") != self._token:
                raise RuntimeError("JARVIS voice control authentication failed")
            raw_identity = hello.get("release_identity")
            if raw_identity is not None:
                if not isinstance(raw_identity, dict):
                    raise RuntimeError("JARVIS release identity is malformed")
                try:
                    self._child_release_identity = RuntimeReleaseIdentity(
                        release_sha=str(raw_identity.get("release_sha", "")),
                        release_root=str(raw_identity.get("release_root", "")),
                        promotion_attempt_id=str(
                            raw_identity.get("promotion_attempt_id", "")
                        ),
                        config_digest=str(raw_identity.get("config_digest", "")),
                    )
                except ValueError as exc:
                    raise RuntimeError(
                        f"JARVIS release identity is invalid: {exc}"
                    ) from exc
        except Exception:
            self._reset_child()
            raise

    def wait_for_child_ready(
        self,
        *,
        timeout_seconds: float,
        expected_release: RuntimeReleaseIdentity | None = None,
    ) -> None:
        """Require authenticated readiness and, when supplied, exact release identity."""
        deadline = time.monotonic() + timeout_seconds
        try:
            self._ensure_child(timeout_seconds=timeout_seconds)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("runtime readiness timed out")

                connection = self._connection
                if connection is None:
                    raise RuntimeError("JARVIS voice control connection is unavailable")
                connection.settimeout(min(3.0, remaining))

                request_id = self._next_request_id()
                self._send({"type": "readiness_probe", "request_id": request_id})
                response = self._receive()
                if (
                    response.get("type") != "readiness_response"
                    or response.get("request_id") != request_id
                ):
                    raise RuntimeError("unexpected JARVIS readiness response")

                ready = response.get("ready")
                if ready is True:
                    if expected_release is not None:
                        raw_identity = response.get("release_identity")
                        if not isinstance(raw_identity, dict):
                            raise RuntimeError(
                                "runtime readiness omitted expected release identity"
                            )
                        observed = RuntimeReleaseIdentity(
                            release_sha=str(raw_identity.get("release_sha", "")),
                            release_root=str(raw_identity.get("release_root", "")),
                            promotion_attempt_id=str(
                                raw_identity.get("promotion_attempt_id", "")
                            ),
                            config_digest=str(raw_identity.get("config_digest", "")),
                        )
                        if observed != expected_release:
                            raise RuntimeError(
                                "runtime readiness release identity mismatch"
                            )
                        if self._child_release_identity != expected_release:
                            raise RuntimeError(
                                "runtime hello release identity mismatch"
                            )
                    return
                if ready is not False:
                    raise TypeError("invalid JARVIS readiness state")

                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            self._reset_child()
            raise RuntimeError(f"JARVIS startup readiness failed: {exc}") from exc

    def request_liveness(self, *, timeout_seconds: float) -> bool:
        """Probe only authenticated runtime responsiveness, not dependency health."""

        try:
            self._ensure_child(timeout_seconds=timeout_seconds)
            request_id = self._next_request_id()
            self._send({"type": "liveness_probe", "request_id": request_id})
            response = self._receive()
            valid = (
                response.get("type") == "liveness_response"
                and response.get("request_id") == request_id
                and response.get("alive") is True
            )
            if not valid:
                self._reset_child()
            return valid
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            TypeError,
            json.JSONDecodeError,
        ):
            self._reset_child()
            return False

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


def _runtime_supervisor_config_from_environment() -> DevSupervisorConfig:
    branch = os.environ.get(_BRANCH_ENV, "main").strip() or "main"
    return DevSupervisorConfig(branch=branch, git_updates_enabled=False)


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
    *,
    release_identity: RuntimeReleaseIdentity | None = None,
) -> subprocess.Popen[bytes]:
    child_env = os.environ.copy()
    child_env.update(control.child_environment())
    if release_identity is not None:
        if Path(release_identity.release_root).resolve() != root.resolve():
            raise RuntimeError("release identity root does not match runtime root")
        child_env.update(release_identity.environment())
        source_root = str((root / "src").resolve())
        existing_pythonpath = child_env.get("PYTHONPATH", "").strip()
        child_env["PYTHONPATH"] = (
            source_root
            if not existing_pythonpath
            else os.pathsep.join((source_root, existing_pythonpath))
        )
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    kwargs: dict[str, object] = {"cwd": root, "env": child_env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "-m", "jarvis.voice.production_runtime"],
        **kwargs,
    )
    try:
        _attach_windows_runtime_job(process)
    except WindowsJobObjectError:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3.0)
        raise
    print(f"JARVIS started (pid={process.pid}).")
    return process


def _runtime_revision(
    repo: GitRepo,
    root: Path,
    release_identity: RuntimeReleaseIdentity | None,
) -> str:
    if release_identity is None:
        return repo.local_sha()
    if Path(release_identity.release_root).resolve() != root.resolve():
        raise RuntimeError("release identity root does not match runtime root")
    try:
        observed = (
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            .stdout.strip()
            .casefold()
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("release Git identity is unavailable") from exc
    if observed != release_identity.release_sha:
        raise RuntimeError("release runtime root no longer matches release SHA")
    return observed


class SupervisorReleaseRuntimeDriver:
    """Parent-process runtime switcher used by governed Phase-7 deployment."""

    def __init__(
        self,
        process: subprocess.Popen[bytes] | None,
        control: VoiceControlServer,
        config: DevSupervisorConfig,
    ) -> None:
        self._process: subprocess.Popen[bytes] | None = process
        self._control = control
        self._config = config

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._process

    def stop_active(self, *, timeout_seconds: float) -> None:
        process = self._process
        if process is None:
            return
        _stop_jarvis(
            process,
            timeout_seconds=timeout_seconds,
            control=self._control,
        )
        self._process = None

    def start_release(self, identity: RuntimeReleaseIdentity) -> None:
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("a supervised JARVIS runtime is already active")
        root = Path(identity.release_root).resolve()
        self._process = _start_jarvis(
            root,
            self._control,
            release_identity=identity,
        )

    def wait_ready(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            raise RuntimeError("release runtime is not active")
        self._control.wait_for_child_ready(
            timeout_seconds=timeout_seconds,
            expected_release=identity,
        )

    def stop_candidate(self, *, timeout_seconds: float) -> None:
        self.stop_active(timeout_seconds=timeout_seconds)

    def ensure_release(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            self.start_release(identity)
        self.wait_ready(identity, timeout_seconds=timeout_seconds)


def _phase7_promotion_stores() -> tuple[ChangeStore, PromotionStore]:
    store_path = default_work_store_path()
    work = SQLiteWorkStore(
        store_path,
        payload_codec=build_default_work_payload_codec(store_path),
    )
    changes = ChangeStore(
        work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    return changes, PromotionStore(changes)


def _resume_pending_phase7_deployment(
    repository_root: Path,
    process: subprocess.Popen[bytes] | None,
    control: VoiceControlServer,
    config: DevSupervisorConfig,
) -> tuple[subprocess.Popen[bytes] | None, RuntimeReleaseIdentity | None, str | None]:
    """Start or resume one durable parent-owned Phase-7 deployment handoff."""

    metadata = DeploymentMetadataStore(default_deployment_root())
    changes, promotions = _phase7_promotion_stores()
    recovery = metadata.recovery()
    driver = SupervisorReleaseRuntimeDriver(process, control, config)
    coordinator = DeploymentCoordinator(
        changes,
        promotions,
        stager=GitReleaseStager(repository_root, default_releases_root()),
        metadata=metadata,
        runtime=driver,
        shutdown_timeout_seconds=config.shutdown_timeout_seconds,
        startup_timeout_seconds=config.startup_timeout_seconds,
    )

    if recovery is not None:
        if recovery.phase in {
            RecoveryPhase.STARTUP_FAILED,
            RecoveryPhase.ROLLBACK_STARTED,
            RecoveryPhase.ROLLBACK_VERIFIED,
        }:
            return process, None, None
        attempt = promotions.get(recovery.attempt_id)
        if attempt is None or attempt.state is not PromotionAttemptState.DEPLOYING:
            return process, None, None
        try:
            result = coordinator.resume(attempt)
        except DeploymentError as exc:
            active = metadata.active()
            active_identity = None if active is None else active.runtime_identity()
            return driver.process, active_identity, str(exc)
        return driver.process, result.release.runtime_identity(), None

    merged = promotions.list_by_states(
        (PromotionAttemptState.MERGED,),
        limit=2,
    )
    if not merged:
        return process, None, None
    if len(merged) != 1:
        return (
            process,
            None,
            "multiple merged promotion attempts require owner investigation",
        )
    attempt = merged[0]
    if (
        attempt.promotion_artifact_id is None
        or attempt.promotion_artifact_digest is None
    ):
        return process, None, "merged promotion attempt has no exact evidence artifact"
    artifact = changes.get_artifact(attempt.promotion_artifact_id)
    if (
        artifact is None
        or artifact.kind != "promotion"
        or artifact.digest != attempt.promotion_artifact_digest
    ):
        return process, None, "merged promotion evidence artifact is missing or stale"
    try:
        evidence = PromotionEvidenceV1.from_payload(artifact.payload)
    except ValueError as exc:
        return process, None, f"merged promotion evidence is invalid: {exc}"
    if evidence.attempt_id != attempt.attempt_id:
        return process, None, "merged promotion evidence attempt identity mismatch"

    try:
        result = coordinator.deploy(
            evidence=evidence,
            attempt=attempt,
        )
    except DeploymentError as exc:
        active = metadata.active()
        active_identity = None if active is None else active.runtime_identity()
        return driver.process, active_identity, str(exc)
    return driver.process, result.release.runtime_identity(), None


def _attach_windows_runtime_job(process: subprocess.Popen[bytes]) -> None:
    """Assign the runtime and any already-created descendants to one Windows job."""

    if os.name != "nt":
        return

    job = WindowsRuntimeJob()
    try:
        job.assign_pid(process.pid)
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = ()
        for descendant in descendants:
            try:
                job.assign_pid(descendant.pid)
            except psutil.NoSuchProcess:
                continue
        process._jarvis_runtime_job = job
    except Exception:
        job.close()
        raise


def _runtime_job(process: subprocess.Popen[bytes]) -> WindowsRuntimeJob | None:
    candidate = getattr(process, "_jarvis_runtime_job", None)
    return candidate if isinstance(candidate, WindowsRuntimeJob) else None


def _release_runtime_job(process: subprocess.Popen[bytes]) -> None:
    job = _runtime_job(process)
    if job is None:
        return
    try:
        job.close()
    finally:
        try:
            delattr(process, "_jarvis_runtime_job")
        except AttributeError:
            pass


def _force_cleanup_runtime(
    process: subprocess.Popen[bytes],
    runtime_tree: tuple[psutil.Process, ...],
) -> tuple[bool, int]:
    """Prefer OS-owned Windows job termination; fall back to captured psutil tree."""

    job = _runtime_job(process)
    if job is not None:
        try:
            job.terminate(exit_code=1)
            return True, 0
        except WindowsJobObjectError as exc:
            print(
                "Windows Job Object termination failed; falling back to captured "
                f"runtime tree cleanup: {exc}"
            )
    return False, _kill_runtime_process_tree(runtime_tree)


def _snapshot_runtime_process_tree(root_pid: int) -> tuple[psutil.Process, ...]:
    """Capture only the supervised runtime root and its current descendants."""

    try:
        root = psutil.Process(root_pid)
    except psutil.NoSuchProcess:
        return ()
    return (*tuple(root.children(recursive=True)), root)


def _kill_runtime_process_tree(processes: tuple[psutil.Process, ...]) -> int:
    """Force-stop a previously captured runtime tree without touching siblings."""

    killed = 0
    for candidate in processes:
        try:
            if not candidate.is_running():
                continue
            candidate.kill()
            killed += 1
        except psutil.NoSuchProcess:
            continue
    return killed


def _stop_jarvis(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    control: VoiceControlServer,
) -> None:
    runtime_tree = _snapshot_runtime_process_tree(process.pid)

    def finish_cleanup() -> None:
        used_job, killed = _force_cleanup_runtime(process, runtime_tree)
        if used_job:
            print("Windows Job Object runtime tree cleanup completed.")
        elif killed:
            print(f"Force-terminated {killed} captured runtime process(es).")
        _release_runtime_job(process)
        control.child_stopped()

    if process.poll() is not None:
        finish_cleanup()
        return

    print("Stopping JARVIS gracefully...")
    if control.request_shutdown():
        try:
            process.wait(timeout=timeout_seconds)
            finish_cleanup()
            return
        except subprocess.TimeoutExpired:
            pass

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=timeout_seconds)
        finish_cleanup()
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    used_job, killed = _force_cleanup_runtime(process, runtime_tree)
    if used_job:
        print("Graceful shutdown timed out; terminated Windows runtime Job Object.")
    else:
        print(
            "Graceful shutdown timed out; force-terminated "
            f"{killed} runtime process(es)."
        )
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)
    finally:
        _release_runtime_job(process)
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
    liveness_policy = build_runtime_liveness_policy(
        max_attempts=config.crash_restart_max_attempts,
        rolling_window_seconds=config.crash_restart_window_seconds,
        cooldown_seconds=config.crash_restart_cooldown_seconds,
        backoff_multiplier=config.crash_restart_backoff_multiplier,
    )
    return SupervisorRepairController(
        IncidentService(store),
        policy=policy,
        additional_policies=(liveness_policy,),
    ), store


def _verify_child_stabilization(
    process: subprocess.Popen[bytes],
    control: VoiceControlServer,
    config: DevSupervisorConfig,
    *,
    sleep_fn: Any = time.sleep,
    monotonic_fn: Any = time.monotonic,
) -> tuple[bool, str]:
    """Require a live process and repeated authenticated probes for a stable window."""

    deadline = float(monotonic_fn()) + config.stabilization_seconds
    probes = 0
    while True:
        return_code = process.poll()
        if return_code is not None:
            return False, f"process_exited_during_stabilization:{return_code}"

        if not control.request_liveness(
            timeout_seconds=config.liveness_timeout_seconds
        ):
            return False, "liveness_probe_failed"

        probes += 1
        remaining = deadline - float(monotonic_fn())
        if remaining <= 0:
            return True, f"readiness_and_liveness_stable:{probes}_probes"

        sleep_fn(min(config.liveness_interval_seconds, remaining))


def _recover_unexpected_exit(
    repo: GitRepo,
    root: Path,
    process: subprocess.Popen[bytes],
    control: VoiceControlServer,
    config: DevSupervisorConfig,
    repair: SupervisorRepairController,
    *,
    release_identity: RuntimeReleaseIdentity | None = None,
    sleep_fn: Any = time.sleep,
    now_fn: Any = time.time,
    stabilization_verifier: Any = _verify_child_stabilization,
) -> subprocess.Popen[bytes] | None:
    """Perform the single supervisor-owned bounded same-version restart loop."""

    exit_code = process.returncode

    # The supervised launcher may exit before one of its descendants (notably the
    # Windows venv launcher -> base-interpreter shape). Always close/terminate the
    # old runtime Job Object before starting any replacement so a dead root cannot
    # leave an orphan interpreter beside the recovered runtime.
    _stop_jarvis(
        process,
        timeout_seconds=config.shutdown_timeout_seconds,
        control=control,
    )
    commit_sha = _runtime_revision(repo, root, release_identity)

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
        budget_index = plan.budget.budget_index
        print(
            f"JARVIS exited unexpectedly with code {exit_code}; "
            f"bounded same-version restart attempt {budget_index}/"
            f"{plan.policy.max_attempts} is eligible after {wait_seconds:g}s."
        )
        if wait_seconds > 0:
            sleep_fn(wait_seconds)

        if _runtime_revision(repo, root, release_identity) != commit_sha:
            print(
                "Local revision changed while crash recovery was waiting; "
                "automatic restart aborted rather than repairing a different revision."
            )
            return None

        attempt = repair.start_attempt(
            plan,
            current_revision=_runtime_revision(repo, root, release_identity),
            now_epoch=float(now_fn()),
        )
        try:
            if release_identity is None:
                restarted = _start_jarvis(root, control)
            else:
                restarted = _start_jarvis(
                    root,
                    control,
                    release_identity=release_identity,
                )
        except (OSError, WindowsJobObjectError):
            repair.complete_attempt(
                plan,
                attempt,
                execution_result="same-version child restart failed to start",
                verification_status=RepairVerificationStatus.FAIL,
                verification_summary="process_start_failed",
                post_repair_evidence=("supervisor:process_start_failed",),
                now_epoch=float(now_fn()),
            )
            continue

        try:
            control.wait_for_child_ready(
                timeout_seconds=config.startup_timeout_seconds,
                expected_release=release_identity,
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
                verification_status=RepairVerificationStatus.FAIL,
                verification_summary="startup_readiness_failed",
                post_repair_evidence=("supervisor:startup_readiness_failed",),
                now_epoch=float(now_fn()),
            )
            continue

        stable, verifier_result = stabilization_verifier(
            restarted,
            control,
            config,
            sleep_fn=sleep_fn,
        )
        if not stable:
            _stop_jarvis(
                restarted,
                timeout_seconds=config.shutdown_timeout_seconds,
                control=control,
            )
            repair.complete_attempt(
                plan,
                attempt,
                execution_result="same-version child restart reached readiness",
                verification_status=RepairVerificationStatus.FAIL,
                verification_summary=verifier_result,
                post_repair_evidence=(
                    "supervisor:startup_readiness_confirmed",
                    f"supervisor:{verifier_result}",
                ),
                now_epoch=float(now_fn()),
            )
            continue

        repair.complete_attempt(
            plan,
            attempt,
            execution_result="same-version child restart stabilized",
            verification_status=RepairVerificationStatus.PASS,
            verification_summary=verifier_result,
            post_repair_evidence=(
                "supervisor:startup_readiness_confirmed",
                "supervisor:liveness_stabilized",
            ),
            now_epoch=float(now_fn()),
        )
        print(
            "Same-version JARVIS restart recovered: startup readiness and "
            "liveness stabilization confirmed."
        )
        return restarted


def _liveness_restart_required(
    control: VoiceControlServer,
    config: DevSupervisorConfig,
    failure_streak: int,
) -> tuple[int, bool]:
    """Require consecutive failures plus one confirmation probe before restart."""

    if control.request_liveness(timeout_seconds=config.liveness_timeout_seconds):
        if failure_streak:
            print(
                "JARVIS liveness probe recovered after "
                f"{failure_streak} consecutive failure(s)."
            )
        return 0, False

    next_streak = failure_streak + 1
    print(
        "JARVIS liveness probe failed "
        f"({next_streak}/{config.liveness_failure_threshold})."
    )
    if next_streak < config.liveness_failure_threshold:
        return next_streak, False

    print("JARVIS liveness threshold reached; running confirmation probe.")
    if control.request_liveness(timeout_seconds=config.liveness_timeout_seconds):
        print("JARVIS liveness confirmation succeeded; restart cancelled.")
        return 0, False
    return next_streak, True


def _recover_liveness_failure(
    repo: GitRepo,
    root: Path,
    process: subprocess.Popen[bytes],
    control: VoiceControlServer,
    config: DevSupervisorConfig,
    repair: SupervisorRepairController,
    *,
    release_identity: RuntimeReleaseIdentity | None = None,
    sleep_fn: Any = time.sleep,
    now_fn: Any = time.time,
    stabilization_verifier: Any = _verify_child_stabilization,
) -> subprocess.Popen[bytes] | None:
    """Restart an alive-but-unresponsive runtime under the registered R2 policy."""

    commit_sha = repo.local_sha()

    while True:
        plan = repair.plan_liveness_failure(
            commit_sha=commit_sha,
            now_epoch=float(now_fn()),
        )
        if plan.exhausted:
            print(
                "JARVIS liveness restart budget exhausted for failure "
                f"{plan.fingerprint.fingerprint_id[:12]}; stopping automatic "
                "restart and escalating."
            )
            return None

        wait_seconds = plan.budget.wait_seconds
        budget_index = plan.budget.budget_index
        print(
            "JARVIS runtime is unresponsive; bounded same-version restart "
            f"attempt {budget_index}/{plan.policy.max_attempts} is eligible "
            f"after {wait_seconds:g}s."
        )
        if wait_seconds > 0:
            sleep_fn(wait_seconds)

        if _runtime_revision(repo, root, release_identity) != commit_sha:
            print(
                "Local revision changed while liveness recovery was waiting; "
                "automatic restart aborted rather than repairing a different revision."
            )
            return None

        attempt = repair.start_attempt(
            plan,
            current_revision=_runtime_revision(repo, root, release_identity),
            now_epoch=float(now_fn()),
        )
        _stop_jarvis(
            process,
            timeout_seconds=config.shutdown_timeout_seconds,
            control=control,
        )
        try:
            if release_identity is None:
                restarted = _start_jarvis(root, control)
            else:
                restarted = _start_jarvis(
                    root,
                    control,
                    release_identity=release_identity,
                )
        except (OSError, WindowsJobObjectError):
            repair.complete_attempt(
                plan,
                attempt,
                execution_result="unresponsive child restart failed to start",
                verification_status=RepairVerificationStatus.FAIL,
                verification_summary="process_start_failed",
                post_repair_evidence=("supervisor:process_start_failed",),
                now_epoch=float(now_fn()),
            )
            continue

        try:
            control.wait_for_child_ready(
                timeout_seconds=config.startup_timeout_seconds,
                expected_release=release_identity,
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
                execution_result="unresponsive child restart attempted",
                verification_status=RepairVerificationStatus.FAIL,
                verification_summary="startup_readiness_failed",
                post_repair_evidence=("supervisor:startup_readiness_failed",),
                now_epoch=float(now_fn()),
            )
            process = restarted
            continue

        stable, verifier_result = stabilization_verifier(
            restarted,
            control,
            config,
            sleep_fn=sleep_fn,
        )
        if not stable:
            _stop_jarvis(
                restarted,
                timeout_seconds=config.shutdown_timeout_seconds,
                control=control,
            )
            repair.complete_attempt(
                plan,
                attempt,
                execution_result="unresponsive child restart reached readiness",
                verification_status=RepairVerificationStatus.FAIL,
                verification_summary=verifier_result,
                post_repair_evidence=(
                    "supervisor:startup_readiness_confirmed",
                    f"supervisor:{verifier_result}",
                ),
                now_epoch=float(now_fn()),
            )
            process = restarted
            continue

        repair.complete_attempt(
            plan,
            attempt,
            execution_result="unresponsive child restart stabilized",
            verification_status=RepairVerificationStatus.PASS,
            verification_summary=verifier_result,
            post_repair_evidence=(
                "supervisor:startup_readiness_confirmed",
                "supervisor:liveness_stabilized",
            ),
            now_epoch=float(now_fn()),
        )
        print(
            "JARVIS liveness recovery succeeded: startup readiness and "
            "liveness stabilization confirmed."
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
            control.wait_for_child_ready(
                timeout_seconds=config.startup_timeout_seconds,
            )
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
            control.wait_for_child_ready(
                timeout_seconds=config.startup_timeout_seconds,
            )
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


def _escalation_exit_code(
    config: DevSupervisorConfig,
    fallback_code: int = 1,
) -> int:
    """Production guardian mode must not restart after intentional fail-closed stop."""

    return fallback_code if config.git_updates_enabled else 0


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

    runtime_root = root
    release_identity: RuntimeReleaseIdentity | None = None
    if not config.git_updates_enabled:
        active_release = load_active_release_for_startup()
        if active_release is not None:
            runtime_root = Path(active_release.release_root).resolve()
            release_identity = active_release.runtime_identity()

    if config.git_updates_enabled:
        print("JARVIS development supervisor")
        print(
            f"Watching {config.remote}/{config.branch} every {config.poll_seconds:g}s."
        )
        print("Updates require one explicit spoken owner Yes/No decision.")
        print("Ambiguous speech, timeout, or unavailable voice approval means No.")
    else:
        print("JARVIS production runtime supervisor")
        print("Git/network update polling is disabled; Self-Repair remains local-only.")
        if release_identity is not None:
            print(
                "Starting durable active release "
                f"{release_identity.release_sha[:10]} from {runtime_root}."
            )

    control = VoiceControlServer()
    repair, repair_store = _build_supervisor_repair_controller(config)
    process: subprocess.Popen[bytes] | None = None
    if not config.git_updates_enabled:
        process, recovered_identity, deployment_error = (
            _resume_pending_phase7_deployment(
                root,
                None,
                control,
                config,
            )
        )
        if recovered_identity is not None:
            release_identity = recovered_identity
            runtime_root = Path(recovered_identity.release_root).resolve()
        if deployment_error is not None:
            print(f"Phase-7 deployment recovery: {deployment_error}")
    if process is None:
        process = _start_jarvis(
            runtime_root,
            control,
            release_identity=release_identity,
        )
    update_poller = (
        RemoteUpdatePoller(root, config) if config.git_updates_enabled else None
    )
    update_poller_started = False
    declined_sha: str | None = None
    liveness_failure_streak = 0

    try:
        try:
            control.wait_for_child_ready(
                timeout_seconds=config.startup_timeout_seconds,
                expected_release=release_identity,
            )
        except RuntimeError as exc:
            print(f"Initial JARVIS startup readiness failed: {exc}")
            return _escalation_exit_code(config)

        if update_poller is not None:
            update_poller.start()
            update_poller_started = True

        while True:
            if process.poll() is not None:
                if repair is None:
                    print(
                        f"JARVIS exited unexpectedly with code {process.returncode}; "
                        "durable Self-Repair is unavailable, so automatic restart "
                        "fails closed."
                    )
                    return _escalation_exit_code(
                        config,
                        int(process.returncode or 1),
                    )
                restarted = _recover_unexpected_exit(
                    repo,
                    runtime_root,
                    process,
                    control,
                    config,
                    repair,
                    release_identity=release_identity,
                )
                if restarted is None:
                    return _escalation_exit_code(
                        config,
                        int(process.returncode or 1),
                    )
                process = restarted
                continue

            time.sleep(config.poll_seconds)
            if process.poll() is not None:
                continue

            if not config.git_updates_enabled:
                resumed_process, resumed_identity, deployment_error = (
                    _resume_pending_phase7_deployment(
                        root,
                        process,
                        control,
                        config,
                    )
                )
                if resumed_identity is not None or deployment_error is not None:
                    if resumed_process is None:
                        print(
                            "Phase-7 deployment handoff left no runnable JARVIS; "
                            "failing closed."
                        )
                        return _escalation_exit_code(config)
                    process = resumed_process
                    if resumed_identity is not None:
                        release_identity = resumed_identity
                        runtime_root = Path(resumed_identity.release_root).resolve()
                    if deployment_error is not None:
                        print(f"Phase-7 deployment handoff: {deployment_error}")
                    else:
                        print(
                            "Phase-7 deployment activated exact release "
                            f"{release_identity.release_sha[:10]}."
                        )
                    liveness_failure_streak = 0
                    continue

            liveness_failure_streak, restart_required = _liveness_restart_required(
                control,
                config,
                liveness_failure_streak,
            )
            if restart_required:
                if process.poll() is not None:
                    continue
                if repair is None:
                    print(
                        "JARVIS runtime failed the liveness watchdog, but durable "
                        "Self-Repair is unavailable; automatic restart fails closed."
                    )
                    return _escalation_exit_code(config)
                restarted = _recover_liveness_failure(
                    repo,
                    runtime_root,
                    process,
                    control,
                    config,
                    repair,
                    release_identity=release_identity,
                )
                if restarted is None:
                    return _escalation_exit_code(config)
                process = restarted
                liveness_failure_streak = 0
                continue

            if update_poller is None:
                continue

            remote_poll = update_poller.latest()
            if remote_poll is None:
                continue
            if remote_poll.error is not None:
                print(
                    "Git update poll failed in the background; "
                    f"watchdog remains active: {remote_poll.error}"
                )
                continue

            local_sha = remote_poll.local_sha
            remote_sha = remote_poll.remote_sha
            if local_sha is None or remote_sha is None:
                continue

            if repo.local_sha() != local_sha:
                # The snapshot became stale while an intentional local update changed
                # the checked-out revision. Wait for the next background poll.
                continue
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
        if update_poller_started and update_poller is not None:
            update_poller.stop()
        _stop_jarvis(
            process,
            timeout_seconds=config.shutdown_timeout_seconds,
            control=control,
        )
        control.close()
        if repair_store is not None:
            repair_store.close()


def runtime_supervisor_main() -> int:
    try:
        return run_supervisor(_runtime_supervisor_config_from_environment())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"jarvis-supervisor error: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    try:
        return run_supervisor()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"jarvis-dev error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
