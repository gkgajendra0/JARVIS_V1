from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.model_routing.local_residency import (
    GpuResidencySnapshot,
    GpuResidencyState,
    LocalModelResidencyManager,
    LocalModelResourcePressure,
    LocalResidencyPolicy,
    NvidiaSmiResidencyProbe,
)


class MutableProbe:
    def __init__(self, snapshot: GpuResidencySnapshot | None) -> None:
        self.snapshot = snapshot

    def sample(self) -> GpuResidencySnapshot | None:
        return self.snapshot


def _snapshot(
    *,
    free_mib: int = 6000,
    used_mib: int = 1900,
    utilization: float = 10.0,
    captured: float = 1.0,
) -> GpuResidencySnapshot:
    return GpuResidencySnapshot(
        gpu_name="NVIDIA GeForce RTX 5060 Ti",
        total_mib=8151,
        used_mib=used_mib,
        free_mib=free_mib,
        utilization_percent=utilization,
        captured_at_monotonic=captured,
    )


def _policy(**changes: object) -> LocalResidencyPolicy:
    base = LocalResidencyPolicy(sample_interval_seconds=60.0)
    return replace(base, **changes)


def test_default_policy_preserves_measured_c5_headroom() -> None:
    policy = LocalResidencyPolicy()

    assert policy.min_free_to_load_mib == 5600
    assert policy.pressure_free_mib == 1800
    assert policy.hard_pressure_free_mib == 1200
    assert policy.max_util_to_load_percent == 45.0
    assert policy.pressure_util_percent == 80.0
    assert policy.recovery_free_mib == 5600
    assert policy.recovery_util_percent == 35.0
    assert policy.pressure_samples == 2
    assert policy.recovery_samples == 3


def test_cold_load_is_blocked_when_gpu_headroom_is_low() -> None:
    probe = MutableProbe(_snapshot(free_mib=4000, utilization=15.0))
    manager = LocalModelResidencyManager(
        policy=_policy(),
        probe=probe,
        unload_model=lambda _model: True,
    )
    try:
        with pytest.raises(LocalModelResourcePressure):
            manager.before_invocation("qwen3.5:4b")

        status = manager.status()
        assert status.state is GpuResidencyState.PRESSURE_BLOCKED
        assert status.last_reason == "insufficient_free_vram_for_cold_load"
    finally:
        manager.close()


def test_cold_load_is_blocked_when_gpu_is_already_busy() -> None:
    probe = MutableProbe(_snapshot(free_mib=6500, utilization=70.0))
    manager = LocalModelResidencyManager(
        policy=_policy(),
        probe=probe,
        unload_model=lambda _model: True,
    )
    try:
        with pytest.raises(LocalModelResourcePressure):
            manager.before_invocation("qwen3.5:4b")

        assert manager.status().last_reason == (
            "gpu_utilization_too_high_for_cold_load"
        )
    finally:
        manager.close()


def test_resident_model_is_evicted_after_sustained_pressure_then_recovers() -> None:
    probe = MutableProbe(_snapshot())
    unloaded: list[str] = []
    manager = LocalModelResidencyManager(
        policy=_policy(),
        probe=probe,
        unload_model=lambda model: unloaded.append(model) is None,
    )
    try:
        manager.before_invocation("qwen3.5:4b")
        manager.after_invocation("qwen3.5:4b", success=True)
        assert manager.status().state is GpuResidencyState.RESIDENT

        probe.snapshot = _snapshot(free_mib=1700, used_mib=6200, utilization=25.0)
        first = manager.poll_once()
        assert first.state is GpuResidencyState.RESIDENT
        assert first.pressure_sample_count == 1
        assert unloaded == []

        second = manager.poll_once()
        assert second.state is GpuResidencyState.PRESSURE_BLOCKED
        assert second.resident_model is None
        assert unloaded == ["qwen3.5:4b"]
        assert second.last_reason == "sustained_vram_pressure"

        probe.snapshot = _snapshot(free_mib=6000, utilization=10.0)
        assert manager.poll_once().state is GpuResidencyState.PRESSURE_BLOCKED
        assert manager.poll_once().state is GpuResidencyState.PRESSURE_BLOCKED
        recovered = manager.poll_once()
        assert recovered.state is GpuResidencyState.AVAILABLE
        assert recovered.last_reason == "gpu_pressure_recovered"
    finally:
        manager.close()


def test_hard_vram_pressure_evicts_on_one_sample() -> None:
    probe = MutableProbe(_snapshot())
    unloaded: list[str] = []
    manager = LocalModelResidencyManager(
        policy=_policy(),
        probe=probe,
        unload_model=lambda model: unloaded.append(model) is None,
    )
    try:
        manager.before_invocation("qwen3.5:4b")
        manager.after_invocation("qwen3.5:4b", success=True)

        probe.snapshot = _snapshot(free_mib=900, used_mib=7000, utilization=30.0)
        status = manager.poll_once()

        assert status.state is GpuResidencyState.PRESSURE_BLOCKED
        assert status.last_reason == "hard_vram_pressure"
        assert unloaded == ["qwen3.5:4b"]
    finally:
        manager.close()


def test_active_local_request_is_not_evicted_by_its_own_gpu_spike() -> None:
    probe = MutableProbe(_snapshot())
    unloaded: list[str] = []
    manager = LocalModelResidencyManager(
        policy=_policy(),
        probe=probe,
        unload_model=lambda model: unloaded.append(model) is None,
    )
    try:
        manager.before_invocation("qwen3.5:4b")
        manager.after_invocation("qwen3.5:4b", success=True)

        manager.before_invocation("qwen3.5:4b")
        probe.snapshot = _snapshot(free_mib=1000, used_mib=6900, utilization=99.0)

        status = manager.poll_once()

        assert status.state is GpuResidencyState.RESIDENT
        assert status.active_requests == 1
        assert unloaded == []

        manager.after_invocation("qwen3.5:4b", success=True)
    finally:
        manager.close()


def test_unavailable_gpu_probe_fails_closed_for_cold_load() -> None:
    manager = LocalModelResidencyManager(
        policy=_policy(),
        probe=MutableProbe(None),
        unload_model=lambda _model: True,
    )
    try:
        with pytest.raises(LocalModelResourcePressure):
            manager.before_invocation("qwen3.5:4b")

        assert manager.status().state is GpuResidencyState.UNAVAILABLE
        assert manager.status().last_reason == "gpu_snapshot_unavailable"
    finally:
        manager.close()


def test_nvidia_smi_probe_parses_free_memory_and_utilization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        returncode = 0
        stdout = "0, NVIDIA GeForce RTX 5060 Ti, 8151, 1963, 5929, 12\n"
        stderr = ""

    monkeypatch.setattr(
        "jarvis.model_routing.local_residency.subprocess.run",
        lambda *args, **kwargs: Result(),
    )
    probe = NvidiaSmiResidencyProbe(
        executable="nvidia-smi",
        clock=lambda: 123.0,
    )

    snapshot = probe.sample()

    assert snapshot == GpuResidencySnapshot(
        gpu_name="NVIDIA GeForce RTX 5060 Ti",
        total_mib=8151,
        used_mib=1963,
        free_mib=5929,
        utilization_percent=12.0,
        captured_at_monotonic=123.0,
    )
