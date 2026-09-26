from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest

from jarvis.engineering_substrate import (
    ArtifactIntegrityError,
    ArtifactStore,
    DependencyArtifact,
    DependencyEcosystem,
    DependencyRequirement,
    DependencyResolution,
    DistributionKind,
    default_sandbox_registry,
)
from jarvis.engineering_substrate.dependency import ResolvedPythonDependency
from jarvis.engineering_substrate.dependency.offline import (
    UV_VERIFY_IMAGE,
    OfflineCandidateVerifier,
    OfflineVerificationBundleBuilder,
    OfflineVerificationError,
)

WHEEL_BYTES = b"offline-wheel-payload"
WHEEL_SHA = hashlib.sha256(WHEEL_BYTES).hexdigest()


def _resolved_fixture(tmp_path: Path):
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        f"""lock-version = "1.0"
created-by = "uv 0.12.19"

[[packages]]
name = "demo-package"
version = "1.2.3"
index = "https://pypi.org/simple/"
dependencies = []

[[packages.wheels]]
name = "demo_package-1.2.3-py3-none-any.whl"
url = "https://files.pythonhosted.org/packages/demo/demo_package-1.2.3-py3-none-any.whl"
size = {len(WHEEL_BYTES)}
hashes = {{sha256 = "{WHEEL_SHA}"}}
""",
        encoding="utf-8",
    )
    requirement = DependencyRequirement(
        requirement_id="requirement-1",
        ecosystem=DependencyEcosystem.PYTHON,
        package_name="demo-package",
        version_constraint="==1.2.3",
        purpose="offline-test",
        registered_source_ids=("pypi.public.v1",),
    )
    resolution = DependencyResolution(
        resolution_id="resolution-1",
        requirement_id=requirement.requirement_id,
        resolver_id="uv",
        resolver_version="0.12.19",
        resolver_digest="a" * 64,
        resolved_packages=("demo-package==1.2.3",),
        artifact_ids=(WHEEL_SHA,),
        dependency_graph_digest="b" * 64,
        lock_format="pylock.toml",
        lock_version="1.0",
        lock_digest=hashlib.sha256(lock.read_bytes()).hexdigest(),
    )
    resolved = ResolvedPythonDependency(
        requirement=requirement,
        resolution=resolution,
        lock_path=lock,
    )
    store = ArtifactStore(tmp_path / "store")
    wheel = tmp_path / "demo_package-1.2.3-py3-none-any.whl"
    wheel.write_bytes(WHEEL_BYTES)
    admitted = store.admit_file(wheel, expected_sha256=WHEEL_SHA)
    artifact = DependencyArtifact(
        artifact_id=admitted.artifact_sha256,
        package_name="demo-package",
        package_version="1.2.3",
        filename=wheel.name,
        distribution_kind=DistributionKind.WHEEL,
        size_bytes=admitted.size_bytes,
        sha256=admitted.artifact_sha256,
        source_id="pypi.public.v1",
    )
    return resolved, store, artifact


def test_offline_bundle_rewrites_urls_to_local_verified_wheel_paths(
    tmp_path: Path,
) -> None:
    resolved, store, artifact = _resolved_fixture(tmp_path)
    builder = OfflineVerificationBundleBuilder(store)

    first = builder.build(
        resolved,
        (artifact,),
        output_root=tmp_path / "bundle-a",
    )
    second = builder.build(
        resolved,
        (artifact,),
        output_root=tmp_path / "bundle-b",
    )

    offline_text = (first.root / "pylock.toml").read_text(encoding="utf-8")
    assert "files.pythonhosted.org" not in offline_text
    assert 'path = "wheels/demo_package-1.2.3-py3-none-any.whl"' in offline_text
    assert (first.root / "wheels" / artifact.filename).read_bytes() == WHEEL_BYTES
    assert first.canonical_lock_digest == resolved.resolution.lock_digest
    assert first.offline_lock_digest == second.offline_lock_digest
    assert first.artifact_digests == (WHEEL_SHA,)

    parsed = tomllib.loads(offline_text)
    wheel = parsed["packages"][0]["wheels"][0]
    assert "url" not in wheel
    assert wheel["hashes"]["sha256"] == WHEEL_SHA


def test_offline_bundle_rejects_missing_or_tampered_artifact(tmp_path: Path) -> None:
    resolved, store, artifact = _resolved_fixture(tmp_path)
    builder = OfflineVerificationBundleBuilder(store)

    with pytest.raises(OfflineVerificationError, match="absent"):
        builder.build(
            resolved,
            (),
            output_root=tmp_path / "bundle-missing",
        )

    (store.objects_root / artifact.sha256).write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="verify-on-read"):
        builder.build(
            resolved,
            (artifact,),
            output_root=tmp_path / "bundle-tampered",
        )


class RecordingDockerRunner:
    def __init__(self, *, freeze_output: str = "demo-package==1.2.3\n") -> None:
        self.freeze_output = freeze_output
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        argv = [str(item) for item in command]
        self.commands.append(argv)
        if any("pip freeze" in item for item in argv):
            return subprocess.CompletedProcess(argv, 0, self.freeze_output, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_candidate_recreation_runs_only_registered_offline_docker_operations(
    tmp_path: Path,
) -> None:
    resolved, store, artifact = _resolved_fixture(tmp_path)
    bundle = OfflineVerificationBundleBuilder(store).build(
        resolved,
        (artifact,),
        output_root=tmp_path / "bundle",
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    candidate = tmp_path / "candidate"
    runner = RecordingDockerRunner()
    registry = default_sandbox_registry(docker_executable="docker")

    result = OfflineCandidateVerifier(
        sandbox_registry=registry,
        runner=runner,
    ).verify(
        bundle,
        candidate_dir=candidate,
        worktree=worktree,
    )

    assert result.inventory == ("demo-package==1.2.3",)
    assert result.image == UV_VERIFY_IMAGE
    assert len(runner.commands) == 1
    command = runner.commands[0]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in command
    assert UV_VERIFY_IMAGE in command
    assert "/candidate:rw,nosuid,size=512m" in command
    assert not any("candidate_rw" in item for item in command)
    script = command[-1]
    assert "uv --cache-dir /tmp/uv-cache venv /candidate/.venv" in script
    assert "pip sync /artifacts/pylock.toml" in script
    assert "--offline" in script
    assert "--require-hashes" in script
    assert "--only-binary :all:" in script
    assert "pip check" in script
    assert "pip freeze" in script
    assert "--no-build" not in script


def test_candidate_inventory_must_exactly_match_canonical_resolution(
    tmp_path: Path,
) -> None:
    resolved, store, artifact = _resolved_fixture(tmp_path)
    bundle = OfflineVerificationBundleBuilder(store).build(
        resolved,
        (artifact,),
        output_root=tmp_path / "bundle",
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(OfflineVerificationError, match="inventory differs"):
        OfflineCandidateVerifier(
            sandbox_registry=default_sandbox_registry(docker_executable="docker"),
            runner=RecordingDockerRunner(
                freeze_output="demo-package==1.2.3\nunexpected==9.9\n"
            ),
        ).verify(
            bundle,
            candidate_dir=tmp_path / "candidate",
            worktree=worktree,
        )


def test_candidate_verifier_refuses_unreviewed_container_image() -> None:
    with pytest.raises(ValueError, match="reviewed digest"):
        OfflineCandidateVerifier(
            sandbox_registry=default_sandbox_registry(docker_executable="docker"),
            image="ghcr.io/astral-sh/uv:latest",
        )
