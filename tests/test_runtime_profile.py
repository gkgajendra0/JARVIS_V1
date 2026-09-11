from __future__ import annotations

from jarvis.performance.runtime_profile import build_summary, metric_summary, percentile


def test_percentile_interpolates_middle_value() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.5


def test_metric_summary_ignores_missing_values() -> None:
    samples = [
        {"gpu_util_percent": None},
        {"gpu_util_percent": 5.0},
        {"gpu_util_percent": 15.0},
    ]

    summary = metric_summary(samples, "gpu_util_percent")

    assert summary is not None
    assert summary["mean"] == 10.0
    assert summary["median"] == 10.0
    assert summary["max"] == 15.0


def test_build_summary_keeps_phase_boundaries() -> None:
    samples = [
        {
            "phase": "idle_background",
            "process_cpu_raw_percent": 100.0,
            "process_cpu_task_manager_percent": 10.0,
            "system_cpu_percent": 20.0,
            "rss_mb": 100.0,
            "vms_mb": 200.0,
            "num_threads": 10,
            "child_process_count": 0,
            "num_handles": 20,
            "gpu_util_percent": 5.0,
            "gpu_memory_used_mb": 1000.0,
        },
        {
            "phase": "conversation",
            "process_cpu_raw_percent": 300.0,
            "process_cpu_task_manager_percent": 30.0,
            "system_cpu_percent": 50.0,
            "rss_mb": 120.0,
            "vms_mb": 220.0,
            "num_threads": 12,
            "child_process_count": 0,
            "num_handles": 22,
            "gpu_util_percent": 25.0,
            "gpu_memory_used_mb": 1200.0,
        },
    ]

    summary = build_summary(samples)

    assert summary["overall"]["process_cpu_task_manager_percent"]["median"] == 20.0
    assert (
        summary["by_phase"]["idle_background"]["gpu_util_percent"]["max"]
        == 5.0
    )
    assert (
        summary["by_phase"]["conversation"]["gpu_util_percent"]["max"]
        == 25.0
    )
