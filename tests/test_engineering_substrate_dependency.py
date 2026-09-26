from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from jarvis.engineering_substrate import ArtifactStore
from jarvis.engineering_substrate.contracts import (
    DependencyEcosystem,
    DependencyRequirement,
)
from jarvis.engineering_substrate.dependency import (
    PYPI_PUBLIC_V1,
    UV_WINDOWS_X64_0_12_19,
    DependencyBroker,
    DependencyPolicyError,
    DependencyResourceUnavailable,
    DependencySourcePolicy,
    DependencySourceRegistry,
    LockedWheelFetcher,
    PythonResolutionEnvironment,
    UvAdapter,
    UvBinaryRegistration,
    default_dependency_source_registry,
    inspect_pylock,
    normalize_python_package_name,
)

WHEEL_BYTES = b"phase5c-wheel-payload"
WHEEL_SHA = hashlib.sha256(WHEEL_BYTES).hexdigest()


def _requirement(**overrides: object) -> DependencyRequirement:
    values: dict[str, object] = {
        "requirement_id": "req-1",
        "ecosystem": DependencyEcosystem.PYTHON,
        "package_name": "Demo_Package",
        "version_constraint": "==1.2.3",
        "purpose": "phase5c-test",
        "registered_source_ids": ("pypi.public.v1",),
        "change_id": "change-1",
        "work_id": "work-1",
    }
    values.update(overrides)
    return DependencyRequirement(**values)  # type: ignore[arg-type]


def _pylock_text(*, with_wheel: bool = True, index: str = "https://pypi.org/simple") -> str:
    wheel = ""
    if with_wheel:
        wheel = f"""
[[packages.wheels]]
name = "demo_package-1.2.3-py3-none-any.whl"
url = "https://files.pythonhosted.org/packages/demo/demo_package-1.2.3-py3-none-any.whl"
size = {len(WHEEL_BYTES)}
hashes = {{sha256 = "{WHEEL_SHA}"}}
"""
    return f"""lock-version = "1.0"
created-by = "uv 0.12.19"

[[packages]]
name = "demo_package"
version = "1.2.3"
index = "{index}"
dependencies = []
{wheel}
"""


class RecordingUvRunner:
    def __init__(self, lock_text: str) -> None:
        self.lock_text = lock_text
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        argv = [str(item) for item in command]
        self.calls.append(argv)
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "uv 0.12.19\n", "")
        output_index = argv.index("--output-file") + 1
        Path(argv[output_index]).write_text(self.lock_text, encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")


class FixtureWheelFetcher(LockedWheelFetcher):
    def fetch(self, wheel, *, source, destination_dir):
        assert source.source_id == "pypi.public.v1"
        assert wheel.sha256 == WHEEL_SHA
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / "locked-wheel.tmp"
        path.write_bytes(WHEEL_BYTES)
        return path


def _adapter(tmp_path: Path, runner: RecordingUvRunner) -> UvAdapter:
    executable = tmp_path / "uv.exe"
    executable.write_bytes(b"reviewed-uv-executable")
    executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    policy = UV_WINDOWS_X64_0_12_19
    registration = UvBinaryRegistration(
        executable_path=executable,
        version=policy.version,
        executable_sha256=executable_sha,
        release_commit_sha=policy.release_commit_sha,
        release_asset_sha256=policy.release_asset_sha256,
        release_policy_digest=policy.policy_digest,
    )
    return UvAdapter(
        release_policy=policy,
        binary_registration=registration,
        runner=runner,
    )


def test_python_package_name_uses_pep503_normalization() -> None:
    assert normalize_python_package_name("Demo_Package.Name") == "demo-package-name"


def test_public_source_policy_requires_https_and_known_artifact_host() -> None:
    assert PYPI_PUBLIC_V1.permits_artifact_url(
        "https://files.pythonhosted.org/packages/a/demo.whl"
    )
    assert not PYPI_PUBLIC_V1.permits_artifact_url(
        "https://example.invalid/demo.whl"
    )

    with pytest.raises(DependencyPolicyError, match="HTTPS"):
        DependencySourcePolicy(
            source_id="bad",
            index_url="http://pypi.org/simple",
            allowed_artifact_hosts=("files.pythonhosted.org",),
        )


def test_uv_adapter_builds_fixed_wheel_only_single_index_command(tmp_path: Path) -> None:
    runner = RecordingUvRunner(_pylock_text())
    adapter = _adapter(tmp_path, runner)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    requirement_file = workspace / "requirements.in"
    requirement_file.write_text("demo-package==1.2.3\n", encoding="utf-8")

    command = adapter.build_compile_command(
        workspace=workspace,
        requirement_file=requirement_file,
        output_lock=workspace / "pylock.toml",
        source=PYPI_PUBLIC_V1,
        environment=PythonResolutionEnvironment(
            python_version="3.11",
            python_platform="x86_64-pc-windows-msvc",
        ),
    )

    assert command[1:3] == ("pip", "compile")
    assert "--only-binary" in command
    assert command[command.index("--only-binary") + 1] == ":all:"
    assert "--no-build" in command
    assert "--no-config" in command
    assert "--no-python-downloads" in command
    assert "--default-index" in command
    assert command[command.index("--default-index") + 1] == "https://pypi.org/simple"
    assert "--index-strategy" in command
    assert command[command.index("--index-strategy") + 1] == "first-index"
    assert "--trusted-host" not in command
    assert "--allow-insecure-host" not in command
    assert "--index" not in command
    assert "--extra-index-url" not in command


def test_uv_binary_identity_fails_closed_on_digest_or_version_drift(
    tmp_path: Path,
) -> None:
    runner = RecordingUvRunner(_pylock_text())
    adapter = _adapter(tmp_path, runner)
    adapter.verify_trust()

    adapter.binary_registration.executable_path.write_bytes(b"tampered")
    with pytest.raises(DependencyResourceUnavailable, match="SHA-256"):
        adapter.verify_trust()


def test_missing_uv_is_a_resource_blocker(tmp_path: Path) -> None:
    runner = RecordingUvRunner(_pylock_text())
    policy = UV_WINDOWS_X64_0_12_19
    registration = UvBinaryRegistration(
        executable_path=tmp_path / "missing-uv.exe",
        version=policy.version,
        executable_sha256="a" * 64,
        release_commit_sha=policy.release_commit_sha,
        release_asset_sha256=policy.release_asset_sha256,
        release_policy_digest=policy.policy_digest,
    )
    adapter = UvAdapter(
        release_policy=policy,
        binary_registration=registration,
        runner=runner,
    )
    with pytest.raises(DependencyResourceUnavailable, match="missing"):
        adapter.verify_trust()


def test_pylock_rejects_non_wheel_or_wrong_source(tmp_path: Path) -> None:
    no_wheel = tmp_path / "pylock-no-wheel.toml"
    no_wheel.write_text(_pylock_text(with_wheel=False), encoding="utf-8")
    with pytest.raises(DependencyPolicyError, match="no locked wheel"):
        inspect_pylock(no_wheel, source=PYPI_PUBLIC_V1)

    wrong_source = tmp_path / "pylock-wrong-source.toml"
    wrong_source.write_text(
        _pylock_text(index="https://private.example/simple"),
        encoding="utf-8",
    )
    with pytest.raises(DependencyPolicyError, match="registered source"):
        inspect_pylock(wrong_source, source=PYPI_PUBLIC_V1)


def test_broker_resolves_and_acquires_only_locked_wheels(tmp_path: Path) -> None:
    runner = RecordingUvRunner(_pylock_text())
    adapter = _adapter(tmp_path, runner)
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    artifact_store = ArtifactStore(tmp_path / "artifact-store")
    broker = DependencyBroker(
        source_registry=default_dependency_source_registry(),
        uv_adapter=adapter,
        artifact_store=artifact_store,
        wheel_fetcher=FixtureWheelFetcher(),
        protected_main_root=tmp_path / "protected-main",
    )

    resolved = broker.resolve_python(
        _requirement(),
        workspace=workspace,
        environment=PythonResolutionEnvironment(
            python_version="3.11",
            python_platform="x86_64-pc-windows-msvc",
        ),
    )
    artifacts = broker.acquire_locked_wheels(
        resolved,
        staging_dir=tmp_path / "staging",
    )

    assert resolved.requirement.package_name == "demo-package"
    assert resolved.resolution.resolver_version == "0.12.19"
    assert resolved.resolution.lock_format == "pylock.toml"
    assert resolved.resolution.resolved_packages == ("demo-package==1.2.3",)
    assert resolved.resolution.artifact_ids == (WHEEL_SHA,)
    assert len(artifacts) == 1
    assert artifacts[0].sha256 == WHEEL_SHA
    assert artifact_store.read_bytes(WHEEL_SHA) == WHEEL_BYTES


def test_broker_denies_source_mixing_and_direct_or_vcs_inputs(tmp_path: Path) -> None:
    runner = RecordingUvRunner(_pylock_text())
    adapter = _adapter(tmp_path, runner)
    store = ArtifactStore(tmp_path / "artifact-store")
    registry = DependencySourceRegistry(
        (
            PYPI_PUBLIC_V1,
            DependencySourcePolicy(
                source_id="private.v1",
                index_url="https://packages.example/simple",
                allowed_artifact_hosts=("packages.example",),
                required_secret_scope="repository.read",
            ),
        )
    )
    broker = DependencyBroker(
        source_registry=registry,
        uv_adapter=adapter,
        artifact_store=store,
    )
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    environment = PythonResolutionEnvironment(
        python_version="3.11",
        python_platform="x86_64-pc-windows-msvc",
    )

    with pytest.raises(DependencyPolicyError, match="exactly one"):
        broker.resolve_python(
            _requirement(
                registered_source_ids=("pypi.public.v1", "private.v1")
            ),
            workspace=workspace,
            environment=environment,
        )

    for constraint in (
        "@ https://example.invalid/demo.whl",
        "git+https://example.invalid/repo.git",
        "file:../demo.whl",
    ):
        with pytest.raises(DependencyPolicyError, match="direct URL"):
            broker.resolve_python(
                _requirement(version_constraint=constraint),
                workspace=workspace,
                environment=environment,
            )


def test_private_source_blocks_until_secret_broker_exists(tmp_path: Path) -> None:
    runner = RecordingUvRunner(_pylock_text())
    adapter = _adapter(tmp_path, runner)
    private = DependencySourcePolicy(
        source_id="private.v1",
        index_url="https://packages.example/simple",
        allowed_artifact_hosts=("packages.example",),
        required_secret_scope="repository.read",
    )
    broker = DependencyBroker(
        source_registry=DependencySourceRegistry((private,)),
        uv_adapter=adapter,
        artifact_store=ArtifactStore(tmp_path / "artifact-store"),
    )
    workspace = tmp_path / "worktree"
    workspace.mkdir()

    with pytest.raises(DependencyResourceUnavailable, match="SecretBroker"):
        broker.resolve_python(
            _requirement(registered_source_ids=("private.v1",)),
            workspace=workspace,
            environment=PythonResolutionEnvironment(
                python_version="3.11",
                python_platform="x86_64-pc-windows-msvc",
            ),
        )


def test_broker_never_operates_in_protected_main_or_mutates_main_venv(
    tmp_path: Path,
) -> None:
    runner = RecordingUvRunner(_pylock_text())
    adapter = _adapter(tmp_path, runner)
    protected = tmp_path / "main"
    protected.mkdir()
    venv = protected / ".venv"
    venv.mkdir()
    sentinel = venv / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    before = sentinel.read_bytes()

    broker = DependencyBroker(
        source_registry=default_dependency_source_registry(),
        uv_adapter=adapter,
        artifact_store=ArtifactStore(tmp_path / "artifact-store"),
        protected_main_root=protected,
    )
    environment = PythonResolutionEnvironment(
        python_version="3.11",
        python_platform="x86_64-pc-windows-msvc",
    )

    with pytest.raises(DependencyPolicyError, match="protected main"):
        broker.resolve_python(
            _requirement(),
            workspace=protected,
            environment=environment,
        )

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    broker.resolve_python(
        _requirement(),
        workspace=worktree,
        environment=environment,
    )
    assert sentinel.read_bytes() == before
