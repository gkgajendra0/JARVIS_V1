"""Runtime construction helpers for the reviewed Phase-5 dependency broker."""

from __future__ import annotations

import pathlib
import shutil
import sys

from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.dependency.broker import DependencyBroker
from jarvis.engineering_substrate.dependency.policy import (
    UV_WINDOWS_X64_0_12_19,
    DependencyResourceUnavailable,
    default_dependency_source_registry,
)
from jarvis.engineering_substrate.dependency.uv_adapter import (
    PythonResolutionEnvironment,
    UvAdapter,
    UvBinaryRegistration,
)
from jarvis.machine_config import configured_text, load_machine_settings

UV_EXECUTABLE_SETTING = "JARVIS_UV_EXECUTABLE_PATH"
UV_EXECUTABLE_SHA256_SETTING = "JARVIS_UV_EXECUTABLE_SHA256"


def current_python_resolution_environment() -> PythonResolutionEnvironment:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.platform == "win32":
        target = "x86_64-pc-windows-msvc"
    elif sys.platform.startswith("linux"):
        target = "x86_64-unknown-linux-gnu"
    else:
        raise DependencyResourceUnavailable(
            f"unsupported dependency resolution platform: {sys.platform}"
        )
    return PythonResolutionEnvironment(
        python_version=version,
        python_platform=target,
    )


def build_runtime_uv_adapter(
    machine_settings: dict[str, str] | None = None,
) -> UvAdapter:
    settings = load_machine_settings() if machine_settings is None else machine_settings
    configured_path = configured_text(UV_EXECUTABLE_SETTING, settings)
    configured_digest = configured_text(UV_EXECUTABLE_SHA256_SETTING, settings)
    if not configured_path or not configured_digest:
        raise DependencyResourceUnavailable(
            "reviewed uv runtime is not configured; persist JARVIS_UV_EXECUTABLE_PATH "
            "and JARVIS_UV_EXECUTABLE_SHA256 after Phase-5 owner acceptance"
        )
    executable = pathlib.Path(configured_path).expanduser().resolve()
    policy = UV_WINDOWS_X64_0_12_19
    registration = UvBinaryRegistration(
        executable_path=executable,
        version=policy.version,
        executable_sha256=str(configured_digest).strip().casefold(),
        release_commit_sha=policy.release_commit_sha,
        release_asset_sha256=policy.release_asset_sha256,
        release_policy_digest=policy.policy_digest,
    )
    adapter = UvAdapter(
        release_policy=policy,
        binary_registration=registration,
    )
    adapter.verify_trust()
    return adapter


def build_runtime_dependency_broker(
    *,
    artifact_store: ArtifactStore | None = None,
    protected_main_root: pathlib.Path | str | None = None,
    machine_settings: dict[str, str] | None = None,
) -> DependencyBroker:
    return DependencyBroker(
        source_registry=default_dependency_source_registry(),
        uv_adapter=build_runtime_uv_adapter(machine_settings),
        artifact_store=artifact_store or ArtifactStore(),
        protected_main_root=protected_main_root,
    )


def dependency_work_root(work_id: str) -> pathlib.Path:
    token = "".join(
        character
        for character in str(work_id).strip()
        if character.isascii() and (character.isalnum() or character in {"-", "_"})
    )
    if not token:
        raise ValueError("dependency work_id cannot be normalized safely")
    base = ArtifactStore().root / "dependency-work"
    root = (base / token).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise DependencyResourceUnavailable("dependency work root cannot be a symlink")
    return root


def reset_dependency_work_root(work_id: str) -> pathlib.Path:
    root = dependency_work_root(work_id)
    for child in root.iterdir():
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return root
