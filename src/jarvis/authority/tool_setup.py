"""One-time provisioning of non-secret authority executables for this PC."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from jarvis.authority.tooling import (
    OPA_PATH_SETTING,
    WINDOWS_HELLO_HELPER_SETTING,
    AuthorityToolError,
    managed_tools_root,
    managed_windows_hello_helper_path,
    probe_opa_binary,
    probe_windows_hello_helper_contract,
)
from jarvis.machine_config import configured_text


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _windows_runtime_identifier() -> str:
    machine = platform.machine().strip().casefold()
    if machine in {"amd64", "x86_64", "x64"}:
        return "win-x64"
    if machine in {"arm64", "aarch64"}:
        return "win-arm64"
    raise AuthorityToolError(
        f"unsupported Windows architecture for Hello helper: {machine}"
    )


def _valid_opa(candidate: Path | None) -> Path | None:
    if candidate is None or not candidate.is_file():
        return None
    try:
        probe_opa_binary(candidate)
    except AuthorityToolError:
        return None
    return candidate


def discover_opa_for_setup(existing: Mapping[str, str]) -> Path | None:
    configured = configured_text(OPA_PATH_SETTING, existing)
    if configured:
        valid = _valid_opa(Path(configured).expanduser())
        if valid is not None:
            return valid

    discovered = shutil.which("opa")
    if discovered:
        valid = _valid_opa(Path(discovered))
        if valid is not None:
            return valid

    for candidate in (
        Path.home() / ".jarvis" / "tools" / "opa.exe",
        managed_tools_root() / "opa" / "opa.exe",
        managed_tools_root() / "opa.exe",
    ):
        valid = _valid_opa(candidate)
        if valid is not None:
            return valid
    return None


def _prompt_for_opa(prompt: Callable[[str], str]) -> Path:
    while True:
        raw = prompt(
            "OPA executable path (install the official opa.exe first, then enter its path): "
        ).strip()
        candidate = Path(raw).expanduser()
        valid = _valid_opa(candidate)
        if valid is not None:
            return valid
        print(f"Not a usable OPA executable: {candidate}")


def _hello_project_path() -> Path:
    return (
        _repo_root()
        / "tools"
        / "windows"
        / "Jarvis.WindowsHelloVerifier"
        / "Jarvis.WindowsHelloVerifier.csproj"
    )


def _publish_command(
    *,
    dotnet: str,
    project: Path,
    output: Path,
    runtime_identifier: str,
) -> list[str]:
    return [
        dotnet,
        "publish",
        str(project),
        "--configuration",
        "Release",
        "--runtime",
        runtime_identifier,
        "--self-contained",
        "true",
        "--nologo",
        "-p:PublishSingleFile=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true",
        "-p:PublishTrimmed=false",
        "-p:DebugType=None",
        "--output",
        str(output),
    ]


def ensure_managed_windows_hello_helper() -> Path:
    if os.name != "nt":
        raise AuthorityToolError(
            "Windows Hello helper can only be provisioned on Windows"
        )

    destination = managed_windows_hello_helper_path()
    existing_valid = False
    if destination.is_file():
        try:
            probe_windows_hello_helper_contract(destination)
            existing_valid = True
        except AuthorityToolError:
            existing_valid = False

    dotnet = shutil.which("dotnet")
    if not dotnet:
        if existing_valid:
            return destination
        raise AuthorityToolError(
            ".NET 9 SDK is required once to publish the self-contained Windows Hello "
            "helper; install it and rerun jarvis-setup"
        )

    project = _hello_project_path()
    if not project.is_file():
        raise AuthorityToolError(f"Windows Hello helper project is missing: {project}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    runtime_identifier = _windows_runtime_identifier()
    with tempfile.TemporaryDirectory(
        prefix="hello-publish-",
        dir=destination.parent,
    ) as raw_temp:
        output = Path(raw_temp)
        command = _publish_command(
            dotnet=dotnet,
            project=project,
            output=output,
            runtime_identifier=runtime_identifier,
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=180.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuthorityToolError("Windows Hello helper publish failed") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise AuthorityToolError(
                "Windows Hello helper publish failed"
                + (f": {detail[-1000:]}" if detail else "")
            )
        published = output / "Jarvis.WindowsHelloVerifier.exe"
        probe_windows_hello_helper_contract(published)
        staged = destination.with_suffix(".exe.tmp")
        shutil.copy2(published, staged)
        os.replace(staged, destination)

    probe_windows_hello_helper_contract(destination)
    return destination


def configure_authority_tool_settings(
    existing: Mapping[str, str],
    *,
    prompt: Callable[[str], str] = input,
) -> dict[str, str]:
    """Resolve OPA and publish Hello once, returning persistable machine settings."""

    opa = discover_opa_for_setup(existing)
    if opa is None:
        opa = _prompt_for_opa(prompt)
    version = probe_opa_binary(opa)
    print(f"Using OPA: {opa} ({version})")

    hello = ensure_managed_windows_hello_helper()
    print(f"Using managed Windows Hello helper: {hello}")
    return {
        OPA_PATH_SETTING: str(opa),
        WINDOWS_HELLO_HELPER_SETTING: str(hello),
    }
