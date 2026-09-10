"""Resolve and probe local authority executables without shell-owned state."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jarvis.machine_config import (
    configured_text,
    default_machine_config_path,
    load_machine_settings,
)

OPA_PATH_SETTING = "JARVIS_OPA_PATH"
WINDOWS_HELLO_HELPER_SETTING = "JARVIS_WINDOWS_HELLO_HELPER"


class AuthorityToolError(RuntimeError):
    """Raised when a required local authority executable is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class AuthorityToolReadiness:
    label: str
    ok: bool
    detail: str
    path: Path | None = None


def managed_tools_root() -> Path:
    """Return the per-user JARVIS tool directory beside ``machine.json``."""

    return default_machine_config_path().parent / "tools"


def managed_windows_hello_helper_path() -> Path:
    return managed_tools_root() / "windows-hello" / "Jarvis.WindowsHelloVerifier.exe"


def _settings_or_load(machine_settings: Mapping[str, str] | None) -> Mapping[str, str]:
    return load_machine_settings() if machine_settings is None else machine_settings


def _configured_executable(
    setting: str,
    *,
    explicit: str | Path | None,
    machine_settings: Mapping[str, str] | None,
) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise AuthorityToolError(
                f"explicit {setting} executable does not exist: {candidate}"
            )
        return candidate

    settings = _settings_or_load(machine_settings)
    configured = configured_text(setting, settings)
    if configured is None or not configured.strip():
        return None
    candidate = Path(configured).expanduser()
    if not candidate.is_file():
        raise AuthorityToolError(
            f"configured {setting} executable does not exist: {candidate}; "
            "run jarvis-setup to repair the machine profile"
        )
    return candidate


def resolve_opa_binary(
    explicit: str | Path | None = None,
    *,
    machine_settings: Mapping[str, str] | None = None,
) -> Path:
    """Resolve OPA using explicit/configured state before bounded discovery fallbacks."""

    configured = _configured_executable(
        OPA_PATH_SETTING,
        explicit=explicit,
        machine_settings=machine_settings,
    )
    if configured is not None:
        return configured

    discovered = shutil.which("opa")
    if discovered:
        return Path(discovered)

    legacy_candidates = (
        Path.home() / ".jarvis" / "tools" / "opa.exe",
        managed_tools_root() / "opa" / "opa.exe",
        managed_tools_root() / "opa.exe",
    )
    for candidate in legacy_candidates:
        if candidate.is_file():
            return candidate

    raise AuthorityToolError(
        "OPA is required for authority policy evaluation. Run jarvis-setup after "
        "installing the official OPA Windows binary."
    )


def resolve_windows_hello_helper(
    explicit: str | Path | None = None,
    *,
    machine_settings: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the exact local Windows Hello helper used by strong approval."""

    configured = _configured_executable(
        WINDOWS_HELLO_HELPER_SETTING,
        explicit=explicit,
        machine_settings=machine_settings,
    )
    if configured is not None:
        return configured

    managed = managed_windows_hello_helper_path()
    if managed.is_file():
        return managed
    raise AuthorityToolError(
        "Windows Hello helper is not configured. Run jarvis-setup to publish the "
        "managed helper for this PC."
    )


def probe_opa_binary(path: str | Path, *, timeout_seconds: float = 5.0) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise AuthorityToolError(f"OPA executable not found: {candidate}")
    try:
        completed = subprocess.run(
            [str(candidate), "version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorityToolError(f"OPA version probe failed: {candidate}") from exc
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0 or "version" not in output.casefold():
        raise AuthorityToolError(
            f"OPA executable did not satisfy the version probe: {candidate}"
        )
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "OPA")
    return first_line


def probe_windows_hello_helper_contract(
    path: str | Path,
    *,
    timeout_seconds: float = 10.0,
) -> None:
    """Launch the helper without showing Hello UI and validate its JSON contract."""

    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise AuthorityToolError(f"Windows Hello helper not found: {candidate}")
    try:
        completed = subprocess.run(
            [str(candidate)],
            input="{}",
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorityToolError(
            f"Windows Hello helper contract probe failed: {candidate}"
        ) from exc
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AuthorityToolError(
            f"Windows Hello helper returned invalid JSON: {candidate}"
        ) from exc
    if (
        completed.returncode != 2
        or not isinstance(payload, dict)
        or payload.get("status") != "error"
        or payload.get("reason") != "invalid_request"
    ):
        raise AuthorityToolError(
            f"Windows Hello helper contract probe did not match: {candidate}"
        )


def authority_tool_readiness(
    *,
    machine_settings: Mapping[str, str] | None = None,
) -> tuple[AuthorityToolReadiness, ...]:
    checks: list[AuthorityToolReadiness] = []
    try:
        opa = resolve_opa_binary(machine_settings=machine_settings)
        version = probe_opa_binary(opa)
        checks.append(AuthorityToolReadiness("OPA policy engine", True, version, opa))
    except (AuthorityToolError, RuntimeError) as exc:
        checks.append(AuthorityToolReadiness("OPA policy engine", False, str(exc)))

    try:
        hello = resolve_windows_hello_helper(machine_settings=machine_settings)
        probe_windows_hello_helper_contract(hello)
        checks.append(
            AuthorityToolReadiness(
                "Windows Hello helper",
                True,
                "managed helper JSON contract ready",
                hello,
            )
        )
    except (AuthorityToolError, RuntimeError) as exc:
        checks.append(AuthorityToolReadiness("Windows Hello helper", False, str(exc)))
    return tuple(checks)
