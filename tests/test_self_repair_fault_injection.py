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
            ("python", "jarvis-dev") if supervised else ("python", "unrelated-parent")
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
    ("kind", "method_name", "expected_order"),
    (
        (faults.FaultKind.CRASH, "kill", (31, 32, 30)),
        (faults.FaultKind.HANG, "suspend", (31, 32, 30)),
        (faults.FaultKind.RESUME, "resume", (30, 32, 31)),
    ),
)
def test_inject_fault_targets_only_supervised_runtime_tree(
    monkeypatch: pytest.MonkeyPatch,
    kind: faults.FaultKind,
    method_name: str,
    expected_order: tuple[int, ...],
) -> None:
    calls: list[tuple[str, int]] = []

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def create_time(self) -> float:
            return 100.0

        def children(self, *, recursive: bool) -> list[FakeProcess]:
            assert recursive is True
            return [FakeProcess(31), FakeProcess(32)] if self.pid == 30 else []

        def kill(self) -> None:
            calls.append(("kill", self.pid))

        def suspend(self) -> None:
            calls.append(("suspend", self.pid))

        def resume(self) -> None:
            calls.append(("resume", self.pid))

    monkeypatch.setattr(faults.psutil, "Process", FakeProcess)

    affected = faults.inject_fault(kind, _snapshot(30))

    assert affected == 3
    assert calls == [(method_name, pid) for pid in expected_order]


def test_inject_fault_revalidates_process_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReusedPid:
        def create_time(self) -> float:
            return 200.0

        def children(self, *, recursive: bool) -> list[object]:
            return []

    monkeypatch.setattr(faults.psutil, "Process", lambda pid: ReusedPid())

    with pytest.raises(RuntimeError, match="identity changed"):
        faults.inject_fault(faults.FaultKind.CRASH, _snapshot(30))


def test_partial_hang_rolls_back_already_suspended_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def create_time(self) -> float:
            return 100.0

        def children(self, *, recursive: bool) -> list[FakeProcess]:
            assert recursive is True
            return [FakeProcess(31), FakeProcess(32)] if self.pid == 30 else []

        def suspend(self) -> None:
            calls.append(("suspend", self.pid))
            if self.pid == 32:
                raise faults.psutil.AccessDenied(self.pid)

        def resume(self) -> None:
            calls.append(("resume", self.pid))

    monkeypatch.setattr(faults.psutil, "Process", FakeProcess)

    with pytest.raises(faults.psutil.AccessDenied):
        faults.inject_fault(faults.FaultKind.HANG, _snapshot(30))

    assert calls == [
        ("suspend", 31),
        ("suspend", 32),
        ("resume", 31),
    ]
