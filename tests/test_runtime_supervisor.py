from __future__ import annotations

from jarvis import runtime_supervisor
from jarvis.dev_supervisor import DevSupervisorConfig


def test_runtime_supervisor_branch_override_preserves_local_only_mode(
    monkeypatch,
) -> None:
    captured: list[DevSupervisorConfig] = []

    monkeypatch.setattr(
        runtime_supervisor,
        "_runtime_supervisor_config_from_environment",
        lambda: DevSupervisorConfig(branch="main", git_updates_enabled=False),
    )

    def fake_run(config: DevSupervisorConfig) -> int:
        captured.append(config)
        return 0

    monkeypatch.setattr(runtime_supervisor, "run_supervisor", fake_run)

    assert runtime_supervisor.main(["--branch", "feature/hardening"]) == 0
    assert captured == [
        DevSupervisorConfig(
            branch="feature/hardening",
            git_updates_enabled=False,
        )
    ]
