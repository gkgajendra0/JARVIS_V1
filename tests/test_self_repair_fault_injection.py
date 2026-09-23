from __future__ import annotations

import pytest

from jarvis.self_repair import fault_injection as faults


def _snapshot(
    pid: int,
    *,
    runtime: bool = True,
    supervised: bool = True,
    create_time: float = 100.0,
) -> faults.ProcessSnapshot:
    return faults.ProcessSnapshot(
        pid=pid,
        create_time=create_time,
        cmdline=(
            ("python", "-m", "jarvis.voice.production_runtime")
            if runtime
            else ("python", "-m", "other.module")
        ),
        parent_pid=1,
        parent_cmdline=(
            ("python", "jarvis-dev")
            if supervised
            else ("python", "unrelated-parent")
        ),
    )


def test_select_supervised_runtime_requires_exactly_one_target() -> None:
    selected = faults.select_supervised_runtime(
        (
            _snapshot(10, runtime=False),
            _snapshot(20, supervised=False),
            _snapshot(30),
        )
    )

    assert selected.pid == 30


def test_select_supervised_runtime_refuses_unsupervised_process() -> None:
    with pytest.raises(RuntimeError, match="no production runtime"):
        faults.select_supervised_runtime((_snapshot(20, supervised=False),))


def test_select_supervised_runtime_refuses_ambiguous_targets() -> None:
    with pytest.raises(RuntimeError, match="multiple supervised runtimes"):
        faults.select_supervised_runtime((_snapshot(30), _snapshot(31)))


@pytest.mark.parametrize(
    ("kind", "method_name"),
    (
        (faults.FaultKind.CRASH, "kill"),
        (faults.FaultKind.HANG, "suspend"),
        (faults.FaultKind.RESUME, "resume"),
    ),
)
def test_inject_fault_only_invokes_requested_process_action(
    monkeypatch: pytest.MonkeyPatch,
    kind: faults.FaultKind,
    method_name: str,
) -> None:
    calls: list[str] = []

    class FakeProcess:
        def create_time(self) -> float:
            return 100.0

        def kill(self) -> None:
            calls.append("kill")

        def suspend(self) -> None:
            calls.append("suspend")

        def resume(self) -> None:
            calls.append("resume")

    monkeypatch.setattr(faults.psutil, "Process", lambda pid: FakeProcess())

    faults.inject_fault(kind, _snapshot(30))

    assert calls == [method_name]


def test_inject_fault_revalidates_process_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReusedPid:
        def create_time(self) -> float:
            return 200.0

    monkeypatch.setattr(faults.psutil, "Process", lambda pid: ReusedPid())

    with pytest.raises(RuntimeError, match="identity changed"):
        faults.inject_fault(faults.FaultKind.CRASH, _snapshot(30))
