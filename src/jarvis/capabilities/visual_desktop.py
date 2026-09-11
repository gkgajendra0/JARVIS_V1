"""Governed generic visual fallback for arbitrary Windows application workflows."""

from __future__ import annotations

import asyncio
import platform
import re
import time
from collections.abc import Callable
from typing import Any

from jarvis.authority.types import ActionAttributes, ActionScope
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capabilities.window_scoped_computer import WindowScopedComputerExecutor
from jarvis.computer.latency_provider import build_latency_computer_use_provider
from jarvis.computer.service import ComputerUseService
from jarvis.hands.app_catalog import validate_app_name

_MAX_TASK_CHARACTERS = 1_500
_SECRET_LIKE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_ -]?key|password|token|secret)\s*[:=])"
)
_BROWSER_APPS = frozenset(
    {
        "chrome",
        "google chrome",
        "edge",
        "microsoft edge",
        "firefox",
        "mozilla firefox",
    }
)
_FORBIDDEN_TARGET_APPS = frozenset(
    {
        "file explorer",
        "explorer",
        "powershell",
        "windows powershell",
        "terminal",
        "windows terminal",
        "command prompt",
        "cmd",
        "registry editor",
        "regedit",
        "settings",
        "windows settings",
    }
)
_CRITICAL_INTENT_TERMS = (
    "run as administrator",
    "administrator permission",
    "security permission",
    "change permission",
    "registry",
    "regedit",
    "powershell",
    "terminal",
    "command prompt",
    "cmd.exe",
    "install ",
    "uninstall ",
    "delete ",
    "permanently delete",
    "erase ",
    "factory reset",
    "format drive",
    "password",
    "credential",
    "api key",
    "access token",
    "secret key",
)


def _normalize_task(value: object) -> str:
    task = " ".join(str(value).split())
    if not task:
        raise ValueError("visual desktop task must not be empty")
    if len(task) > _MAX_TASK_CHARACTERS:
        raise ValueError("visual desktop task exceeds bounded input limit")
    if _SECRET_LIKE.search(task):
        raise ValueError("visual desktop task appears to contain credential material")
    return task


def _normalized(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


class GovernedVisualDesktopExecutor:
    """Last-resort app-window Computer Use behind deterministic Authority.

    Generic visual interaction has unknown side-effect semantics, so JARVIS assigns a
    deterministic CRITICAL authority floor before the provider sees a screenshot. One
    strongly authorized visual goal may still execute a bounded sequence of app-local
    actions. The model never chooses its own risk class. Explicit critical/destructive,
    system and credential intents remain outside this generic substrate entirely.
    """

    capability_key = "visual:desktop.control"
    operations = ("execute_visual_desktop_task",)

    def __init__(
        self,
        *,
        provider_name: str,
        enabled: bool = False,
        provider_factory: Callable[..., Any] = build_latency_computer_use_provider,
        executor_factory: Callable[[str], Any] = WindowScopedComputerExecutor,
    ) -> None:
        self._provider_name = str(provider_name).strip().casefold()
        self._enabled = bool(enabled and platform.system() == "Windows")
        self._provider_factory = provider_factory
        self._executor_factory = executor_factory
        self.descriptor = CapabilityDescriptor.create(
            capability_id="desktop.control",
            source_id="visual",
            kind=CapabilityKind.VISUAL_FALLBACK,
            name="Governed Window-Scoped Visual Desktop Fallback",
            description=(
                "Last-resort provider-backed Computer Use constrained to one target "
                "application window and the canonical JARVIS Authority path."
            ),
            operations=self.operations,
            metadata={
                "provider": self._provider_name,
                "explicit_opt_in": True,
                "window_scoped": True,
                "whole_desktop_control": False,
                "browser_control": False,
                "raw_shell": False,
                "authority_floor": "critical",
            },
            execution_enabled=self._enabled,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation != "execute_visual_desktop_task":
            raise ValueError("unsupported visual desktop operation")
        app = validate_app_name(request.parameters.get("app", ""))
        task = _normalize_task(request.parameters.get("task"))
        normalized_app = _normalized(app)
        if normalized_app in _BROWSER_APPS:
            raise ValueError(
                "browser interaction belongs to the dedicated Playwright capability"
            )
        if normalized_app in _FORBIDDEN_TARGET_APPS:
            raise ValueError(
                "this application requires a dedicated governed capability rather "
                "than generic visual fallback"
            )
        lowered = f" {task.casefold()} "
        blocked = [term.strip() for term in _CRITICAL_INTENT_TERMS if term in lowered]
        if blocked:
            raise ValueError(
                "visual fallback task crosses a critical/destructive scope that "
                "requires a dedicated governed capability: "
                + ",".join(sorted(set(blocked)))
            )
        return PreparedCapability(
            request=request,
            target={"app": app, "strategy": "window_scoped_visual_fallback"},
            parameters={"app": app, "task": task},
            material_summary=f"Visually operate {app} to perform: {task}",
            attributes=ActionAttributes(
                private_read=True,
                persistent_write=True,
                external_side_effect=True,
                generic_visual_control=True,
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
                    "window-scoped visual desktop fallback is disabled; enable it in "
                    "the persisted JARVIS machine profile before use"
                ),
                elapsed_ms=(time.monotonic() - started) * 1000,
            )

        app = str(prepared.execution_payload["app"])
        task = str(prepared.execution_payload["task"])
        try:
            provider = self._provider_factory(self._provider_name)
            executor = self._executor_factory(app)
            service = ComputerUseService(
                provider=provider,
                executor=executor,
                max_steps=10,
            )
            bounded_prompt = (
                f"Operate only inside the currently authorized Windows application "
                f"window {app!r}. The local executor will reject input outside that "
                "window. Complete only the user's stated task. When several safe "
                "dependent actions are already grounded by the current screenshot, "
                "batch them in one computer action response when the provider supports "
                "it rather than pausing for a new model round-trip after every click. "
                "Normal app-local persistent or external actions explicitly requested "
                "by the user, such as save, export, send, share, print, upload, or "
                "download, are permitted by JARVIS Authority for this goal. Never "
                "switch to another application and never interact with terminals, "
                "registry, Windows security/permissions, credentials/secrets, software "
                "installation, or destructive deletion. "
                f"User task: {task}"
            )
            result = asyncio.run(service.execute(bounded_prompt))
        except Exception as exc:  # noqa: BLE001 - provider/input backend errors vary.
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={},
                reason=f"{type(exc).__name__}: visual desktop fallback failed",
                elapsed_ms=(time.monotonic() - started) * 1000,
            )

        data = result.to_tool_payload()
        data["verification_passed"] = result.ok
        data["window_scoped"] = True
        status = CapabilityStatus.SUCCEEDED if result.ok else CapabilityStatus.FAILED
        return CapabilityResult(
            status=status,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data=data,
            reason=result.reason or result.safety_message,
            elapsed_ms=(time.monotonic() - started) * 1000,
            provenance=(
                f"{result.provider} computer use",
                "target-window screenshot/input containment",
                "JARVIS canonical Authority",
            ),
        )
