"""Generic governed capability runtime for local reads and JARVIS Hands."""

from __future__ import annotations

import os
import time
from typing import Protocol

from jarvis.authority.audit import AuditError
from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.authority_bridge import (
    AuthorizedCapability,
    CapabilityAuthorityBroker,
    CapabilityAuthorizationError,
)
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.execution import CapabilityExecutor
from jarvis.capabilities.local_reads import LocalProjectReadExecutor
from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capabilities.system_reads import SystemReadExecutor
from jarvis.capabilities.windows_control import (
    VisualDesktopControlExecutor,
    WindowsStructuredControlExecutor,
)
from jarvis.capabilities.windows_native import (
    AppLifecycleExecutor,
    ClipboardExecutor,
    MediaPlaybackExecutor,
    SystemAudioExecutor,
    WindowManagementExecutor,
)
from jarvis.capabilities.windows_sources import WinAppCliSchemaSource, WindowsOdrSource
from jarvis.hands.registry import HandsCapabilityRegistry


class AuthorityBroker(Protocol):
    def authorize(self, prepared) -> AuthorizedCapability: ...

    def consume(self, authorized: AuthorizedCapability) -> None: ...

    def audit_result(
        self,
        *,
        session_id: str,
        authorized: AuthorizedCapability,
        result: CapabilityResult,
    ) -> None: ...

    def close(self) -> None: ...


class CapabilityRuntime:
    """Resolve -> validate -> authorize -> revalidate -> execute -> audit."""

    def __init__(
        self,
        *,
        executors: tuple[CapabilityExecutor, ...],
        resolver: CapabilityResolver,
        authority: AuthorityBroker,
        hands_registry: HandsCapabilityRegistry | None = None,
    ) -> None:
        self._executors = {executor.capability_key: executor for executor in executors}
        if len(self._executors) != len(executors):
            raise ValueError("capability executor keys must be unique")
        self._resolver = resolver
        self._authority = authority
        self._hands_registry = hands_registry or HandsCapabilityRegistry.default()
        self._catalog: CapabilityCatalog | None = None

    def refresh_catalog(self) -> CapabilityCatalog:
        self._catalog = self._resolver.refresh()
        return self._catalog

    @property
    def catalog(self) -> CapabilityCatalog:
        return self._catalog or self.refresh_catalog()

    @property
    def hands_registry(self) -> HandsCapabilityRegistry:
        return self._hands_registry

    def capability_for_operation(self, operation: str) -> str | None:
        normalized = str(operation).strip()
        candidates = sorted(
            key
            for key, executor in self._executors.items()
            if normalized in executor.operations
        )
        return candidates[0] if len(candidates) == 1 else None

    def execute_operation(
        self,
        *,
        session_id: str,
        operation: str,
        parameters: dict,
        origin: ActionOrigin = ActionOrigin.DIRECT_USER,
    ) -> CapabilityResult:
        capability_key = self.capability_for_operation(operation)
        if capability_key is None:
            return CapabilityResult(
                status=CapabilityStatus.INVALID,
                capability_key="unresolved",
                operation=str(operation),
                data={},
                reason="operation does not resolve to exactly one governed capability",
            )
        return self.execute(
            CapabilityRequest(
                session_id=session_id,
                capability_key=capability_key,
                operation=operation,
                parameters=parameters,
                origin=origin,
            )
        )

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        started = time.monotonic()
        descriptor = self.catalog.by_key(request.capability_key)
        if descriptor is None:
            return self._failure(
                request,
                CapabilityStatus.UNAVAILABLE,
                started,
                "capability is not present in the current catalog",
            )
        executor = self._executors.get(request.capability_key)
        if executor is None:
            return self._failure(
                request,
                CapabilityStatus.DENIED,
                started,
                "capability is discovery-only or execution-disabled",
            )
        if not descriptor.execution_enabled:
            return self._failure(
                request,
                CapabilityStatus.UNAVAILABLE,
                started,
                "capability executor is unavailable on this machine",
            )
        if (
            request.operation not in descriptor.operations
            or request.operation not in executor.operations
        ):
            return self._failure(
                request,
                CapabilityStatus.INVALID,
                started,
                "operation is not registered for this capability",
            )
        try:
            prepared = executor.prepare(request)
        except (ValueError, TypeError) as exc:
            return self._failure(
                request,
                CapabilityStatus.INVALID,
                started,
                str(exc),
            )
        try:
            authorized = self._authority.authorize(prepared)
            self._authority.consume(authorized)
        except CapabilityAuthorizationError as exc:
            return self._failure(
                request,
                CapabilityStatus.DENIED,
                started,
                str(exc),
            )
        result = executor.execute(prepared)
        try:
            self._authority.audit_result(
                session_id=request.session_id,
                authorized=authorized,
                result=result,
            )
        except AuditError:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=result.capability_key,
                operation=result.operation,
                data={},
                reason="capability result audit failed; result withheld",
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )
        return result

    @staticmethod
    def _failure(
        request: CapabilityRequest,
        status: CapabilityStatus,
        started: float,
        reason: str,
    ) -> CapabilityResult:
        return CapabilityResult(
            status=status,
            capability_key=request.capability_key,
            operation=request.operation,
            data={},
            reason=reason,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )

    def close(self) -> None:
        self._authority.close()


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def build_default_capability_runtime(
    *,
    ai_provider: str | None = None,
) -> CapabilityRuntime:
    project = LocalProjectReadExecutor()
    system = SystemReadExecutor()
    audio = SystemAudioExecutor()
    media = MediaPlaybackExecutor()
    clipboard = ClipboardExecutor()
    windows = WindowManagementExecutor()
    app_lifecycle = AppLifecycleExecutor()
    structured_control = WindowsStructuredControlExecutor()
    visual_control = VisualDesktopControlExecutor(
        provider_name=ai_provider or os.getenv("JARVIS_AI_PROVIDER", "gemini"),
        enabled=_env_enabled("JARVIS_VISUAL_COMPUTER_USE_ENABLED"),
    )
    executors: tuple[CapabilityExecutor, ...] = (
        project,
        system,
        audio,
        media,
        clipboard,
        windows,
        app_lifecycle,
        structured_control,
        visual_control,
    )
    builtins = tuple(executor.descriptor for executor in executors)
    resolver = CapabilityResolver(
        (WinAppCliSchemaSource(), WindowsOdrSource()),
        builtins=builtins,
    )
    return CapabilityRuntime(
        executors=executors,
        resolver=resolver,
        authority=CapabilityAuthorityBroker(),
        hands_registry=HandsCapabilityRegistry.default(),
    )
