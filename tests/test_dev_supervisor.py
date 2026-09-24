from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import jarvis.dev_supervisor as supervisor
from jarvis.dev_supervisor import DevSupervisorConfig, _config_from_environment


def test_supervisor_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        DevSupervisorConfig(remote=" ")
    with pytest.raises(ValueError):
        DevSupervisorConfig(branch=" ")
    with pytest.raises(ValueError):
        DevSupervisorConfig(poll_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(shutdown_timeout_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(approval_timeout_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(startup_timeout_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_max_attempts=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_max_attempts=True)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_window_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_cooldown_seconds=-1)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_backoff_multiplier=0.5)
    with pytest.raises(ValueError):
        DevSupervisorConfig(liveness_timeout_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(stabilization_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(liveness_interval_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(liveness_failure_threshold=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(liveness_failure_threshold=True)
    with pytest.raises(ValueError):
        DevSupervisorConfig(git_fetch_timeout_seconds=0)


def test_environment_config_defaults_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_DEV_BRANCH", raising=False)

    assert _config_from_environment().branch == "main"


def test_environment_config_allows_explicit_development_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_DEV_BRANCH", " feature/jarvis-dev-supervisor ")

    assert _config_from_environment().branch == "feature/jarvis-dev-supervisor"


def test_supervisor_startup_timeout_allows_heavy_hardware_initialization() -> None:
    assert DevSupervisorConfig().startup_timeout_seconds == 120.0


def test_wait_for_child_ready_requires_explicit_runtime_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.timeouts: list[float] = []
            self.closed = False
            self.responses = [
                b'{"type":"readiness_response","request_id":"1","ready":false}\n',
                b'{"type":"readiness_response","request_id":"2","ready":true}\n',
            ]
            self.writes: list[bytes] = []

        def settimeout(self, timeout: float) -> None:
            self.timeouts.append(timeout)

        def sendall(self, data: bytes) -> None:
            self.writes.append(data)

        def recv(self, size: int) -> bytes:
            assert size > 0
            return self.responses.pop(0)

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    control = supervisor.VoiceControlServer()
    control._connection = connection
    monkeypatch.setattr(supervisor.time, "sleep", lambda _: None)

    try:
        control.wait_for_child_ready(timeout_seconds=2.0)
    finally:
        control.close()

    assert connection.writes == [
        b'{"type":"readiness_probe","request_id":"1"}\n',
        b'{"type":"readiness_probe","request_id":"2"}\n',
    ]
    assert connection.closed is True


def test_liveness_timeout_resets_direct_socket_connection() -> None:
    class FrozenConnection:
        def __init__(self) -> None:
            self.closed = False
            self.writes: list[bytes] = []

        def settimeout(self, timeout: float) -> None:
            assert timeout > 0

        def sendall(self, data: bytes) -> None:
            self.writes.append(data)

        def recv(self, size: int) -> bytes:
            assert size > 0
            raise TimeoutError("frozen runtime")

        def close(self) -> None:
            self.closed = True

    connection = FrozenConnection()
    control = supervisor.VoiceControlServer()
    control._connection = connection

    try:
        assert control.request_liveness(timeout_seconds=0.1) is False
        assert control._connection is None
    finally:
        control.close()

    assert connection.closed is True
    assert connection.writes == [b'{"type":"liveness_probe","request_id":"1"}\n']


def test_direct_socket_receive_handles_fragmented_control_frame() -> None:
    class FragmentedConnection:
        def __init__(self) -> None:
            self.fragments = [
                b'{"type":"liveness_',
                b'response","request_id":"1","alive":true}\n',
            ]
            self.closed = False

        def settimeout(self, timeout: float) -> None:
            assert timeout > 0

        def sendall(self, data: bytes) -> None:
            assert data == b'{"type":"liveness_probe","request_id":"1"}\n'

        def recv(self, size: int) -> bytes:
            assert size > 0
            return self.fragments.pop(0)

        def close(self) -> None:
            self.closed = True

    connection = FragmentedConnection()
    control = supervisor.VoiceControlServer()
    control._connection = connection

    try:
        assert control.request_liveness(timeout_seconds=0.1) is True
    finally:
        control.close()

    assert connection.closed is True


def test_git_fetch_uses_bounded_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    repo = supervisor.GitRepo(
        tmp_path,
        DevSupervisorConfig(git_fetch_timeout_seconds=7.5),
    )

    repo.fetch()

    assert observed["kwargs"]["timeout"] == 7.5


def test_remote_update_poller_cannot_block_liveness_watchdog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    fetch_started = threading.Event()
    release_fetch = threading.Event()

    class BlockingRepo:
        def __init__(self, root: Path, config: DevSupervisorConfig) -> None:
            self.root = root
            self.config = config

        def fetch(self) -> None:
            fetch_started.set()
            release_fetch.wait(timeout=2.0)

        def local_sha(self) -> str:
            return "a" * 40

        def remote_sha(self) -> str:
            return "a" * 40

    class AliveControl:
        def request_liveness(self, *, timeout_seconds: float) -> bool:
            assert timeout_seconds > 0
            return True

    monkeypatch.setattr(supervisor, "GitRepo", BlockingRepo)
    poller = supervisor.RemoteUpdatePoller(
        tmp_path,
        DevSupervisorConfig(poll_seconds=60),
    )
    poller.start()

    try:
        assert fetch_started.wait(timeout=0.5)
        assert poller.thread.daemon is True
        assert supervisor._liveness_restart_required(
            AliveControl(),  # type: ignore[arg-type]
            DevSupervisorConfig(),
            0,
        ) == (0, False)
    finally:
        release_fetch.set()
        poller.stop()
        poller.thread.join(timeout=1.0)


def test_remote_update_poller_publishes_latest_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    published = threading.Event()

    class SnapshotRepo:
        def __init__(self, root: Path, config: DevSupervisorConfig) -> None:
            self.root = root
            self.config = config

        def fetch(self) -> None:
            pass

        def local_sha(self) -> str:
            return "a" * 40

        def remote_sha(self) -> str:
            published.set()
            return "b" * 40

    monkeypatch.setattr(supervisor, "GitRepo", SnapshotRepo)
    poller = supervisor.RemoteUpdatePoller(
        tmp_path,
        DevSupervisorConfig(poll_seconds=60),
    )
    poller.start()

    try:
        assert published.wait(timeout=0.5)
        snapshot = None
        for _ in range(20):
            snapshot = poller.latest()
            if snapshot is not None:
                break
            supervisor.time.sleep(0.01)
        assert snapshot is not None
        assert snapshot.local_sha == "a" * 40
        assert snapshot.remote_sha == "b" * 40
        assert snapshot.error is None
    finally:
        poller.stop()
        poller.thread.join(timeout=1.0)


def test_force_runtime_tree_cleanup_targets_descendants_before_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    class FakePsProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def children(self, *, recursive: bool) -> list[FakePsProcess]:
            assert recursive is True
            return [FakePsProcess(31), FakePsProcess(32)] if self.pid == 30 else []

        def is_running(self) -> bool:
            return True

        def kill(self) -> None:
            calls.append(("kill", self.pid))

    monkeypatch.setattr(supervisor.psutil, "Process", FakePsProcess)

    tree = supervisor._snapshot_runtime_process_tree(30)
    killed = supervisor._kill_runtime_process_tree(tree)

    assert tuple(process.pid for process in tree) == (31, 32, 30)
    assert killed == 3
    assert calls == [("kill", 31), ("kill", 32), ("kill", 30)]


def test_windows_runtime_job_is_attached_to_root_and_existing_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeJob:
        def assign_pid(self, pid: int) -> None:
            calls.append(("assign", pid))

        def close(self) -> None:
            calls.append(("close",))

    class FakeRoot:
        def children(self, *, recursive: bool):
            assert recursive is True
            return [SimpleNamespace(pid=31), SimpleNamespace(pid=32)]

    process = SimpleNamespace(pid=30)
    monkeypatch.setattr(supervisor, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(supervisor, "WindowsRuntimeJob", FakeJob)
    monkeypatch.setattr(supervisor.psutil, "Process", lambda pid: FakeRoot())

    supervisor._attach_windows_runtime_job(process)  # type: ignore[arg-type]

    assert calls == [("assign", 30), ("assign", 31), ("assign", 32)]
    assert isinstance(process._jarvis_runtime_job, FakeJob)


def test_force_cleanup_prefers_windows_runtime_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeJob:
        def terminate(self, *, exit_code: int) -> None:
            calls.append(("terminate", exit_code))

        def close(self) -> None:
            calls.append(("close",))

    monkeypatch.setattr(supervisor, "WindowsRuntimeJob", FakeJob)
    monkeypatch.setattr(
        supervisor,
        "_kill_runtime_process_tree",
        lambda tree: (_ for _ in ()).throw(AssertionError("psutil fallback used")),
    )
    process = SimpleNamespace(_jarvis_runtime_job=FakeJob())

    used_job, killed = supervisor._force_cleanup_runtime(
        process,  # type: ignore[arg-type]
        ("captured",),  # type: ignore[arg-type]
    )
    supervisor._release_runtime_job(process)  # type: ignore[arg-type]

    assert used_job is True
    assert killed == 0
    assert calls == [("terminate", 1), ("close",)]
    assert not hasattr(process, "_jarvis_runtime_job")


def test_stop_jarvis_force_cleans_captured_runtime_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    runtime_tree = ("child", "root")

    class FakeProcess:
        pid = 30

        def __init__(self) -> None:
            self.wait_calls = 0

        def poll(self):
            return None

        def send_signal(self, signal_value) -> None:
            calls.append(("signal", signal_value))

        def wait(self, timeout: float) -> None:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise supervisor.subprocess.TimeoutExpired("jarvis", timeout)
            calls.append(("wait", timeout))

        def kill(self) -> None:
            calls.append("popen-kill")

    class FakeStopControl:
        def request_shutdown(self) -> bool:
            return False

        def child_stopped(self) -> None:
            calls.append("child-stopped")

    monkeypatch.setattr(
        supervisor,
        "_snapshot_runtime_process_tree",
        lambda pid: runtime_tree,
    )

    def fake_tree_kill(tree) -> int:
        assert tree == runtime_tree
        calls.append("tree-kill")
        return 2

    monkeypatch.setattr(supervisor, "_kill_runtime_process_tree", fake_tree_kill)
    monkeypatch.setattr(supervisor, "os", SimpleNamespace(name="posix"))

    supervisor._stop_jarvis(
        FakeProcess(),  # type: ignore[arg-type]
        timeout_seconds=1.0,
        control=FakeStopControl(),  # type: ignore[arg-type]
    )

    assert "tree-kill" in calls
    assert "popen-kill" not in calls
    assert calls[-1] == "child-stopped"


class FakeRepo:
    def __init__(self, *, updated_sha: str = "b" * 40) -> None:
        self.updated_sha = updated_sha
        self.pull_count = 0
        self.reset_to: str | None = None

    def pull_fast_forward(self) -> None:
        self.pull_count += 1

    def local_sha(self) -> str:
        return self.updated_sha

    def reset_hard(self, sha: str) -> None:
        self.reset_to = sha


class FakeControl:
    def __init__(
        self,
        readiness_outcomes: list[Exception | None],
        liveness_outcomes: list[bool] | None = None,
    ) -> None:
        self.readiness_outcomes = list(readiness_outcomes)
        self.liveness_outcomes = list(liveness_outcomes or ())
        self.readiness_calls = 0
        self.liveness_calls = 0
        self.child_stopped_calls = 0

    def child_stopped(self) -> None:
        self.child_stopped_calls += 1

    def wait_for_child_ready(self, *, timeout_seconds: float) -> None:
        assert timeout_seconds > 0
        self.readiness_calls += 1
        outcome = self.readiness_outcomes.pop(0)
        if outcome is not None:
            raise outcome

    def request_liveness(self, *, timeout_seconds: float) -> bool:
        assert timeout_seconds > 0
        self.liveness_calls += 1
        if not self.liveness_outcomes:
            return True
        return self.liveness_outcomes.pop(0)


def test_liveness_watchdog_ignores_transient_failure() -> None:
    control = FakeControl([], [False, True])
    config = DevSupervisorConfig(liveness_failure_threshold=3)

    streak, restart = supervisor._liveness_restart_required(
        control,  # type: ignore[arg-type]
        config,
        0,
    )
    assert (streak, restart) == (1, False)

    streak, restart = supervisor._liveness_restart_required(
        control,  # type: ignore[arg-type]
        config,
        streak,
    )
    assert (streak, restart) == (0, False)


def test_liveness_watchdog_requires_threshold_and_confirmation() -> None:
    control = FakeControl([], [False, False, False, False])
    config = DevSupervisorConfig(liveness_failure_threshold=3)

    streak, restart = supervisor._liveness_restart_required(
        control,  # type: ignore[arg-type]
        config,
        0,
    )
    assert (streak, restart) == (1, False)

    streak, restart = supervisor._liveness_restart_required(
        control,  # type: ignore[arg-type]
        config,
        streak,
    )
    assert (streak, restart) == (2, False)

    streak, restart = supervisor._liveness_restart_required(
        control,  # type: ignore[arg-type]
        config,
        streak,
    )
    assert (streak, restart) == (3, True)
    assert control.liveness_calls == 4


def test_liveness_watchdog_confirmation_can_cancel_restart() -> None:
    control = FakeControl([], [False, True])
    config = DevSupervisorConfig(liveness_failure_threshold=3)

    streak, restart = supervisor._liveness_restart_required(
        control,  # type: ignore[arg-type]
        config,
        2,
    )

    assert (streak, restart) == (0, False)
    assert control.liveness_calls == 2


def test_approved_update_keeps_new_revision_after_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepo()
    control = FakeControl([None])
    stopped: list[object] = []
    started = iter(["new-process"])
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda process, **_: stopped.append(process),
    )
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )

    process, healthy = supervisor._apply_approved_update(
        repo,  # type: ignore[arg-type]
        Path("."),
        "old-process",  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(),
        previous_sha="a" * 40,
        remote_sha="b" * 40,
    )

    assert healthy is True
    assert process == "new-process"
    assert stopped == ["old-process"]
    assert repo.pull_count == 1
    assert repo.reset_to is None
    assert control.readiness_calls == 1


def test_approved_update_rolls_back_when_new_revision_never_becomes_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_sha = "a" * 40
    repo = FakeRepo()
    control = FakeControl([RuntimeError("new child failed"), None])
    stopped: list[object] = []
    started = iter(["new-process", "rollback-process"])
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda process, **_: stopped.append(process),
    )
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )

    process, healthy = supervisor._apply_approved_update(
        repo,  # type: ignore[arg-type]
        Path("."),
        "old-process",  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(),
        previous_sha=previous_sha,
        remote_sha="b" * 40,
    )

    assert healthy is False
    assert process == "rollback-process"
    assert stopped == ["old-process", "new-process"]
    assert repo.pull_count == 1
    assert repo.reset_to == previous_sha
    assert control.readiness_calls == 2


def test_transient_voice_approval_failure_is_not_an_owner_decline() -> None:
    source = Path(supervisor.__file__).read_text(encoding="utf-8")

    assert "the update will be offered again" in source
    assert "declined_sha = None" in source


def test_dev_control_client_is_expected_to_reconnect_after_transient_failure() -> None:
    from jarvis import dev_control

    source = Path(dev_control.__file__).read_text(encoding="utf-8")

    assert "while True:" in source
    assert "await asyncio.sleep(1.0)" in source


def test_unexpected_exit_requires_stabilization_before_recovered(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.incidents import IncidentService, SqliteIncidentStore
    from jarvis.self_repair import RepairVerdict
    from jarvis.self_repair.supervisor import (
        SupervisorRepairController,
        build_runtime_child_exit_policy,
    )

    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=2,
            cooldown_seconds=0,
        ),
    )
    repo = FakeRepo(updated_sha="a" * 40)
    control = FakeControl([None])
    process = SimpleNamespace(returncode=9)
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: "restarted-process",
    )
    now = iter([100.0, 100.0, 101.0])

    restarted = supervisor._recover_unexpected_exit(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=2,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: next(now),
        stabilization_verifier=lambda *_, **__: (
            True,
            "readiness_and_liveness_stable:3_probes",
        ),
    )

    assert restarted == "restarted-process"
    incident = incidents.list_recent(limit=1)[0]
    attempts = incidents.list_repair_attempts(incident.incident_id)
    assert len(attempts) == 1
    assert attempts[0].verdict is RepairVerdict.RECOVERED
    assert attempts[0].verifier_result == "readiness_and_liveness_stable:3_probes"
    assert attempts[0].action.component_id == "voice_runtime"
    assert control.child_stopped_calls == 1
    store.close()


def test_stabilization_requires_repeated_liveness_probes() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0
            self.sleeps: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

    clock = FakeClock()
    control = FakeControl([], [True, True, True, True])
    process = SimpleNamespace(poll=lambda: None)

    stable, verifier = supervisor._verify_child_stabilization(
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            liveness_timeout_seconds=1,
            stabilization_seconds=5,
            liveness_interval_seconds=2,
        ),
        sleep_fn=clock.sleep,
        monotonic_fn=clock.monotonic,
    )

    assert stable is True
    assert verifier == "readiness_and_liveness_stable:4_probes"
    assert control.liveness_calls == 4
    assert clock.sleeps == [2, 2, 1]


def test_stabilization_fails_when_authenticated_liveness_fails() -> None:
    control = FakeControl([], [False])
    process = SimpleNamespace(poll=lambda: None)

    stable, verifier = supervisor._verify_child_stabilization(
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(),
        sleep_fn=lambda _: None,
        monotonic_fn=lambda: 0.0,
    )

    assert stable is False
    assert verifier == "liveness_probe_failed"
    assert control.liveness_calls == 1


def test_readiness_failures_exhaust_restart_budget(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.incidents import IncidentService, SqliteIncidentStore
    from jarvis.self_repair import RepairVerdict
    from jarvis.self_repair.supervisor import (
        SupervisorRepairController,
        build_runtime_child_exit_policy,
    )

    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=2,
            rolling_window_seconds=300,
            cooldown_seconds=0,
        ),
    )
    repo = FakeRepo(updated_sha="a" * 40)
    control = FakeControl([RuntimeError("not ready"), RuntimeError("still not ready")])
    process = SimpleNamespace(returncode=9)
    started = iter(["restart-1", "restart-2"])
    stopped: list[object] = []
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda candidate, **_: stopped.append(candidate),
    )
    now = iter([100.0, 100.0, 101.0, 102.0, 102.0, 103.0, 104.0])

    restarted = supervisor._recover_unexpected_exit(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=2,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: next(now),
    )

    assert restarted is None
    incident = incidents.list_recent(limit=1)[0]
    attempts = incidents.list_repair_attempts(incident.incident_id)
    assert len(attempts) == 2
    assert all(attempt.verdict is RepairVerdict.NOT_RECOVERED for attempt in attempts)
    assert stopped == ["restart-1", "restart-2"]
    assert any(
        evidence.kind == "repair_budget_exhausted" for evidence in incident.evidence
    )
    store.close()


def test_liveness_failures_consume_budget_and_stop_restarting(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.incidents import IncidentService, SqliteIncidentStore
    from jarvis.self_repair import RepairVerdict
    from jarvis.self_repair.supervisor import (
        SupervisorRepairController,
        build_runtime_child_exit_policy,
    )

    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=2,
            rolling_window_seconds=300,
            cooldown_seconds=0,
        ),
    )
    repo = FakeRepo(updated_sha="a" * 40)
    control = FakeControl([None, None])
    process = SimpleNamespace(returncode=9)
    started = iter(["restart-1", "restart-2"])
    stopped: list[object] = []
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda candidate, **_: stopped.append(candidate),
    )
    now = iter([100.0, 100.0, 101.0, 102.0, 102.0, 103.0, 104.0])

    restarted = supervisor._recover_unexpected_exit(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=2,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: next(now),
        stabilization_verifier=lambda *_, **__: (
            False,
            "liveness_probe_failed",
        ),
    )

    assert restarted is None
    incident = incidents.list_recent(limit=1)[0]
    attempts = incidents.list_repair_attempts(incident.incident_id)
    assert len(attempts) == 2
    assert all(attempt.verdict is RepairVerdict.NOT_RECOVERED for attempt in attempts)
    assert all(
        attempt.verifier_result == "liveness_probe_failed" for attempt in attempts
    )
    assert stopped == ["restart-1", "restart-2"]
    store.close()


def test_unresponsive_runtime_uses_separate_registered_repair_policy(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.incidents import IncidentService, SqliteIncidentStore
    from jarvis.self_repair import RepairVerdict
    from jarvis.self_repair.supervisor import (
        SupervisorRepairController,
        build_runtime_child_exit_policy,
        build_runtime_liveness_policy,
    )

    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=2,
            cooldown_seconds=0,
        ),
        additional_policies=(
            build_runtime_liveness_policy(
                max_attempts=2,
                cooldown_seconds=0,
            ),
        ),
    )
    repo = FakeRepo(updated_sha="a" * 40)
    control = FakeControl([None])
    process = SimpleNamespace(poll=lambda: None)
    stopped: list[object] = []
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda candidate, **_: stopped.append(candidate),
    )
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: "restarted-process",
    )
    now = iter([100.0, 100.0, 101.0])

    restarted = supervisor._recover_liveness_failure(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=2,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: next(now),
        stabilization_verifier=lambda *_, **__: (
            True,
            "readiness_and_liveness_stable:3_probes",
        ),
    )

    assert restarted == "restarted-process"
    incident = incidents.list_recent(limit=1)[0]
    assert incident.title == "JARVIS runtime became unresponsive"
    attempts = incidents.list_repair_attempts(incident.incident_id)
    assert len(attempts) == 1
    assert attempts[0].policy_id == "supervisor-runtime-unresponsive-v1"
    assert attempts[0].verdict is RepairVerdict.RECOVERED
    assert stopped == [process]
    store.close()


def test_production_supervisor_escalation_does_not_trigger_outer_restart() -> None:
    production = DevSupervisorConfig(git_updates_enabled=False)
    development = DevSupervisorConfig(git_updates_enabled=True)

    assert supervisor._escalation_exit_code(production, 17) == 0
    assert supervisor._escalation_exit_code(development, 17) == 17


def test_runtime_supervisor_configuration_disables_git_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_DEV_BRANCH", raising=False)

    config = supervisor._runtime_supervisor_config_from_environment()

    assert config.branch == "main"
    assert config.git_updates_enabled is False
