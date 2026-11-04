"""One-time provisioning of non-secret authority executables for this PC."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from jarvis.authority.tooling import (
    OPA_PATH_SETTING,
    AuthorityToolError,
    managed_tools_root,
    probe_opa_binary,
    probe_windows_hello_helper_contract,
)
from jarvis.machine_config import configured_text


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


def check_builtin_windows_hello() -> None:
    """Confirm the built-in Hello consent helper starts (no Hello prompt)."""

    if os.name != "nt":
        raise AuthorityToolError("Windows Hello is only available on Windows")
    probe_windows_hello_helper_contract()


def configure_authority_tool_settings(
    existing: Mapping[str, str],
    *,
    prompt: Callable[[str], str] = input,
) -> dict[str, str]:
    """Resolve OPA and check Hello, returning persistable machine settings.

    Windows Hello needs no setting: it runs in the Python runtime. An existing
    ``JARVIS_WINDOWS_HELLO_HELPER`` value is left as it is, and unused.
    """

    opa = discover_opa_for_setup(existing)
    if opa is None:
        opa = _prompt_for_opa(prompt)
    version = probe_opa_binary(opa)
    print(f"Using OPA: {opa} ({version})")

    check_builtin_windows_hello()
    print("Using built-in Windows Hello consent (no separate helper executable)")
    return {OPA_PATH_SETTING: str(opa)}
