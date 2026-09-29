"""Resource-aware residency control for bounded local model targets.

The default thresholds are calibrated from the accepted C5 owner-machine
coexistence evidence on the RTX 5060 Ti 8 GB host:

- normal JARVIS baseline: ~1.96 GiB GPU memory used;
- JARVIS + resident Qwen3.5:4B conversation: ~5.88 GiB used;
- resident local-model increment: ~3.9 GiB;
- normal coexistence GPU utilization p95: ~13.4%.

The controller is deliberately conservative. It prevents a cold local load when
headroom is already low, keeps an admitted model warm while resources are calm,
and evicts it after sustained pressure. Recovery requires multiple calm samples
so a game or other GPU-heavy workload does not cause load/unload thrashing.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class GpuResidencyState(StrEnum):
    AVAILABLE = "available"
    RESIDENT = "resident"
    PRESSURE_BLOCKED = "pressure_blocked"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GpuResidencySnapshot:
    gpu_name: str
    total_mib: int
    used_mib: int
    free_mib: int
    utilization_percent: float
    captured_at_monotonic: float

    def __post_init__(self) -> None:
        for name in ("total_mib", "used_mib", "free_mib"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.total_mib <= 0:
            raise ValueError("total_mib must be positive")
        if not 0 <= float(self.utilization_percent) <= 100:
            raise ValueError("utilization_percent must be between 0 and 100")
        if float(self.captured_at_monotonic) < 0:
            raise ValueError("captured_at_monotonic must not be negative")
        if not str(self.gpu_name).strip():
            raise ValueError("gpu_name must not be empty")


@dataclass(frozen=True, slots=True)
class LocalResidencyPolicy:
    min_free_to_load_mib: int = 5600
    max_util_to_load_percent: float = 45.0
    pressure_free_mib: int = 1800
    hard_pressure_free_mib: int = 1200
    pressure_util_percent: float = 80.0
    recovery_free_mib: int = 5600
    recovery_util_percent: float = 35.0
    pressure_samples: int = 2
    recovery_samples: int = 3
    sample_interval_seconds: float = 2.0
    resident_assumption_seconds: float = 240.0

    def __post_init__(self) -> None:
        integer_fields = (
            "min_free_to_load_mib",
            "pressure_free_mib",
            "hard_pressure_free_mib",
            "recovery_free_mib",
            "pressure_samples",
            "recovery_samples",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        for name in (
            "max_util_to_load_percent",
            "pressure_util_percent",
            "recovery_util_percent",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")

        if self.hard_pressure_free_mib > self.pressure_free_mib:
            raise ValueError(
                "hard_pressure_free_mib must not exceed pressure_free_mib"
            )
        if self.pressure_free_mib >= self.min_free_to_load_mib:
            raise ValueError(
                "pressure_free_mib must be below min_free_to_load_mib"
            )
        if self.recovery_free_mib < self.min_free_to_load_mib:
            raise ValueError(
                "recovery_free_mib must be at least min_free_to_load_mib"
            )
        if self.recovery_util_percent > self.max_util_to_load_percent:
            raise ValueError(
                "recovery_util_percent must not exceed max_util_to_load_percent"
            )
        if self.pressure_util_percent <= self.max_util_to_load_percent:
            raise ValueError(
                "pressure_util_percent must exceed max_util_to_load_percent"
            )
        if float(self.sample_interval_seconds) <= 0:
            raise ValueError("sample_interval_seconds must be positive")
        if float(self.resident_assumption_seconds) <= 0:
            raise ValueError("resident_assumption_seconds must be positive")


@dataclass(frozen=True, slots=True)
class LocalResidencyStatus:
    state: GpuResidencyState
    active_requests: int
    resident_model: str | None
    pressure_sample_count: int
    recovery_sample_count: int
    last_reason: str | None
    snapshot: GpuResidencySnapshot | None


class GpuResidencyProbe(Protocol):
    def sample(self) -> GpuResidencySnapshot | None: ...


class LocalModelResourcePressure(RuntimeError):
    """Local GPU admission failed; callers may use an approved fallback."""

    status_code = 503
    retryable = True
    local_resource_pressure = True


class NvidiaSmiResidencyProbe:
    """Sample one NVIDIA GPU through the already-installed nvidia-smi CLI."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        gpu_index: int = 0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        resolved = executable or shutil.which("nvidia-smi")
        self._executable = resolved
        self._gpu_index = int(gpu_index)
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._executable is not None

    def sample(self) -> GpuResidencySnapshot | None:
        if self._executable is None:
            return None
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                [
                    self._executable,
                    (
                        "--query-gpu=index,name,memory.total,memory.used,"
                        "memory.free,utilization.gpu"
                    ),
                    "--format=csv,noheader,nounits",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None

        for row in result.stdout.splitlines():
            fields = [field.strip() for field in row.split(",")]
            if len(fields) != 6:
                continue
            try:
                index = int(fields[0])
                if index != self._gpu_index:
                    continue
                return GpuResidencySnapshot(
                    gpu_name=fields[1],
                    total_mib=int(fields[2]),
                    used_mib=int(fields[3]),
                    free_mib=int(fields[4]),
                    utilization_percent=float(fields[5]),
                    captured_at_monotonic=float(self._clock()),
                )
            except ValueError:
                continue
        return None


UnloadModel = Callable[[str], bool]


class LocalModelResidencyManager:
    """Bound local-model residency around deterministic GPU resource facts."""

    def __init__(
        self,
        *,
        policy: LocalResidencyPolicy | None = None,
        probe: GpuResidencyProbe | None = None,
        unload_model: UnloadModel,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(unload_model):
            raise TypeError("unload_model must be callable")
        self.policy = policy or LocalResidencyPolicy()
        self._probe = probe or NvidiaSmiResidencyProbe(clock=clock)
        self._unload_model = unload_model
        self._clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = GpuResidencyState.AVAILABLE
        self._active_requests = 0
        self._resident_model: str | None = None
        self._resident_last_used_at: float | None = None
        self._pressure_count = 0
        self._recovery_count = 0
        self._last_reason: str | None = None
        self._last_snapshot: GpuResidencySnapshot | None = None

    def status(self) -> LocalResidencyStatus:
        with self._lock:
            self._expire_residency_locked(now=float(self._clock()))
            return LocalResidencyStatus(
                state=self._state,
                active_requests=self._active_requests,
                resident_model=self._resident_model,
                pressure_sample_count=self._pressure_count,
                recovery_sample_count=self._recovery_count,
                last_reason=self._last_reason,
                snapshot=self._last_snapshot,
            )

    def before_invocation(self, model: str) -> GpuResidencySnapshot:
        normalized_model = str(model).strip()
        if not normalized_model:
            raise ValueError("model must not be empty")

        snapshot = self._probe.sample()
        with self._lock:
            self._last_snapshot = snapshot
            self._expire_residency_locked(now=float(self._clock()))

            if snapshot is None:
                self._state = GpuResidencyState.UNAVAILABLE
                self._last_reason = "gpu_snapshot_unavailable"
                raise LocalModelResourcePressure(
                    "local GPU state is unavailable; local model load is blocked"
                )

            if self._state is GpuResidencyState.PRESSURE_BLOCKED:
                self._observe_recovery_locked(snapshot)
                if self._state is GpuResidencyState.PRESSURE_BLOCKED:
                    raise LocalModelResourcePressure(
                        "local GPU remains pressure-blocked"
                    )
            elif self._state is GpuResidencyState.UNAVAILABLE:
                if self._load_safe(snapshot):
                    self._state = GpuResidencyState.AVAILABLE
                    self._last_reason = "gpu_snapshot_recovered"
                else:
                    self._state = GpuResidencyState.PRESSURE_BLOCKED
                    self._last_reason = "gpu_recovered_under_pressure"
                    self._recovery_count = 0
                    raise LocalModelResourcePressure(
                        "local GPU recovered but lacks safe local-model headroom"
                    )

            already_resident = self._resident_model == normalized_model
            if not already_resident and not self._load_safe(snapshot):
                self._state = GpuResidencyState.PRESSURE_BLOCKED
                self._last_reason = self._load_block_reason(snapshot)
                self._recovery_count = 0
                raise LocalModelResourcePressure(
                    "local GPU does not have safe headroom for a cold model load"
                )

            self._active_requests += 1
            self._pressure_count = 0
            self._ensure_monitor_locked()
            return snapshot

    def after_invocation(self, model: str, *, success: bool) -> None:
        normalized_model = str(model).strip()
        if not normalized_model:
            raise ValueError("model must not be empty")
        with self._lock:
            if self._active_requests <= 0:
                raise RuntimeError("residency request counter underflow")
            self._active_requests -= 1
            if success:
                self._resident_model = normalized_model
                self._resident_last_used_at = float(self._clock())
                self._state = GpuResidencyState.RESIDENT
                self._last_reason = "local_model_resident"
            elif self._resident_model is None:
                self._state = GpuResidencyState.AVAILABLE
                self._last_reason = "local_invocation_failed_before_residency"

    def force_unload(self, *, reason: str = "explicit_unload") -> bool:
        with self._lock:
            model = self._resident_model
            if model is None:
                return True
            if self._active_requests:
                return False
            self._resident_model = None
            self._resident_last_used_at = None
            self._state = GpuResidencyState.PRESSURE_BLOCKED
            self._pressure_count = 0
            self._recovery_count = 0
            self._last_reason = str(reason).strip() or "explicit_unload"

        ok = bool(self._unload_model(model))
        if not ok:
            with self._lock:
                self._state = GpuResidencyState.UNAVAILABLE
                self._last_reason = "local_model_unload_failed"
        return ok

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.policy.sample_interval_seconds * 2))

    def _ensure_monitor_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="jarvis-local-model-residency",
            daemon=True,
        )
        self._thread.start()

    def poll_once(self) -> LocalResidencyStatus:
        """Sample GPU state once and apply eviction/recovery policy."""

        snapshot = self._probe.sample()
        model_to_unload: str | None = None
        with self._lock:
            self._last_snapshot = snapshot
            self._expire_residency_locked(now=float(self._clock()))

            if snapshot is None:
                if self._resident_model is None:
                    self._state = GpuResidencyState.UNAVAILABLE
                    self._last_reason = "gpu_snapshot_unavailable"
            elif self._state is GpuResidencyState.PRESSURE_BLOCKED:
                self._observe_recovery_locked(snapshot)
            elif self._state is GpuResidencyState.UNAVAILABLE:
                if self._load_safe(snapshot):
                    self._state = GpuResidencyState.AVAILABLE
                    self._last_reason = "gpu_snapshot_recovered"
            elif self._resident_model is not None and not self._active_requests:
                hard_pressure = (
                    snapshot.free_mib <= self.policy.hard_pressure_free_mib
                )
                pressure = self._pressure(snapshot)
                if hard_pressure:
                    self._pressure_count = self.policy.pressure_samples
                elif pressure:
                    self._pressure_count += 1
                else:
                    self._pressure_count = 0

                if self._pressure_count >= self.policy.pressure_samples:
                    model_to_unload = self._resident_model
                    self._resident_model = None
                    self._resident_last_used_at = None
                    self._state = GpuResidencyState.PRESSURE_BLOCKED
                    self._recovery_count = 0
                    self._last_reason = self._pressure_reason(snapshot)

        if model_to_unload is not None:
            ok = bool(self._unload_model(model_to_unload))
            if not ok:
                with self._lock:
                    self._state = GpuResidencyState.UNAVAILABLE
                    self._last_reason = "local_model_unload_failed"
        return self.status()

    def _monitor_loop(self) -> None:
        while not self._stop.wait(self.policy.sample_interval_seconds):
            self.poll_once()

    def _expire_residency_locked(self, *, now: float) -> None:
        if self._resident_model is None or self._resident_last_used_at is None:
            return
        if now - self._resident_last_used_at < self.policy.resident_assumption_seconds:
            return
        if self._active_requests:
            return
        self._resident_model = None
        self._resident_last_used_at = None
        if self._state is GpuResidencyState.RESIDENT:
            self._state = GpuResidencyState.AVAILABLE
            self._last_reason = "residency_assumption_expired"

    def _load_safe(self, snapshot: GpuResidencySnapshot) -> bool:
        return (
            snapshot.free_mib >= self.policy.min_free_to_load_mib
            and snapshot.utilization_percent
            <= self.policy.max_util_to_load_percent
        )

    def _pressure(self, snapshot: GpuResidencySnapshot) -> bool:
        return (
            snapshot.free_mib <= self.policy.pressure_free_mib
            or snapshot.utilization_percent
            >= self.policy.pressure_util_percent
        )

    def _recovery_safe(self, snapshot: GpuResidencySnapshot) -> bool:
        return (
            snapshot.free_mib >= self.policy.recovery_free_mib
            and snapshot.utilization_percent
            <= self.policy.recovery_util_percent
        )

    def _observe_recovery_locked(self, snapshot: GpuResidencySnapshot) -> None:
        if not self._recovery_safe(snapshot):
            self._recovery_count = 0
            return
        self._recovery_count += 1
        if self._recovery_count < self.policy.recovery_samples:
            return
        self._recovery_count = 0
        self._pressure_count = 0
        self._state = GpuResidencyState.AVAILABLE
        self._last_reason = "gpu_pressure_recovered"

    def _load_block_reason(self, snapshot: GpuResidencySnapshot) -> str:
        if snapshot.free_mib < self.policy.min_free_to_load_mib:
            return "insufficient_free_vram_for_cold_load"
        return "gpu_utilization_too_high_for_cold_load"

    def _pressure_reason(self, snapshot: GpuResidencySnapshot) -> str:
        if snapshot.free_mib <= self.policy.hard_pressure_free_mib:
            return "hard_vram_pressure"
        if snapshot.free_mib <= self.policy.pressure_free_mib:
            return "sustained_vram_pressure"
        return "sustained_gpu_utilization_pressure"
