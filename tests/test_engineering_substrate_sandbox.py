from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.engineering_substrate import (
    SandboxMountBinding,
    SandboxPolicyError,
    SandboxResourceUnavailable,
    default_sandbox_registry,
)


def test_default_sandbox_profiles_are_exact_and_hardened(tmp_path: Path) -> None:
    registry = default_sandbox_registry(
        docker_executable="/usr/bin/docker",
        protected_main_root=tmp_path / "main",
    )

    profiles = {item.profile.profile_id: item.profile for item in registry.all()}

    assert set(profiles) == {
        "test.offline.v1",
        "dependency.acquire.v1",
        "dependency.verify.v1",
    }
    assert profiles["test.offline.v1"].network_mode.value == "none"
    assert profiles["dependency.verify.v1"].network_mode.value == "none"
    assert profiles["dependency.acquire.v1"].network_mode.value == "registered_sources"
    assert all(item.no_new_privileges for item in profiles.values())
    assert all(item.dropped_capabilities == ("all",) for item in profiles.values())


def test_offline_pytest_command_uses_only_registered_security_switches(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = default_sandbox_registry(docker_executable="/usr/bin/docker")

    launch = registry.build_launch(
        profile_id="test.offline.v1",
        image="jarvis-tests:locked",
        mounts=(SandboxMountBinding("workspace_ro", workspace),),
        trusted_suffix=("tests/test_example.py",),
        requested_timeout_seconds=45,
    )

    command = list(launch.command)
    assert command[0] == "/usr/bin/docker"
    assert command[1:3] == ["run", "--rm"]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in command
    assert command[command.index("--pids-limit") + 1] == "128"
    assert "type=bind" in command[command.index("--mount") + 1]
    assert "readonly" in command[command.index("--mount") + 1]
    assert "/var/run/docker.sock" not in " ".join(command)
    image_index = command.index("jarvis-tests:locked")
    assert command[image_index + 1 : image_index + 7] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    assert command[-1] == "tests/test_example.py"
    assert launch.timeout_seconds == 45


def test_dependency_profiles_build_fixed_commands_without_runtime_suffix(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    worktree = tmp_path / "worktree"
    artifacts = tmp_path / "artifacts"
    candidate = tmp_path / "candidate"
    for path in (staging, worktree, artifacts, candidate):
        path.mkdir()

    registry = default_sandbox_registry(docker_executable="docker")

    acquire = registry.build_launch(
        profile_id="dependency.acquire.v1",
        image="jarvis-dependency:locked",
        mounts=(
            SandboxMountBinding("staging_rw", staging),
            SandboxMountBinding("worktree_ro", worktree),
        ),
    )
    verify = registry.build_launch(
        profile_id="dependency.verify.v1",
        image="jarvis-dependency:locked",
        mounts=(
            SandboxMountBinding("artifacts_ro", artifacts),
            SandboxMountBinding("candidate_rw", candidate),
            SandboxMountBinding("worktree_ro", worktree),
        ),
    )

    acquire_command = list(acquire.command)
    verify_command = list(verify.command)
    assert acquire_command[acquire_command.index("--network") + 1] == "bridge"
    assert verify_command[verify_command.index("--network") + 1] == "none"
    assert acquire_command[-2:] == [
        "jarvis.engineering_substrate.dependency.worker",
        "acquire",
    ]
    assert verify_command[-3:] == (
        "uv",
        "--cache-dir",
        "/candidate/.uv-cache",
    )

    verify_sync = registry.build_launch(
        profile_id="dependency.verify.v1",
        image="jarvis-dependency:locked",
        mounts=(
            SandboxMountBinding("artifacts_ro", artifacts),
            SandboxMountBinding("candidate_rw", candidate),
            SandboxMountBinding("worktree_ro", worktree),
        ),
        trusted_suffix=(
            "pip",
            "sync",
            "/artifacts/pylock.toml",
            "--python",
            "/candidate/.venv/bin/python",
            "--offline",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--no-config",
            "--no-python-downloads",
            "--no-progress",
        ),
    )
    assert verify_sync.command[-16:] == (
        "uv",
        "--cache-dir",
        "/candidate/.uv-cache",
        "pip",
        "sync",
        "/artifacts/pylock.toml",
        "--python",
        "/candidate/.venv/bin/python",
        "--offline",
        "--require-hashes",
        "--only-binary",
        ":all:",
        "--no-config",
        "--no-python-downloads",
        "--no-progress",
    )

    with pytest.raises(SandboxPolicyError, match="runtime command suffix"):
        registry.build_launch(
            profile_id="dependency.acquire.v1",
            image="jarvis-dependency:locked",
            mounts=(
                SandboxMountBinding("staging_rw", staging),
                SandboxMountBinding("worktree_ro", worktree),
            ),
            trusted_suffix=("--unsafe",),
        )


def test_dependency_verify_rejects_unregistered_uv_operation(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    candidate = tmp_path / "candidate"
    worktree = tmp_path / "worktree"
    for path in (artifacts, candidate, worktree):
        path.mkdir()
    registry = default_sandbox_registry(docker_executable="docker")

    with pytest.raises(SandboxPolicyError, match="not registered"):
        registry.build_launch(
            profile_id="dependency.verify.v1",
            image="jarvis-dependency:locked",
            mounts=(
                SandboxMountBinding("artifacts_ro", artifacts),
                SandboxMountBinding("candidate_rw", candidate),
                SandboxMountBinding("worktree_ro", worktree),
            ),
            trusted_suffix=("pip", "install", "anything"),
        )


def test_sandbox_rejects_mount_policy_drift_and_protected_main_write(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "main"
    protected.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    registry = default_sandbox_registry(
        docker_executable="docker",
        protected_main_root=protected,
    )

    with pytest.raises(SandboxPolicyError, match="exactly match"):
        registry.build_launch(
            profile_id="dependency.acquire.v1",
            image="jarvis-dependency:locked",
            mounts=(SandboxMountBinding("worktree_ro", worktree),),
        )

    with pytest.raises(SandboxPolicyError, match="protected main"):
        registry.build_launch(
            profile_id="dependency.acquire.v1",
            image="jarvis-dependency:locked",
            mounts=(
                SandboxMountBinding("staging_rw", protected),
                SandboxMountBinding("worktree_ro", worktree),
            ),
        )


def test_sandbox_rejects_symlink_and_docker_socket_mounts(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    registry = default_sandbox_registry(docker_executable="docker")
    with pytest.raises(SandboxPolicyError, match="symlink"):
        registry.build_launch(
            profile_id="test.offline.v1",
            image="jarvis-tests:locked",
            mounts=(SandboxMountBinding("workspace_ro", link),),
        )

    docker_sock = tmp_path / "docker.sock"
    docker_sock.write_text("not-a-real-socket", encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="Docker socket"):
        registry.build_launch(
            profile_id="test.offline.v1",
            image="jarvis-tests:locked",
            mounts=(SandboxMountBinding("workspace_ro", docker_sock),),
        )


def test_sandbox_unavailable_docker_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "jarvis.engineering_substrate.sandbox.shutil.which",
        lambda name: None,
    )
    registry = default_sandbox_registry()

    with pytest.raises(SandboxResourceUnavailable, match="cannot fall back"):
        registry.build_launch(
            profile_id="test.offline.v1",
            image="jarvis-tests:locked",
            mounts=(SandboxMountBinding("workspace_ro", Path.cwd()),),
        )


def test_pytest_target_cannot_become_docker_or_pytest_option(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = default_sandbox_registry(docker_executable="docker")

    for target in ("../outside.py", "--collect-only", "/absolute/test.py"):
        with pytest.raises(SandboxPolicyError, match="relative non-option"):
            registry.build_launch(
                profile_id="test.offline.v1",
                image="jarvis-tests:locked",
                mounts=(SandboxMountBinding("workspace_ro", workspace),),
                trusted_suffix=(target,),
            )
