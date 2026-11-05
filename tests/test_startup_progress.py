"""Supervisor startup readiness is judged by progress, not one fixed deadline.

Root cause (owner PC, 2026-11-04): the voice child builds everything before its
control channel connects. A cold LR-ASD CUDA load took 80 s, so the whole
build exceeded the supervisor's single 120 s deadline and a healthy start was
killed ("JARVIS startup readiness failed: timed out"). These tests start real
child processes and talk to them over the real loopback control protocol.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

import jarvis.dev_supervisor as supervisor
from jarvis import startup_progress

SRC = Path(__file__).resolve().parents[1] / "src"

CHILD = textwrap.dedent(
    """
    import asyncio, logging, os, sys, threading, time
    from jarvis import startup_progress
    from jarvis.dev_control import DevControlClient

    steps, gap, heartbeat, background = (
        int(sys.argv[1]), float(sys.argv[2]), sys.argv[3] == "1", sys.argv[4] == "1"
    )
    logging.basicConfig(level=logging.INFO)
    if heartbeat:
        startup_progress.install()
    if background:
        def chatter():
            while True:
                logging.info("background thread still logging")
                time.sleep(0.1)
        threading.Thread(target=chatter, daemon=True).start()
    for step in range(steps):
        logging.info("startup step %s", step)
        time.sleep(gap)
    if os.environ.get("CHILD_HANG"):
        time.sleep(3600)
    if os.environ.get("CHILD_EXIT"):
        raise SystemExit(7)
    client = DevControlClient.from_environment()
    client.mark_ready()

    async def approval(*args):
        return False

    async def main():
        await asyncio.wait_for(
            client.run(approval_handler=approval, shutdown_handler=lambda: None), 20
        )

    try:
        asyncio.run(main())
    except asyncio.TimeoutError:
        pass
    """
)


def _start(control, *args, **env):
    environment = dict(os.environ)
    environment.update(control.child_environment())
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), environment.get("PYTHONPATH", "")]
    )
    environment.update(env)
    process = subprocess.Popen(
        [sys.executable, "-c", CHILD, *[str(a) for a in args]], env=environment
    )
    control.watch_startup(process)
    return process


@pytest.fixture
def control():
    server = supervisor.VoiceControlServer()
    processes = []
    server.start = lambda *a, **k: (
        processes.append(_start(server, *a, **k)) or (processes[-1])
    )
    yield server
    for process in processes:
        # Windows venv python.exe can be a redirector with a real Python child.
        # Killing only the redirector leaves a hanging synthetic child behind.
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        for child in descendants:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(descendants, timeout=10)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
    server.close()


def test_slow_but_progressing_startup_is_not_killed(control):
    # 6 s of steady steps against a 2 s stall window: the old single deadline
    # would have failed this healthy start.
    control.start(20, 0.3, 1, 0)
    started = time.monotonic()
    control.wait_for_child_ready(timeout_seconds=2.0)
    assert time.monotonic() - started > 5.0


def test_hung_startup_is_detected_despite_background_logging(control):
    control.start(3, 0.1, 1, 1, CHILD_HANG="1")
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="no startup progress for 2 s"):
        control.wait_for_child_ready(timeout_seconds=2.0)
    assert time.monotonic() - started < 8.0


def test_child_exit_during_startup_is_reported_at_once(control):
    control.start(2, 0.1, 1, 0, CHILD_EXIT="1")
    with pytest.raises(RuntimeError, match="exited during startup .exit code 7"):
        control.wait_for_child_ready(timeout_seconds=30.0)


def test_child_without_heartbeat_keeps_the_old_deadline(control):
    control.start(20, 0.3, 0, 0)  # an older build: no progress file
    with pytest.raises(RuntimeError, match="no startup progress"):
        control.wait_for_child_ready(timeout_seconds=2.0)


def test_overall_cap_still_bounds_a_progressing_startup(control, monkeypatch):
    monkeypatch.setattr(supervisor, "STARTUP_MAX_SECONDS", 2.5)
    control.start(40, 0.3, 1, 0)
    with pytest.raises(RuntimeError, match="startup exceeded 2.5 s"):
        control.wait_for_child_ready(timeout_seconds=2.0)


def test_progress_from_another_process_is_ignored(control, tmp_path):
    process = control.start(1, 0.1, 0, 0, CHILD_HANG="1")
    # A stale file from an earlier child (different pid) is not progress.
    startup_progress.write_progress(control._progress_path, 99)
    payload = startup_progress.read_progress(control._progress_path)
    assert payload["pid"] != process.pid
    with pytest.raises(RuntimeError, match="no startup progress"):
        control.wait_for_child_ready(timeout_seconds=2.0)


def test_heartbeat_counts_only_main_thread_and_finishes(tmp_path, monkeypatch):
    import logging
    import threading

    path = tmp_path / "progress.json"
    monkeypatch.setenv(startup_progress.STARTUP_PROGRESS_FILE_ENV, str(path))
    startup_progress.install()
    try:
        assert startup_progress.read_progress(path)["sequence"] == 0
        worker = threading.Thread(target=lambda: logging.getLogger("x").warning("bg"))
        worker.start()
        worker.join()
        assert startup_progress.read_progress(path)["sequence"] == 0
        logging.getLogger("x").warning("main step")
        assert startup_progress.read_progress(path)["sequence"] == 1
    finally:
        startup_progress.finish()
    final = startup_progress.read_progress(path)
    assert final["ready"] is True and final["pid"] == os.getpid()
    assert not any(
        isinstance(h, startup_progress.StartupProgressHandler)
        for h in logging.getLogger().handlers
    )


def test_no_supervisor_means_no_heartbeat(tmp_path, monkeypatch):
    monkeypatch.delenv(startup_progress.STARTUP_PROGRESS_FILE_ENV, raising=False)
    startup_progress.install()
    startup_progress.finish()
    assert list(tmp_path.iterdir()) == []


def test_unrelated_python_process_cannot_keep_a_watched_startup_alive(control):
    control.start(1, 0.1, 0, 0, CHILD_HANG="1")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    # Same interpreter and heartbeat schema, but a sibling rather than the
    # watched process's worker. It must not extend the watched stall deadline.
    script = (
        "from pathlib import Path; import sys,time; from jarvis.startup_progress import write_progress; p=Path(sys.argv[1]); "
        + "\nfor n in range(50): write_progress(p,n); time.sleep(.1)"
    )
    unrelated = subprocess.Popen(
        [sys._base_executable, "-c", script, str(control._progress_path)], env=env
    )
    try:
        with pytest.raises(RuntimeError, match="no startup progress"):
            control.wait_for_child_ready(timeout_seconds=2.0)
    finally:
        unrelated.kill()
        unrelated.wait(timeout=10)


@pytest.mark.parametrize("writer_pid", [-1, 0, 2**128])
def test_malformed_heartbeat_pid_is_ignored(control, writer_pid):
    assert not control._startup_writer_matches(
        {"pid": writer_pid}, psutil.Process(os.getpid())
    )
