"""Generic governed capability runtime for local reads and JARVIS Hands."""

from __future__ import annotations

import os
import time
from typing import Protocol

from jarvis.ai_provider import configured_ai_provider
from jarvis.authority.audit import AuditError
from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.authority_bridge import (
    AuthorizedCapability,
    CapabilityAuthorityBroker,
    CapabilityAuthorizationError,
)
from jarvis.capabilities.browser_playwright import BrowserPlanExecutor
from jarvis.capabilities.development_git import (
    DevelopmentGitError,
    DevelopmentGitExecutor,
)
from jarvis.capabilities.document_edits import DocumentEditExecutor
from jarvis.capabilities.execution import CapabilityExecutor
from jarvis.capabilities.local_reads import LocalProjectReadExecutor
from jarvis.capabilities.local_writes import (
    ApprovedWriteRootPolicy,
    LocalFileWriteExecutor,
    LocalWriteValidationError,
)
from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.capabilities.software_management import SoftwareManagementExecutor
from jarvis.capabilities.system_reads import SystemReadExecutor
from jarvis.capabilities.windows_control import (
    VisualDesktopControlExecutor,
    WindowsStructuredControlExecutor,
)
from jarvis.capabilities.windows_devices import (
    BluetoothControlExecutor,
    DisplayControlExecutor,
    PowerSessionExecutor,
)
from jarvis.capabilities.windows_native import (
    AppLifecycleExecutor,
    ClipboardExecutor,
    MediaPlaybackExecutor,
    SystemAudioExecutor,
    WindowManagementExecutor,
)
from jarvis.capabilities.windows_sources import WinAppCliSchemaSource, WindowsOdrSource
from jarvis.hands.models import ExecutionSubstrate
from jarvis.hands.registry import HandsCapabilityRegistry
from jarvis.machine_config import load_machine_settings


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
        hands_planner=None,
    ) -> None:
        self._executors = {executor.capability_key: executor for executor in executors}
        if len(self._executors) != len(executors):
            raise ValueError("capability executor keys must be unique")
        for executor in executors:
            descriptor = getattr(executor, "descriptor", None)
            if descriptor is None or descriptor.key != executor.capability_key:
                raise ValueError(
                    "capability executor key must exactly match its descriptor identity"
                )
        self._resolver = resolver
        self._authority = authority
        self._hands_registry = hands_registry or HandsCapabilityRegistry.default()
        self._hands_planner = hands_planner
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

    @property
    def hands_planner(self):
        return self._hands_planner

    def capability_for_operation(self, operation: str) -> str | None:
        normalized = str(operation).strip()
        candidates = tuple(
            key
            for key, executor in self._executors.items()
            if normalized in executor.operations
        )
        if not candidates:
            return None
        if len(candidates) == 1:
            descriptor = self.catalog.by_key(candidates[0])
            return (
                candidates[0]
                if descriptor is not None and descriptor.execution_enabled
                else None
            )

        semantic = self._hands_registry.operation(normalized)
        if semantic is None:
            return None
        kind_to_substrate = {
            "semantic_connector": ExecutionSubstrate.DEDICATED_INTEGRATION,
            "native_api": ExecutionSubstrate.NATIVE_API,
            "structured_automation": ExecutionSubstrate.STRUCTURED_AUTOMATION,
            "visual_fallback": ExecutionSubstrate.VISUAL_FALLBACK,
            "local_read": ExecutionSubstrate.NATIVE_API,
        }
        preference = {
            substrate: index
            for index, substrate in enumerate(semantic.preferred_substrates)
        }
        ranked: list[tuple[int, str]] = []
        for key in candidates:
            descriptor = self.catalog.by_key(key)
            if descriptor is None or not descriptor.execution_enabled:
                continue
            substrate = kind_to_substrate.get(descriptor.kind.value)
            if substrate in preference:
                ranked.append((preference[substrate], key))
        if not ranked:
            return None
        ranked.sort()
        best_rank = ranked[0][0]
        best = [key for rank, key in ranked if rank == best_rank]
        return best[0] if len(best) == 1 else None

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
        try:
            for executor in self._executors.values():
                close = getattr(executor, "close", None)
                if not callable(close):
                    continue
                try:
                    close()
                except Exception:  # noqa: BLE001,S110 - shutdown must continue across adapters
                    pass
        finally:
            self._authority.close()


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def build_default_capability_runtime(
    *,
    ai_provider: str | None = None,
    hands_planner_model: str | None = None,
) -> CapabilityRuntime:
    project = LocalProjectReadExecutor()
    system = SystemReadExecutor()
    audio = SystemAudioExecutor()
    media = MediaPlaybackExecutor()
    clipboard = ClipboardExecutor()
    windows = WindowManagementExecutor()
    app_lifecycle = AppLifecycleExecutor()
    structured_control = WindowsStructuredControlExecutor()
    visual_provider = ai_provider or configured_ai_provider(load_machine_settings())
    visual_control = VisualDesktopControlExecutor(
        provider_name=visual_provider,
        enabled=_env_enabled("JARVIS_VISUAL_COMPUTER_USE_ENABLED"),
    )
    display = DisplayControlExecutor()
    bluetooth = BluetoothControlExecutor()
    power = PowerSessionExecutor()
    software = SoftwareManagementExecutor()

    executors: list[CapabilityExecutor] = [
        project,
        system,
        audio,
        media,
        clipboard,
        windows,
        app_lifecycle,
        structured_control,
        visual_control,
        display,
        bluetooth,
        power,
        software,
    ]

    write_roots: ApprovedWriteRootPolicy | None = None
    try:
        write_roots = ApprovedWriteRootPolicy()
    except LocalWriteValidationError:
        pass
    if write_roots is not None:
        executors.extend(
            (
                LocalFileWriteExecutor(write_roots),
                DocumentEditExecutor(write_roots),
            )
        )
    executors.append(BrowserPlanExecutor(write_roots=write_roots))

    try:
        executors.append(DevelopmentGitExecutor())
    except DevelopmentGitError:
        pass

    executor_tuple = tuple(executors)
    builtins = tuple(executor.descriptor for executor in executor_tuple)
    resolver = CapabilityResolver(
        (WinAppCliSchemaSource(), WindowsOdrSource()),
        builtins=builtins,
    )
    hands_planner = None
    if ai_provider is not None:
        from jarvis.hands.planner import build_hands_planner

        hands_planner = build_hands_planner(
            provider=ai_provider,
            model=hands_planner_model,
        )
    return CapabilityRuntime(
        executors=executor_tuple,
        resolver=resolver,
        authority=CapabilityAuthorityBroker(),
        hands_registry=HandsCapabilityRegistry.default(),
        hands_planner=hands_planner,
    )
