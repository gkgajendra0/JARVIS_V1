"""Resolve and probe local authority executables without shell-owned state."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jarvis.machine_config import (
    configured_text,
    default_machine_config_path,
    load_machine_settings,
)

OPA_PATH_SETTING = "JARVIS_OPA_PATH"
# Kept so existing machine profiles stay valid. It used to name the compiled
# .NET helper; Windows Hello now runs through ``builtin_windows_hello_command``.
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


def builtin_windows_hello_command() -> tuple[str, ...]:
    """The Windows Hello consent prompt, run in the signed Python runtime.

    ``-I`` keeps the child isolated from PYTHONPATH, the user site and the
    current directory; the module imports only the standard library.
    """

    from jarvis.authority import windows_hello_consent

    return (sys.executable, "-I", windows_hello_consent.__file__)


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


# A first launch can be slow: Windows hashes the file and, for unsigned files
# under Smart App Control, asks the cloud reputation service before it runs.
OPA_PROBE_TIMEOUT_SECONDS = 30.0
_POLICY_BLOCKS = {
    4551: "blocked by Windows code integrity policy (Smart App Control / App Control)",
    1260: "blocked by a Windows software restriction policy",
    225: "blocked by Microsoft Defender as unsafe",
}


def describe_launch_failure(exc: BaseException) -> str:
    """A short, content-free cause for a failed child-process launch."""

    if isinstance(exc, subprocess.TimeoutExpired):
        return f"no response within {exc.timeout:g} s"
    winerror = getattr(exc, "winerror", None)
    if winerror in _POLICY_BLOCKS:
        return f"{_POLICY_BLOCKS[winerror]} (WinError {winerror})"
    if isinstance(exc, OSError):
        code = winerror if winerror is not None else exc.errno
        return f"could not start ({type(exc).__name__} {code})"
    return type(exc).__name__


def probe_opa_binary(
    path: str | Path,
    *,
    timeout_seconds: float = OPA_PROBE_TIMEOUT_SECONDS,
    attempts: int = 2,
    retry_delay_seconds: float = 2.0,
) -> str:
    """Run ``opa version``; one retry covers a slow or transiently refused launch.

    A retry never changes what is run or how it is checked: the same binary
    must start and print a ``Version:`` line. A policy block that persists
    fails exactly as before, now with its cause.
    """

    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise AuthorityToolError(f"OPA executable not found: {candidate}")
    causes: list[str] = []
    for attempt in range(max(1, attempts)):
        if attempt:
            time.sleep(retry_delay_seconds)
        try:
            completed = subprocess.run(
                [str(candidate), "version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            causes.append(describe_launch_failure(exc))
            continue
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        first_line = next(
            (line.strip() for line in output.splitlines() if line.strip()), ""
        )
        if completed.returncode != 0 or not first_line.casefold().startswith(
            "version:"
        ):
            raise AuthorityToolError(
                f"OPA executable did not satisfy the version probe: {candidate} "
                f"(exit code {completed.returncode})"
            )
        return first_line
    raise AuthorityToolError(
        f"OPA version probe failed: {candidate}: " + "; then ".join(causes)
    )


def probe_windows_hello_helper_contract(
    helper: str | Path | Sequence[str] | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    """Start the Hello consent helper without showing Hello UI; check its contract.

    ``None`` probes the built-in helper. A path probes a separate executable
    (tests and diagnostics only).
    """

    if helper is None:
        command = list(builtin_windows_hello_command())
        label = "built-in Windows Hello consent"
    elif isinstance(helper, (str, Path)):
        candidate = Path(helper).expanduser()
        if not candidate.is_file():
            raise AuthorityToolError(f"Windows Hello helper not found: {candidate}")
        command = [str(candidate)]
        label = str(candidate)
    else:
        command = [str(part) for part in helper]
        label = "Windows Hello helper"
    try:
        completed = subprocess.run(
            command,
            input="{}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise AuthorityToolError(
            f"Windows Hello contract probe failed: {label}: "
            f"{describe_launch_failure(exc)}"
        ) from exc
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AuthorityToolError(
            f"Windows Hello helper returned invalid JSON: {label}"
        ) from exc
    if (
        completed.returncode != 2
        or not isinstance(payload, dict)
        or payload.get("status") != "error"
        or payload.get("reason") != "invalid_request"
    ):
        raise AuthorityToolError(f"Windows Hello contract probe did not match: {label}")


def authority_tool_readiness(
    *,
    machine_settings: Mapping[str, str] | None = None,
) -> tuple[AuthorityToolReadiness, ...]:
    checks: list[AuthorityToolReadiness] = []
    try:
        opa = resolve_opa_binary(machine_settings=machine_settings)
        started = time.monotonic()
        version = probe_opa_binary(opa)
        elapsed = time.monotonic() - started
        if elapsed >= 5.0:
            version = f"{version} (slow start: {elapsed:.1f} s)"
        checks.append(AuthorityToolReadiness("OPA policy engine", True, version, opa))
    except (AuthorityToolError, RuntimeError) as exc:
        checks.append(AuthorityToolReadiness("OPA policy engine", False, str(exc)))

    try:
        probe_windows_hello_helper_contract()
        detail = "built-in Windows Hello consent ready (signed Python runtime)"
        settings = _settings_or_load(machine_settings)
        if configured_text(WINDOWS_HELLO_HELPER_SETTING, settings):
            detail += f"; {WINDOWS_HELLO_HELPER_SETTING} is no longer used"
        checks.append(
            AuthorityToolReadiness(
                "Windows Hello helper",
                True,
                detail,
                Path(builtin_windows_hello_command()[0]),
            )
        )
    except (AuthorityToolError, RuntimeError) as exc:
        checks.append(AuthorityToolReadiness("Windows Hello helper", False, str(exc)))
    return tuple(checks)
