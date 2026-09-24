from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from jarvis.self_repair.windows_job import WindowsRuntimeJob


class FakeJobApi:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.members: set[int] = set()

    def create_job(self) -> object:
        self.calls.append(("create",))
        return "job"

    def set_kill_on_close(self, job: object) -> None:
        self.calls.append(("kill_on_close", job))

    def contains_pid(self, job: object, pid: int) -> bool:
        self.calls.append(("contains", job, pid))
        return pid in self.members

    def assign_pid(self, job: object, pid: int) -> None:
        self.calls.append(("assign", job, pid))
        self.members.add(pid)

    def terminate_job(self, job: object, exit_code: int) -> None:
        self.calls.append(("terminate", job, exit_code))

    def close_job(self, job: object) -> None:
        self.calls.append(("close", job))


def test_windows_runtime_job_configures_kill_on_close_and_assigns_once() -> None:
    api = FakeJobApi()
    job = WindowsRuntimeJob(api=api)

    job.assign_pid(42)
    job.assign_pid(42)

    assert api.calls == [
        ("create",),
        ("kill_on_close", "job"),
        ("contains", "job", 42),
        ("assign", "job", 42),
        ("contains", "job", 42),
    ]


def test_windows_runtime_job_terminates_and_closes_idempotently() -> None:
    api = FakeJobApi()
    job = WindowsRuntimeJob(api=api)

    job.terminate(exit_code=17)
    job.close()
    job.close()

    assert ("terminate", "job", 17) in api.calls
    assert api.calls.count(("close", "job")) == 1
    assert job.closed is True


def test_windows_runtime_job_rejects_invalid_pid_and_closed_use() -> None:
    api = FakeJobApi()
    job = WindowsRuntimeJob(api=api)

    with pytest.raises(ValueError, match="pid"):
        job.assign_pid(0)

    job.close()
    with pytest.raises(RuntimeError, match="already closed"):
        job.assign_pid(42)


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows Job Objects")
def test_real_windows_job_terminate_kills_assigned_process() -> None:
    job = WindowsRuntimeJob()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        job.assign_pid(process.pid)
        job.terminate(exit_code=37)
        assert process.wait(timeout=5.0) == 37
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
        job.close()


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows Job Objects")
def test_real_windows_job_kill_on_close_prevents_orphan_runtime() -> None:
    job = WindowsRuntimeJob()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        job.assign_pid(process.pid)
        started = time.monotonic()
        job.close()
        return_code = process.wait(timeout=5.0)
        elapsed = time.monotonic() - started

        # KILL_ON_JOB_CLOSE guarantees termination, not a particular exit code.
        # Returning within this short bound proves the 30-second child did not
        # survive as an orphan after the last job handle closed.
        assert return_code is not None
        assert elapsed < 5.0
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
        job.close()
