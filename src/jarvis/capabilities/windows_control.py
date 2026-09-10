"""Governed Windows desktop-control executors for JARVIS hands."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import time
from collections.abc import Callable
from typing import Any

from jarvis.authority.types import ActionAttributes, ActionScope
from jarvis.capabilities.execution import (
    CapabilityExecutionError,
    PreparedCapability,
)
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.computer.executor import MssPyAutoGuiExecutor
from jarvis.computer.providers import build_computer_use_provider
from jarvis.computer.service import ComputerUseService
from jarvis.computer.structured_windows import (
    AllowlistedWindowsLauncher,
    StructuredCommandResult,
    StructuredWindowsError,
    WinAppCliBackend,
)

_MAX_TASK_CHARACTERS = 1_500
_MAX_PLAN_STEPS = 12
_MAX_RESULT_JSON_CHARACTERS = 16_000
_ALLOWED_STRUCTURED_ACTIONS = {
    "launch",
    "wait_until_running",
    "inspect",
    "search",
    "get_value",
    "verify_value",
    "focus",
    "click",
    "invoke",
    "send_text",
    "set_value",
    "wait_for",
}
_MUTATING_STRUCTURED_ACTIONS = {
    "launch",
    "focus",
    "click",
    "invoke",
    "send_text",
    "set_value",
}
_READ_STRUCTURED_ACTIONS = {
    "inspect",
    "search",
    "get_value",
    "verify_value",
}
_VISUAL_BLOCKED_TERMS = (
    "browser",
    "chrome",
    "edge",
    "firefox",
    "website",
    "web page",
    "email",
    "mail",
    "send message",
    "teams",
    "slack",
    "file explorer",
    "explorer",
    "powershell",
    "terminal",
    "command prompt",
    "cmd.exe",
    "registry",
    "regedit",
    "install",
    "uninstall",
    "download",
    "upload",
    "delete",
    "remove file",
    "save file",
    "save document",
    "password",
    "credential",
    "api key",
    "token",
)
_SECRET_LIKE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_ -]?key|password|token|secret)\s*[:=])"
)


def _safe_apps() -> tuple[str, ...]:
    defaults = set(AllowlistedWindowsLauncher.supported_apps())
    configured = os.getenv("JARVIS_DESKTOP_CONTROL_APPS", "")
    if not configured.strip():
        return tuple(sorted(defaults))
    requested = {
        item.strip().casefold() for item in configured.split(",") if item.strip()
    }
    return tuple(sorted(defaults & requested))


def _normalize_app(value: object) -> str:
    app = str(value).strip().casefold()
    if not app or len(app) > 80:
        raise ValueError("desktop-control app must be a bounded non-empty name")
    allowed = _safe_apps()
    if app not in allowed:
        raise ValueError(
            f"desktop-control app is not approved: {app}; approved={','.join(allowed)}"
        )
    return app


def _normalize_task(value: object) -> str:
    task = " ".join(str(value).split())
    if not task:
        raise ValueError("desktop-control task must not be empty")
    if len(task) > _MAX_TASK_CHARACTERS:
        raise ValueError("desktop-control task exceeds bounded input limit")
    if _SECRET_LIKE.search(task):
        raise ValueError("desktop-control task appears to contain credential material")
    return task


def _bounded_string(value: object, *, field: str, maximum: int = 500) -> str:
    text = str(value)
    if not text or len(text) > maximum:
        raise ValueError(f"{field} must be a non-empty bounded string")
    if _SECRET_LIKE.search(text):
        raise ValueError(f"{field} appears to contain credential material")
    return text


def _bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise TypeError("boolean plan fields must be true or false")


def _float_in_range(
    value: object,
    *,
    field: str,
    minimum: float,
    maximum: float,
    default: float,
) -> float:
    raw = default if value is None else float(value)
    if not minimum <= raw <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return raw


def _normalize_plan(raw: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("structured desktop plan must be a non-empty list")
    if len(raw) > _MAX_PLAN_STEPS:
        raise ValueError(f"structured desktop plan exceeds {_MAX_PLAN_STEPS} steps")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"plan step {index} must be an object")
        action = str(item.get("action", "")).strip().casefold()
        if action not in _ALLOWED_STRUCTURED_ACTIONS:
            raise ValueError(
                f"unsupported structured desktop action: {action or '<empty>'}"
            )
        step: dict[str, Any] = {"action": action}
        if action in {
            "inspect",
            "get_value",
            "verify_value",
            "focus",
            "click",
            "invoke",
            "send_text",
            "set_value",
            "wait_for",
        }:
            selector = item.get("selector")
            if action in {"inspect", "send_text"} and selector in {None, ""}:
                step["selector"] = None
            else:
                step["selector"] = _bounded_string(
                    selector,
                    field="selector",
                    maximum=300,
                )
        if action == "inspect":
            depth = int(item.get("depth", 6))
            if not 1 <= depth <= 8:
                raise ValueError("inspect depth must be between 1 and 8")
            step["depth"] = depth
            step["interactive"] = _bool(item.get("interactive"), default=True)
        elif action == "search":
            step["query"] = _bounded_string(
                item.get("query"),
                field="search query",
                maximum=300,
            )
            max_results = int(item.get("max_results", 10))
            if not 1 <= max_results <= 25:
                raise ValueError("search max_results must be between 1 and 25")
            step["max_results"] = max_results
        elif action == "verify_value":
            step["expected"] = _bounded_string(
                item.get("expected"),
                field="verification expected value",
            )
            comparison = str(item.get("comparison", "equals")).strip().casefold()
            if comparison not in {"equals", "contains"}:
                raise ValueError("verification comparison must be equals or contains")
            step["comparison"] = comparison
        elif action == "click":
            step["double"] = _bool(item.get("double"))
            step["right"] = _bool(item.get("right"))
            if step["double"] and step["right"]:
                raise ValueError("double and right click cannot be combined")
        elif action in {"send_text", "set_value"}:
            step["text"] = _bounded_string(item.get("text"), field="typed text")
        elif action == "wait_until_running":
            step["timeout_seconds"] = _float_in_range(
                item.get("timeout_seconds"),
                field="wait timeout",
                minimum=0.5,
                maximum=15.0,
                default=6.0,
            )
        elif action == "wait_for":
            step["timeout_seconds"] = _float_in_range(
                item.get("timeout_seconds"),
                field="wait-for timeout",
                minimum=0.1,
                maximum=15.0,
                default=5.0,
            )
            step["gone"] = _bool(item.get("gone"))
        normalized.append(step)
    return tuple(normalized)


def _extract_value(payload: dict[str, Any]) -> str:
    for key in ("text", "value", "name"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) <= _MAX_RESULT_JSON_CHARACTERS:
        return payload
    return {
        "truncated": True,
        "preview": encoded[:_MAX_RESULT_JSON_CHARACTERS],
    }


class WindowsStructuredControlExecutor:
    """Execute one owner-approved bounded structured Windows task."""

    capability_key = "windows:desktop.control"
    operations = ("execute_windows_plan",)

    def __init__(
        self,
        *,
        backend_factory: Callable[[], WinAppCliBackend] = WinAppCliBackend,
        launcher_factory: Callable[[], AllowlistedWindowsLauncher] = (
            AllowlistedWindowsLauncher
        ),
        execution_enabled: bool | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self._launcher_factory = launcher_factory
        if execution_enabled is None:
            execution_enabled = platform.system() == "Windows"
        self._execution_enabled = bool(execution_enabled)
        self.descriptor = CapabilityDescriptor.create(
            capability_id="desktop.control",
            source_id="windows",
            kind=CapabilityKind.STRUCTURED_AUTOMATION,
            name="Governed Windows Desktop Control",
            description=(
                "Bounded local Windows application control through Microsoft winapp UIA "
                "and an explicit shell-free launcher allowlist."
            ),
            operations=self.operations,
            metadata={
                "backend": "Microsoft winapp UI Automation",
                "approved_apps": list(_safe_apps()),
                "raw_shell": False,
                "browser_control": False,
            },
            execution_enabled=self._execution_enabled,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation != "execute_windows_plan":
            raise ValueError("unsupported structured Windows operation")
        app = _normalize_app(request.parameters.get("app"))
        task = _normalize_task(request.parameters.get("task"))
        plan = _normalize_plan(request.parameters.get("plan"))
        allow_existing_app = _bool(request.parameters.get("allow_existing_app"))
        mutating = any(step["action"] in _MUTATING_STRUCTURED_ACTIONS for step in plan)
        if not mutating:
            raise ValueError(
                "desktop control plan must contain at least one control action"
            )
        reads_private_state = any(
            step["action"] in _READ_STRUCTURED_ACTIONS for step in plan
        )
        return PreparedCapability(
            request=request,
            target={
                "app": app,
                "strategy": "structured_winapp",
                "step_actions": [step["action"] for step in plan],
            },
            parameters={
                "app": app,
                "task": task,
                "plan": [dict(step) for step in plan],
                "allow_existing_app": allow_existing_app,
            },
            material_summary=f"Control {app} to perform: {task}",
            attributes=ActionAttributes(
                private_read=reads_private_state,
                reversible_local_change=True,
                scope=ActionScope.LIMITED,
            ),
            execution_payload={
                "app": app,
                "task": task,
                "plan": plan,
                "allow_existing_app": allow_existing_app,
            },
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        payload = prepared.execution_payload
        app = str(payload["app"])
        plan = tuple(payload["plan"])
        allow_existing = bool(payload["allow_existing_app"])
        try:
            ui = self._backend_factory()
            launcher = self._launcher_factory()
        except (StructuredWindowsError, OSError) as exc:
            return CapabilityResult(
                status=CapabilityStatus.UNAVAILABLE,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={},
                reason=str(exc),
                elapsed_ms=(time.monotonic() - started) * 1000,
            )

        launched_here = False
        results: list[dict[str, Any]] = []
        try:
            for index, step in enumerate(plan, start=1):
                action = str(step["action"])
                if action == "launch":
                    existing = ui.status(app, check=False)
                    if int(existing.payload.get("exit_code", 1)) == 0:
                        if not allow_existing:
                            raise CapabilityExecutionError(
                                "target app is already running; explicit existing-app "
                                "control was not authorized"
                            )
                        result = existing
                    else:
                        result = launcher.launch(app)
                        launched_here = True
                else:
                    if action in _MUTATING_STRUCTURED_ACTIONS and not (
                        launched_here or allow_existing
                    ):
                        raise CapabilityExecutionError(
                            "control action targets an existing app without explicit "
                            "existing-app authorization"
                        )
                    result = self._execute_step(ui, app, step)

                result_payload = _compact_payload(dict(result.payload))
                record: dict[str, Any] = {
                    "index": index,
                    "action": action,
                    "elapsed_ms": round(result.elapsed_ms, 1),
                    "payload": result_payload,
                }
                if action == "verify_value":
                    actual = _extract_value(result.payload)
                    expected = str(step["expected"])
                    comparison = str(step["comparison"])
                    verified = (
                        actual == expected
                        if comparison == "equals"
                        else expected in actual
                    )
                    record["verified"] = verified
                    if not verified:
                        results.append(record)
                        return CapabilityResult(
                            status=CapabilityStatus.FAILED,
                            capability_key=self.capability_key,
                            operation=prepared.request.operation,
                            data={"steps": results, "verification_passed": False},
                            reason="post-action verification did not match expected state",
                            elapsed_ms=(time.monotonic() - started) * 1000,
                            provenance=("Microsoft winapp UI Automation",),
                        )
                results.append(record)
        except (StructuredWindowsError, CapabilityExecutionError, ValueError) as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={"steps": results},
                reason=str(exc),
                elapsed_ms=(time.monotonic() - started) * 1000,
                provenance=("Microsoft winapp UI Automation",),
            )

        verification_steps = [
            item for item in results if item["action"] == "verify_value"
        ]
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data={
                "app": app,
                "strategy": "structured_winapp",
                "steps": results,
                "verification_passed": bool(verification_steps)
                and all(bool(item.get("verified")) for item in verification_steps),
            },
            elapsed_ms=(time.monotonic() - started) * 1000,
            provenance=(
                "Microsoft winapp UI Automation",
                "JARVIS shell-free allowlisted launcher",
            ),
        )

    @staticmethod
    def _execute_step(
        ui: WinAppCliBackend,
        app: str,
        step: dict[str, Any],
    ) -> StructuredCommandResult:
        action = str(step["action"])
        if action == "wait_until_running":
            return ui.wait_until_running(
                app,
                timeout_seconds=float(step["timeout_seconds"]),
            )
        if action == "inspect":
            return ui.inspect(
                app,
                selector=step.get("selector"),
                depth=int(step["depth"]),
                interactive=bool(step["interactive"]),
            )
        if action == "search":
            return ui.search(
                app,
                str(step["query"]),
                max_results=int(step["max_results"]),
            )
        if action in {"get_value", "verify_value"}:
            return ui.get_value(app, str(step["selector"]))
        if action == "focus":
            return ui.focus(app, str(step["selector"]))
        if action == "click":
            return ui.click(
                app,
                str(step["selector"]),
                double=bool(step["double"]),
                right=bool(step["right"]),
            )
        if action == "invoke":
            return ui.invoke(app, str(step["selector"]))
        if action == "send_text":
            selector = step.get("selector")
            return ui.send_text(
                app,
                str(step["text"]),
                target_selector=str(selector) if selector is not None else None,
            )
        if action == "set_value":
            return ui.set_value(
                app,
                str(step["selector"]),
                str(step["text"]),
            )
        if action == "wait_for":
            return ui.wait_for(
                app,
                str(step["selector"]),
                timeout_seconds=float(step["timeout_seconds"]),
                gone=bool(step["gone"]),
            )
        raise CapabilityExecutionError(f"unsupported structured action: {action}")


class VisualDesktopControlExecutor:
    """Explicit opt-in Gemini/OpenAI visual fallback behind the same authority path."""

    capability_key = "visual:desktop.control"
    operations = ("execute_visual_desktop_task",)

    def __init__(
        self,
        *,
        provider_name: str,
        enabled: bool = False,
        provider_factory: Callable[..., Any] = build_computer_use_provider,
        executor_factory: Callable[[], Any] = MssPyAutoGuiExecutor,
    ) -> None:
        self._provider_name = str(provider_name).strip().casefold()
        self._enabled = bool(enabled and platform.system() == "Windows")
        self._provider_factory = provider_factory
        self._executor_factory = executor_factory
        self.descriptor = CapabilityDescriptor.create(
            capability_id="desktop.control",
            source_id="visual",
            kind=CapabilityKind.VISUAL_FALLBACK,
            name="Governed Visual Desktop Fallback",
            description=(
                "Explicit opt-in screenshot-based desktop control fallback using the "
                "active cloud provider's computer-use model."
            ),
            operations=self.operations,
            metadata={
                "provider": self._provider_name,
                "explicit_opt_in": True,
                "browser_control": False,
            },
            execution_enabled=self._enabled,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation != "execute_visual_desktop_task":
            raise ValueError("unsupported visual desktop operation")
        app = _normalize_app(request.parameters.get("app"))
        task = _normalize_task(request.parameters.get("task"))
        lowered = task.casefold()
        blocked = [term for term in _VISUAL_BLOCKED_TERMS if term in lowered]
        if blocked:
            raise ValueError(
                "visual fallback task crosses the bounded desktop-control scope: "
                + ",".join(sorted(set(blocked)))
            )
        return PreparedCapability(
            request=request,
            target={"app": app, "strategy": "visual_fallback"},
            parameters={"app": app, "task": task},
            material_summary=f"Visually control {app} to perform: {task}",
            attributes=ActionAttributes(
                private_read=True,
                reversible_local_change=True,
                scope=ActionScope.LIMITED,
            ),
            execution_payload={"app": app, "task": task},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        if not self._enabled:
            return CapabilityResult(
                status=CapabilityStatus.UNAVAILABLE,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={},
                reason=(
                    "visual desktop fallback is disabled; set "
                    "JARVIS_VISUAL_COMPUTER_USE_ENABLED=true after installing "
                    "jarvis[computer-use]"
                ),
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        app = str(prepared.execution_payload["app"])
        task = str(prepared.execution_payload["task"])
        try:
            ui = WinAppCliBackend()
            launcher = AllowlistedWindowsLauncher()
            existing = ui.status(app, check=False)
            if int(existing.payload.get("exit_code", 1)) != 0:
                launcher.launch(app)
                ui.wait_until_running(app, timeout_seconds=6.0)
            provider = self._provider_factory(self._provider_name)
            executor = self._executor_factory()
            service = ComputerUseService(
                provider=provider,
                executor=executor,
                max_steps=8,
            )
            bounded_prompt = (
                f"Operate only inside the local Windows application {app!r}. "
                "Do not interact with any browser, terminal, File Explorer, security "
                "settings, credential field, or other application. Do not save, send, "
                f"delete, install, or download anything. User task: {task}"
            )
            result = asyncio.run(service.execute(bounded_prompt))
        except Exception as exc:  # noqa: BLE001 - optional SDK/input backend errors vary.
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={},
                reason=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        status = CapabilityStatus.SUCCEEDED if result.ok else CapabilityStatus.FAILED
        return CapabilityResult(
            status=status,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data=result.to_tool_payload(),
            reason=result.reason,
            elapsed_ms=(time.monotonic() - started) * 1000,
            provenance=(f"{result.provider} computer use", "desktop screenshot loop"),
        )