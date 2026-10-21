"""Generic governed capability runtime for local reads and JARVIS Hands."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Protocol

from jarvis.ai_provider import configured_ai_provider
from jarvis.authority.audit import AuditError
from jarvis.authority.types import ActionAttributes, ActionOrigin
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
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.document_edits import DocumentEditExecutor
from jarvis.capabilities.execution import CapabilityExecutor, PreparedCapability
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
from jarvis.capabilities.visual_desktop import GovernedVisualDesktopExecutor
from jarvis.capabilities.windows_control import WindowsStructuredControlExecutor
from jarvis.capabilities.windows_devices import (
    BluetoothControlExecutor,
    DisplayControlExecutor,
    PowerSessionExecutor,
)
from jarvis.capabilities.windows_focus import ReliableWindowManagementExecutor
from jarvis.capabilities.windows_native import (
    AppLifecycleExecutor,
    ClipboardExecutor,
    MediaPlaybackExecutor,
    SystemAudioExecutor,
)
from jarvis.capabilities.windows_sources import WinAppCliSchemaSource, WindowsOdrSource
from jarvis.hands.models import ExecutionSubstrate
from jarvis.hands.registry import HandsCapabilityRegistry
from jarvis.machine_config import configured_text, load_machine_settings

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


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


class CapabilityResultObserver(Protocol):
    def __call__(self, result: CapabilityResult) -> None: ...


class CapabilityCatalogProjection(Protocol):
    """Optional in-process lifecycle projection on the governed runtime hot path."""

    def project(self, catalog: CapabilityCatalog) -> CapabilityCatalog: ...

    def allows(self, capability_key: str) -> bool: ...


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
        result_observer: CapabilityResultObserver | None = None,
        catalog_projection: CapabilityCatalogProjection | None = None,
        close_callbacks: tuple[Callable[[], None], ...] = (),
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
        self._result_observer = result_observer
        self._catalog_projection = catalog_projection
        self._close_callbacks = tuple(close_callbacks)
        if any(not callable(callback) for callback in self._close_callbacks):
            raise TypeError("close_callbacks must contain callable values")
        self._catalog: CapabilityCatalog | None = None

    def authorize_personal_context(
        self,
        *,
        session_id: str,
        turn_id: str,
        question: str,
        operation: str = "read",
        mutation: dict[str, object] | None = None,
    ) -> AuthorizedCapability:
        """Fixed canonical personal-memory scope; never model-supplied authority."""
        if operation not in {"read", "remember", "correct", "forget"}:
            raise ValueError("unsupported personal context operation")
        if operation != "read" and mutation is None:
            raise ValueError("a concrete memory change is required")
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question.encode("utf-8")) > 8000
        ):
            raise ValueError("personal context requires a bounded accepted question")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise ValueError("personal context requires a canonical turn id")
        authorize = getattr(self._authority, "authorize_fresh_owner", None)
        if not callable(authorize):
            raise CapabilityAuthorizationError("exact owner consent is unavailable")
        parameters = {
            "turn_id": turn_id,
            "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            "max_facts": 4,
        }
        summary = f"{operation.title()} owner memory for this request: {json.dumps(question, ensure_ascii=False)[:500]}"
        if mutation is not None:
            if operation == "read" or set(mutation) != {
                "predicate",
                "assertion_id",
                "value",
                "sensitivity",
            }:
                raise ValueError("invalid concrete memory change")
            predicate, target_id, value = (
                mutation["predicate"],
                mutation["assertion_id"],
                mutation["value"],
            )
            if (
                not isinstance(predicate, str)
                or not predicate.strip()
                or len(predicate) > 96
                or mutation["sensitivity"] not in {"standard", "private", "local_only"}
                or (
                    operation != "remember"
                    and (
                        not isinstance(target_id, str)
                        or not target_id
                        or len(target_id) > 128
                    )
                )
                or (operation == "remember" and target_id is not None)
                or (operation == "forget" and value is not None)
                or (
                    operation != "forget"
                    and (
                        not isinstance(value, str)
                        or not value.strip()
                        or len(value.encode("utf-8")) > 1800
                    )
                )
            ):
                raise ValueError("invalid concrete memory change")
            encoded = json.dumps(
                mutation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            parameters["mutation_sha256"] = hashlib.sha256(
                encoded.encode("utf-8")
            ).hexdigest()
            # The owner reviews the actual resolved target and value; audit gets
            # the digest only. A model-proposed intent is never a write permit.
            summary = f"{operation.title()} memory {json.dumps(predicate, ensure_ascii=False)}"
            if operation != "forget":
                summary += f" to {json.dumps(value, ensure_ascii=False)}"
            summary += f". Request: {json.dumps(question, ensure_ascii=False)[:500]}"
        request = CapabilityRequest(
            session_id=session_id,
            capability_key="memory:personal_context",
            operation=operation,
            parameters=parameters,
            origin=ActionOrigin.DIRECT_USER,
        )
        prepared = PreparedCapability(
            request=request,
            target={"subject_scope": "personal", "subject": "owner"},
            parameters=parameters,
            material_summary=summary,
            attributes=ActionAttributes(
                private_read=True,
                persistent_write=operation != "read",
                destructive=operation == "forget",
            ),
            execution_payload={},
        )
        return authorize(prepared)

    @property
    def personal_learning_authority(self):
        from jarvis.authority.personal_learning import PersonalLearningAuthority

        issuer = getattr(self, "_personal_learning_authority", None)
        if issuer is None:
            if not isinstance(self._authority, CapabilityAuthorityBroker):
                raise CapabilityAuthorizationError("learning authority is unavailable")
            issuer = PersonalLearningAuthority(self._authority)
            self._personal_learning_authority = issuer
        return issuer

    def open_personal_learning(self, runtime_id: str, provider: str):
        return self.personal_learning_authority.open(runtime_id, provider)

    def close_personal_learning(self, grant) -> None:
        self.personal_learning_authority.revoke(grant)

    def consume_personal_context(self, authorized: AuthorizedCapability) -> None:
        self._authority.consume(authorized)

    def validate_personal_context(self, authorized: AuthorizedCapability) -> None:
        validate = getattr(self._authority, "validate_binding", None)
        if not callable(validate):
            raise CapabilityAuthorizationError(
                "personal context continuity is unavailable"
            )
        validate(authorized)

    def invalidate_personal_context(self, session_id: str) -> None:
        invalidate = getattr(self._authority, "invalidate_session", None)
        if callable(invalidate):
            invalidate(session_id)

    def _routing_allowed(self, capability_key: str) -> bool:
        if self._catalog_projection is None:
            return True
        return self._catalog_projection.allows(capability_key)

    def refresh_catalog(self) -> CapabilityCatalog:
        catalog = self._resolver.refresh()
        if self._catalog_projection is not None:
            catalog = self._catalog_projection.project(catalog)
        self._catalog = catalog
        return catalog

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
                if (
                    descriptor is not None
                    and descriptor.execution_enabled
                    and self._routing_allowed(candidates[0])
                )
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
            if (
                descriptor is None
                or not descriptor.execution_enabled
                or not self._routing_allowed(key)
            ):
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
            return self._record_result(
                CapabilityResult(
                    status=CapabilityStatus.INVALID,
                    capability_key="unresolved",
                    operation=str(operation),
                    data={},
                    reason="operation does not resolve to exactly one governed capability",
                )
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
        if not self._routing_allowed(request.capability_key):
            return self._failure(
                request,
                CapabilityStatus.UNAVAILABLE,
                started,
                "capability routing is blocked by lifecycle projection",
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
            return self._record_result(
                CapabilityResult(
                    status=CapabilityStatus.FAILED,
                    capability_key=result.capability_key,
                    operation=result.operation,
                    data={},
                    reason="capability result audit failed; result withheld",
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                )
            )
        return self._record_result(result)

    def _record_result(self, result: CapabilityResult) -> CapabilityResult:
        if self._result_observer is None:
            return result
        try:
            self._result_observer(result)
        except Exception:  # noqa: BLE001,S110 - diagnostics must not break execution
            pass
        return result

    def _failure(
        self,
        request: CapabilityRequest,
        status: CapabilityStatus,
        started: float,
        reason: str,
    ) -> CapabilityResult:
        return self._record_result(
            CapabilityResult(
                status=status,
                capability_key=request.capability_key,
                operation=request.operation,
                data={},
                reason=reason,
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )
        )

    def close(self) -> None:
        try:
            for callback in self._close_callbacks:
                try:
                    callback()
                except Exception:  # noqa: BLE001,S110 - shutdown must continue
                    pass
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


def _visual_computer_use_enabled(configured: bool | None) -> bool:
    if configured is not None:
        return bool(configured)
    machine = load_machine_settings()
    raw = configured_text("JARVIS_VISUAL_COMPUTER_USE_ENABLED", machine, "false")
    return bool(raw and raw.strip().casefold() in _TRUE_VALUES)


def build_default_capability_runtime(
    *,
    ai_provider: str | None = None,
    hands_planner_model: str | None = None,
    chatgpt_plan_enabled: bool = False,
    chatgpt_plan_model: str | None = None,
    visual_computer_use_enabled: bool | None = None,
    result_observer: CapabilityResultObserver | None = None,
    extra_executors: tuple[CapabilityExecutor, ...] = (),
    catalog_projection: CapabilityCatalogProjection | None = None,
    close_callbacks: tuple[Callable[[], None], ...] = (),
) -> CapabilityRuntime:
    project = LocalProjectReadExecutor()
    system = SystemReadExecutor()
    audio = SystemAudioExecutor()
    media = MediaPlaybackExecutor()
    clipboard = ClipboardExecutor()
    windows = ReliableWindowManagementExecutor()
    app_lifecycle = AppLifecycleExecutor()
    structured_control = WindowsStructuredControlExecutor()
    visual_provider = ai_provider or configured_ai_provider(load_machine_settings())
    visual_control = GovernedVisualDesktopExecutor(
        provider_name=visual_provider,
        enabled=_visual_computer_use_enabled(visual_computer_use_enabled),
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
    executors.extend(extra_executors)

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
            chatgpt_plan_enabled=chatgpt_plan_enabled,
            chatgpt_plan_model=chatgpt_plan_model,
        )
    return CapabilityRuntime(
        executors=executor_tuple,
        resolver=resolver,
        authority=CapabilityAuthorityBroker(),
        hands_registry=HandsCapabilityRegistry.default(),
        hands_planner=hands_planner,
        result_observer=result_observer,
        catalog_projection=catalog_projection,
        close_callbacks=close_callbacks,
    )
