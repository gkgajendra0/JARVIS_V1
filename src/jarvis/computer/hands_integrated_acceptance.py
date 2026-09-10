"""Consolidated owner-machine acceptance for governed JARVIS Hands H1-H5."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.authority.tooling import authority_tool_readiness
from jarvis.capabilities.development_git import (
    ApprovedRepositoryPolicy,
    DevelopmentGitError,
)
from jarvis.capabilities.local_writes import (
    ApprovedWriteRootPolicy,
    LocalWriteValidationError,
)
from jarvis.capabilities.runtime import (
    CapabilityRuntime,
    build_default_capability_runtime,
)
from jarvis.capabilities.software_management import WinGetBackend
from jarvis.computer.structured_windows import StructuredWindowsError, WinAppCliBackend
from jarvis.hands.registry import HandsCapabilityRegistry
from jarvis.setup import _probe_playwright_chromium

_ACCEPTANCE_MARKER = "JARVIS governed Hands H1-H5 acceptance"
_OPTIONAL_OPERATION_NAMES = {"execute_visual_desktop_task"}
_REQUIRED_MODULES = {
    "send2trash": "Send2Trash governed file deletion",
    "docx": "python-docx semantic DOCX editing",
    "openpyxl": "openpyxl semantic XLSX editing",
    "pptx": "python-pptx semantic PPTX editing",
    "playwright": "Playwright structured browser control",
    "dulwich": "Dulwich Git control",
}
_WINDOWS_REQUIRED_MODULES = {
    "screen_brightness_control": "Windows display control",
    "winrt.windows.foundation.collections": "Windows Runtime Foundation Collections",
    "winrt.windows.devices.enumeration": "Windows device enumeration",
    "winrt.windows.devices.bluetooth": "Windows Bluetooth control",
}


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    ok: bool
    detail: str


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _dependency_checks(
    finder: Callable[[str], bool] = _module_available,
) -> tuple[AcceptanceCheck, ...]:
    required = dict(_REQUIRED_MODULES)
    if platform.system() == "Windows":
        required.update(_WINDOWS_REQUIRED_MODULES)
    checks: list[AcceptanceCheck] = []
    for module, label in required.items():
        available = finder(module)
        checks.append(
            AcceptanceCheck(
                name=f"Hands dependency: {label}",
                ok=available,
                detail=module if available else f"missing Python module: {module}",
            )
        )
    return tuple(checks)


def _required_operation_names() -> tuple[str, ...]:
    return tuple(
        item.operation
        for item in HandsCapabilityRegistry.default().operations
        if item.operation not in _OPTIONAL_OPERATION_NAMES
    )


def _operation_resolution_checks(
    runtime: CapabilityRuntime,
) -> tuple[AcceptanceCheck, ...]:
    checks: list[AcceptanceCheck] = []
    for operation in _required_operation_names():
        capability = runtime.capability_for_operation(operation)
        checks.append(
            AcceptanceCheck(
                name=f"Hands operation: {operation}",
                ok=capability is not None,
                detail=capability or "no enabled governed executor resolved",
            )
        )
    return tuple(checks)


def collect_integrated_readiness() -> tuple[AcceptanceCheck, ...]:
    checks: list[AcceptanceCheck] = []
    for item in authority_tool_readiness():
        detail = item.detail
        if item.path is not None:
            detail = f"{item.path} | {detail}"
        checks.append(AcceptanceCheck(item.label, item.ok, detail))

    checks.extend(_dependency_checks())

    try:
        ui = WinAppCliBackend()
        probe = ui.probe()
        checks.append(
            AcceptanceCheck(
                "Microsoft winapp",
                True,
                f"{ui.executable} | probe {probe.elapsed_ms:.1f} ms",
            )
        )
    except (StructuredWindowsError, OSError, RuntimeError) as exc:
        checks.append(AcceptanceCheck("Microsoft winapp", False, str(exc)))

    chromium = _probe_playwright_chromium()
    checks.append(
        AcceptanceCheck(
            "Playwright Chromium launch",
            chromium is not None,
            str(chromium) if chromium is not None else "Chromium is not launchable",
        )
    )

    winget = WinGetBackend.available()
    checks.append(
        AcceptanceCheck(
            "Microsoft WinGet",
            winget,
            "winget executable available"
            if winget
            else "winget executable unavailable",
        )
    )

    try:
        write_policy = ApprovedWriteRootPolicy()
        checks.append(
            AcceptanceCheck(
                "Governed local write roots",
                True,
                ", ".join(write_policy.aliases),
            )
        )
    except LocalWriteValidationError as exc:
        checks.append(AcceptanceCheck("Governed local write roots", False, str(exc)))

    try:
        repo_policy = ApprovedRepositoryPolicy()
        checks.append(
            AcceptanceCheck(
                "Governed development repositories",
                True,
                ", ".join(repo_policy.aliases),
            )
        )
    except DevelopmentGitError as exc:
        checks.append(
            AcceptanceCheck("Governed development repositories", False, str(exc))
        )

    runtime: CapabilityRuntime | None = None
    try:
        runtime = build_default_capability_runtime(
            ai_provider=os.getenv("JARVIS_AI_PROVIDER", "gemini")
        )
        checks.extend(_operation_resolution_checks(runtime))
    except Exception as exc:  # noqa: BLE001 - readiness reports optional boundary failures
        checks.append(
            AcceptanceCheck(
                "Governed H1-H5 runtime",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        )
    finally:
        if runtime is not None:
            runtime.close()
    return tuple(checks)


def _readiness_payload(checks: tuple[AcceptanceCheck, ...]) -> dict[str, Any]:
    return {
        "ok": all(check.ok for check in checks),
        "operation": "governed_hands_h1_h5_readiness",
        "read_only": True,
        "mutations_performed": 0,
        "cloud_model_calls": 0,
        "checks": [
            {"name": check.name, "ok": check.ok, "detail": check.detail}
            for check in checks
        ],
    }


def _preferred_write_root(policy: ApprovedWriteRootPolicy) -> str:
    for preferred in ("downloads", "documents", "desktop"):
        if preferred in policy.aliases:
            return preferred
    if not policy.aliases:
        raise LocalWriteValidationError("no approved write root is available")
    return policy.aliases[0]


def _acceptance_paths(run_id: str) -> dict[str, str]:
    folder = f"JARVIS_Hands_Acceptance_{run_id}"
    return {
        "folder": folder,
        "text": f"{folder}/acceptance.txt",
        "docx": f"{folder}/acceptance.docx",
        "xlsx": f"{folder}/acceptance.xlsx",
        "pptx": f"{folder}/acceptance.pptx",
    }


def _representative_actions(
    *,
    write_root: str,
    run_id: str,
) -> tuple[tuple[str, str, dict[str, Any]], ...]:
    paths = _acceptance_paths(run_id)
    return (
        ("h1_system", "system_status", {}),
        ("h1_audio", "get_master_volume", {}),
        ("h1_windows", "list_windows", {}),
        ("h1_app", "open_app", {"app": "calculator"}),
        (
            "h2_text_file",
            "create_text_file",
            {"root": write_root, "path": paths["text"], "text": _ACCEPTANCE_MARKER},
        ),
        (
            "h2_docx",
            "create_docx",
            {"root": write_root, "path": paths["docx"], "text": _ACCEPTANCE_MARKER},
        ),
        (
            "h2_xlsx",
            "create_xlsx",
            {"root": write_root, "path": paths["xlsx"], "sheet": "Hands"},
        ),
        (
            "h2_pptx",
            "create_pptx",
            {
                "root": write_root,
                "path": paths["pptx"],
                "title": "JARVIS Hands Acceptance",
                "body": _ACCEPTANCE_MARKER,
            },
        ),
        (
            "h3_browser",
            "execute_browser_plan",
            {
                "plan": [
                    {"action": "navigate", "url": "https://example.com"},
                    {"action": "read_page"},
                ]
            },
        ),
        ("h4_displays", "list_displays", {}),
        ("h4_bluetooth", "list_bluetooth_devices", {}),
        ("h4_software", "search_software", {"query": "PowerToys"}),
        ("h5_git", "git_status", {"repo": "jarvis"}),
    )


def _result_payload(label: str, result) -> dict[str, Any]:
    return {
        "label": label,
        "ok": result.ok,
        "operation": result.operation,
        "capability": result.capability_key,
        "status": result.status.value,
        "verification_passed": result.data.get("verification_passed", False),
        "reason": result.reason,
        "elapsed_ms": round(result.elapsed_ms, 1),
        "provenance": list(result.provenance),
    }


def run_integrated_readiness() -> int:
    if platform.system() != "Windows":
        print("JARVIS H1-H5 Hands readiness requires Windows.")
        return 2
    payload = _readiness_payload(collect_integrated_readiness())
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] is True else 2


def run_integrated_acceptance() -> int:
    """Run one representative real-machine acceptance session for H1-H5 Hands."""

    if platform.system() != "Windows":
        print("JARVIS H1-H5 Hands acceptance requires Windows.")
        return 2

    readiness = _readiness_payload(collect_integrated_readiness())
    print(json.dumps(readiness, indent=2))
    if readiness["ok"] is not True:
        print("PRECHECK FAILED: no mutations were attempted.")
        return 2

    policy = ApprovedWriteRootPolicy()
    write_root = _preferred_write_root(policy)
    run_id = uuid.uuid4().hex[:8]
    paths = _acceptance_paths(run_id)
    actions = _representative_actions(write_root=write_root, run_id=run_id)

    print("JARVIS consolidated governed Hands H1-H5 owner acceptance")
    print(f"write_root={write_root}")
    print(f"acceptance_folder={paths['folder']}")
    print("h1_mutation=approved Calculator launch only")
    print("browser_target=https://example.com")
    print("software_action=read-only WinGet search for PowerToys")
    print("development_action=read-only Git status for the JARVIS repository")
    print(
        "power_session_mutations=False bluetooth_pairing=False package_mutations=False"
    )
    print("JARVIS_self_modification=False cloud_model_calls=0 raw_shell=False")

    runtime = build_default_capability_runtime(
        ai_provider=os.getenv("JARVIS_AI_PROVIDER", "gemini")
    )
    results: list[dict[str, Any]] = []
    try:
        for label, operation, parameters in actions:
            result = runtime.execute_operation(
                session_id=f"governed-hands-h1-h5-{run_id}",
                operation=operation,
                parameters=parameters,
            )
            payload = _result_payload(label, result)
            results.append(payload)
            print(json.dumps(payload, indent=2))
            if not result.ok or payload["verification_passed"] is not True:
                break
    finally:
        runtime.close()

    ok = len(results) == len(actions) and all(
        item["ok"] and item["verification_passed"] for item in results
    )
    summary = {
        "ok": ok,
        "operation": "governed_hands_h1_h5_owner_acceptance",
        "actions_completed": len(results),
        "actions_expected": len(actions),
        "verification_passed": ok,
        "write_root": write_root,
        "acceptance_folder": paths["folder"],
        "cloud_model_calls": 0,
        "raw_shell": False,
        "arbitrary_browser_javascript": False,
        "package_mutations": False,
        "power_session_mutations": False,
        "bluetooth_pairing_mutations": False,
        "jarvis_self_modification": False,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    if ok:
        root_path: Path = policy.root(write_root)
        print(
            f"Acceptance artifacts left for inspection at: {root_path / paths['folder']}"
        )
    return 0 if ok else 3
