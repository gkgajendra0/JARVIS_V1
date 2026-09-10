"""Goal-oriented JARVIS Hands orchestration.

This module is the semantic boundary between natural conversation and governed
capability execution.  The realtime voice model only hands off the accepted USER goal.
A dedicated planner performs small-surface routing and typed one-action planning;
JARVIS then grounds entities/material, executes through canonical Authority, observes
the verified result, and repeats until the original goal is complete.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlparse

from number_parser import parse as parse_numbers

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.hands.app_catalog import AppCatalog, WindowsAppsFolderCatalog
from jarvis.hands.contracts import PlannedAction, PlannerTurn
from jarvis.hands.entities import AppEntityResolver, EntityResolutionError
from jarvis.hands.models import HandsOperation
from jarvis.hands.planner import HandsPlanningError, HandsRouteGroup

LOGGER = logging.getLogger(__name__)

_MAX_ACTIONS = 8
_MAX_OBSERVATION_CHARS = 5_000

_APP_OPERATIONS = {
    "open_app",
    "close_app",
    "focus_window",
    "maximize_window",
    "minimize_window",
    "restore_window",
    "move_window_to_next_monitor",
    "execute_windows_plan",
    "execute_visual_desktop_task",
}
_FILE_WRITE_OPERATIONS = {
    "create_text_file",
    "replace_text_file",
    "append_text_file",
    "make_directory",
    "copy_path",
    "move_path",
    "rename_path",
    "trash_path",
}
_DOCUMENT_OPERATIONS = {
    "create_docx",
    "append_docx_paragraph",
    "create_xlsx",
    "set_xlsx_cell",
    "create_pptx",
    "add_pptx_text_slide",
}
_POWER_OPERATIONS = {
    "lock_workstation",
    "sleep_workstation",
    "sign_out",
    "restart_workstation",
    "shutdown_workstation",
}

_ROUTE_GROUP_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "system_status",
        "Read machine health, utilization, processes and basic local status.",
        ("system_status", "list_processes"),
    ),
    (
        "audio",
        "Read or change Windows master volume and mute state.",
        (
            "get_master_volume",
            "set_master_volume",
            "mute_master_volume",
            "unmute_master_volume",
        ),
    ),
    (
        "media",
        "Inspect or control the current Windows media session: play, pause, next, previous, stop.",
        (
            "get_current_media",
            "play_media",
            "pause_media",
            "toggle_media_playback",
            "next_media",
            "previous_media",
            "stop_media",
        ),
    ),
    (
        "clipboard",
        "Read, set or clear Windows clipboard text.",
        ("get_clipboard_text", "set_clipboard_text", "clear_clipboard"),
    ),
    (
        "app_lifecycle",
        "Resolve installed Windows applications/games and open or gracefully close them.",
        ("open_app", "close_app"),
    ),
    (
        "app_ui",
        "Inspect and operate controls/content inside an already-running desktop application.",
        ("execute_windows_plan",),
    ),
    (
        "windows",
        "List, focus, maximize, minimize, restore or move application windows.",
        (
            "list_windows",
            "focus_window",
            "maximize_window",
            "minimize_window",
            "restore_window",
            "move_window_to_next_monitor",
        ),
    ),
    (
        "files_read",
        "Read/list/search bounded files and documents under approved local roots.",
        (
            "file_info",
            "list_directory",
            "list_project_files",
            "read_file",
            "read_document",
            "search_project",
        ),
    ),
    (
        "files_write",
        "Create/update/copy/move/rename/trash files or folders under approved write roots.",
        (
            "create_text_file",
            "replace_text_file",
            "append_text_file",
            "make_directory",
            "copy_path",
            "move_path",
            "rename_path",
            "trash_path",
        ),
    ),
    (
        "documents",
        "Create or edit DOCX, XLSX and PPTX files using semantic document libraries.",
        (
            "create_docx",
            "append_docx_paragraph",
            "create_xlsx",
            "set_xlsx_cell",
            "create_pptx",
            "add_pptx_text_slide",
        ),
    ),
    (
        "browser",
        "Navigate/read/interact with websites through structured Playwright browser automation.",
        ("execute_browser_plan",),
    ),
    (
        "display",
        "List displays or read/set display brightness.",
        ("list_displays", "get_display_brightness", "set_display_brightness"),
    ),
    (
        "bluetooth",
        "List, pair or unpair Windows Bluetooth devices.",
        (
            "list_bluetooth_devices",
            "pair_bluetooth_device",
            "unpair_bluetooth_device",
        ),
    ),
    (
        "power",
        "Lock, sleep, sign out, restart or shut down the Windows workstation.",
        (
            "lock_workstation",
            "sleep_workstation",
            "sign_out",
            "restart_workstation",
            "shutdown_workstation",
        ),
    ),
    (
        "software_discovery",
        "Search WinGet or list installed software without changing the machine.",
        ("search_software", "list_installed_software"),
    ),
    (
        "software_mutation",
        "Install or uninstall one exact WinGet package ID under critical authority.",
        ("install_package", "uninstall_package"),
    ),
    (
        "development_read",
        "Read Git repository status or active branch in an approved development repository.",
        ("git_status", "git_active_branch"),
    ),
    (
        "development_mutation",
        "Create/stage/commit/push bounded Git changes in an approved repository.",
        ("git_create_branch", "git_stage_paths", "git_commit", "git_push_current"),
    ),
    (
        "visual_fallback",
        "Owner-enabled screenshot-based computer use only when semantic desktop control cannot proceed.",
        ("execute_visual_desktop_task",),
    ),
)

_SAFE_RELATED_GROUPS: dict[str, tuple[str, ...]] = {
    "app_ui": ("app_lifecycle", "media", "windows"),
    "media": ("app_lifecycle", "app_ui", "audio"),
    "documents": ("files_read", "files_write"),
    "files_write": ("files_read",),
    "software_mutation": ("software_discovery",),
    "development_mutation": ("development_read",),
}


class HandsOrchestrationError(RuntimeError):
    pass


class HandsPlannerLike(Protocol):
    provider_name: str
    model_name: str

    async def route(
        self,
        *,
        goal: str,
        recent_user_turns: tuple[str, ...],
        route_groups: tuple[HandsRouteGroup, ...],
    ) -> tuple[str, ...]: ...

    async def next_action(
        self,
        *,
        goal: str,
        recent_user_turns: tuple[str, ...],
        candidate_operations: tuple[HandsOperation, ...],
        observations: tuple[dict[str, Any], ...],
    ) -> PlannerTurn: ...


@dataclass(frozen=True, slots=True)
class GroundingContext:
    latest_user_text: str
    recent_user_texts: tuple[str, ...]

    @property
    def all_texts(self) -> tuple[str, ...]:
        return (self.latest_user_text, *reversed(self.recent_user_texts))


@dataclass(frozen=True, slots=True)
class NormalizedAction:
    operation: str
    parameters: dict[str, Any]
    entity_trace: tuple[dict[str, str], ...] = ()


def _normalized(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _spoken_punctuation(value: object) -> str:
    text = str(value).casefold()
    for symbol, spoken in (
        ("\\", " backslash "),
        ("/", " slash "),
        ("_", " underscore "),
        ("-", " dash "),
        (".", " dot "),
    ):
        text = text.replace(symbol, spoken)
    return _normalized(text)


def _material_in_text(value: object, text: str) -> bool:
    material = _normalized(value)
    normalized_text = _normalized(text)
    if material and material in normalized_text:
        return True
    spoken = _spoken_punctuation(value)
    return bool(spoken) and spoken in normalized_text


def _require_material(
    value: object,
    context: GroundingContext,
    field: str,
    *,
    latest_only: bool = False,
) -> str:
    text = str(value or "").strip()
    sources = (
        (context.latest_user_text,)
        if latest_only
        else context.all_texts
    )
    if not text or not any(_material_in_text(text, source) for source in sources):
        raise HandsOrchestrationError(
            f"{field} is not grounded in the accepted USER conversation"
        )
    return text


def _evidence_grounded(evidence: str, latest_user_text: str) -> bool:
    evidence_text = _normalized(evidence)
    latest = _normalized(latest_user_text)
    return bool(evidence_text) and evidence_text in latest


def _numeric_values(text: str) -> tuple[float, ...]:
    try:
        parsed = parse_numbers(text)
    except Exception:  # noqa: BLE001 - optional normalization must fail closed
        parsed = text
    values: list[float] = []
    for match in re.findall(r"\b\d+(?:\.\d+)?\b", parsed):
        try:
            values.append(float(match))
        except ValueError:
            continue
    return tuple(values)


def _number_grounded(value: float, text: str) -> bool:
    return any(abs(float(value) - candidate) < 0.001 for candidate in _numeric_values(text))


def _url_grounded(value: object, context: GroundingContext) -> bool:
    url = str(value or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    return any(
        (host and _material_in_text(host, text)) or _material_in_text(url, text)
        for text in context.all_texts
    )


def _repo_grounded(repo: str, context: GroundingContext) -> bool:
    if any(_material_in_text(repo, text) for text in context.all_texts):
        return True
    if repo.casefold() != "jarvis":
        return False
    normalized = " ".join(_normalized(text) for text in context.all_texts)
    return any(
        marker in normalized
        for marker in ("your repo", "your repository", "this repo", "current repo")
    )


def _safe_preview(data: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(data, ensure_ascii=False, default=str)
    if len(encoded) <= _MAX_OBSERVATION_CHARS:
        return data
    return {"truncated": True, "preview": encoded[:_MAX_OBSERVATION_CHARS]}


def _fingerprint(operation: str, parameters: dict[str, Any]) -> str:
    payload = json.dumps(
        {"operation": operation, "parameters": parameters},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class HandsOrchestrator:
    """Route, plan, ground, authorize, execute, observe, and finish one USER goal."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        planner: HandsPlannerLike,
        *,
        app_catalog: AppCatalog | None = None,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        self._runtime = runtime
        self._planner = planner
        self._registry = runtime.hands_registry
        self._app_resolver = AppEntityResolver(app_catalog or WindowsAppsFolderCatalog())

    def _available_operations(self) -> tuple[HandsOperation, ...]:
        available: list[HandsOperation] = []
        catalog = self._runtime.catalog
        for operation in self._registry.operations:
            capability_key = self._runtime.capability_for_operation(operation.operation)
            descriptor = catalog.by_key(capability_key) if capability_key else None
            if descriptor is not None and descriptor.execution_enabled:
                available.append(operation)
        return tuple(available)

    def _route_groups(
        self, available_operations: tuple[HandsOperation, ...]
    ) -> tuple[HandsRouteGroup, ...]:
        by_name = {item.operation: item for item in available_operations}
        groups: list[HandsRouteGroup] = []
        for key, description, names in _ROUTE_GROUP_SPECS:
            operations = tuple(by_name[name] for name in names if name in by_name)
            if operations:
                groups.append(
                    HandsRouteGroup(
                        key=key,
                        description=description,
                        operations=operations,
                    )
                )
        return tuple(groups)

    @staticmethod
    def _candidate_operations(
        selected_keys: tuple[str, ...],
        route_groups: tuple[HandsRouteGroup, ...],
    ) -> tuple[HandsOperation, ...]:
        by_key = {group.key: group for group in route_groups}
        expanded: list[str] = list(selected_keys)
        for key in selected_keys:
            for related in _SAFE_RELATED_GROUPS.get(key, ()):
                if related in by_key and related not in expanded:
                    expanded.append(related)
        seen: set[str] = set()
        operations: list[HandsOperation] = []
        for key in expanded:
            group = by_key.get(key)
            if group is None:
                continue
            for operation in group.operations:
                if operation.operation not in seen:
                    seen.add(operation.operation)
                    operations.append(operation)
        return tuple(operations)

    def _normalize_app_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ) -> NormalizedAction:
        app_query = str(action.parameters.get("app") or "")
        resolved = self._app_resolver.resolve(
            app_query,
            latest_user_text=context.latest_user_text,
            recent_user_texts=context.recent_user_texts,
            evidence=action.evidence,
        )
        params = dict(action.parameters)
        params["app"] = resolved.display_name
        if action.operation == "execute_windows_plan":
            plan = params.get("plan")
            if not isinstance(plan, list) or not plan:
                raise HandsOrchestrationError("structured app UI plan is empty")
            for step in plan:
                if not isinstance(step, dict):
                    raise HandsOrchestrationError("structured app UI step is invalid")
                step_action = str(step.get("action") or "").casefold()
                if step_action == "search":
                    _require_material(step.get("query"), context, "app search content")
                elif step_action in {"send_text", "set_value"}:
                    _require_material(step.get("text"), context, "app typed text")
                elif step_action == "verify_value":
                    _require_material(
                        step.get("expected"), context, "app verification value"
                    )
            params = {
                "app": resolved.display_name,
                "task": context.latest_user_text,
                "plan": plan,
                "allow_existing_app": True,
            }
        elif action.operation == "execute_visual_desktop_task":
            params = {"app": resolved.display_name, "task": context.latest_user_text}
        else:
            params = {"app": resolved.display_name}
        return NormalizedAction(
            operation=action.operation,
            parameters=params,
            entity_trace=(resolved.payload(),),
        )

    def _normalize_file_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ) -> NormalizedAction:
        params = dict(action.parameters)
        operation = action.operation
        if operation in {"copy_path", "move_path"}:
            for key, label in (
                ("source_root", "source root"),
                ("source_path", "source path"),
                ("dest_root", "destination root"),
                ("dest_path", "destination path"),
            ):
                params[key] = _require_material(params.get(key), context, label)
            params["source_root"] = str(params["source_root"]).casefold()
            params["dest_root"] = str(params["dest_root"]).casefold()
        elif operation == "rename_path":
            params["root"] = _require_material(params.get("root"), context, "root").casefold()
            params["path"] = _require_material(params.get("path"), context, "path")
            params["new_path"] = _require_material(
                params.get("new_path"), context, "new path"
            )
        else:
            params["root"] = _require_material(params.get("root"), context, "root").casefold()
            params["path"] = _require_material(params.get("path"), context, "path")
            if operation in {
                "create_text_file",
                "replace_text_file",
                "append_text_file",
            }:
                params["text"] = _require_material(params.get("text"), context, "text")
        return NormalizedAction(operation=operation, parameters=params)

    def _normalize_document_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ) -> NormalizedAction:
        params = dict(action.parameters)
        params["root"] = _require_material(params.get("root"), context, "root").casefold()
        params["path"] = _require_material(params.get("path"), context, "document path")
        operation = action.operation
        if operation in {"create_docx", "append_docx_paragraph"}:
            params["text"] = _require_material(
                params.get("text"), context, "document text"
            )
        elif operation in {"create_pptx", "add_pptx_text_slide"}:
            params["title"] = _require_material(
                params.get("title"), context, "slide title"
            )
            body = str(params.get("body") or "")
            if body:
                params["body"] = _require_material(body, context, "slide body")
        elif operation == "create_xlsx":
            sheet = str(params.get("sheet") or "Sheet1")
            if sheet.casefold() != "sheet1":
                params["sheet"] = _require_material(sheet, context, "worksheet name")
        elif operation == "set_xlsx_cell":
            sheet = str(params.get("sheet") or "Sheet1")
            if sheet.casefold() != "sheet1":
                params["sheet"] = _require_material(sheet, context, "worksheet name")
            params["cell"] = _require_material(params.get("cell"), context, "cell")
            value = params.get("value")
            if value is not None and not any(
                _material_in_text(value, text) for text in context.all_texts
            ):
                raise HandsOrchestrationError(
                    "spreadsheet cell value is not grounded in the accepted USER conversation"
                )
        return NormalizedAction(operation=operation, parameters=params)

    def _normalize_browser_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ) -> NormalizedAction:
        params = dict(action.parameters)
        plan = params.get("plan")
        if not isinstance(plan, list) or not plan:
            raise HandsOrchestrationError("browser plan is empty")
        for step in plan:
            if not isinstance(step, dict):
                raise HandsOrchestrationError("browser plan step is invalid")
            step_action = str(step.get("action") or "").casefold()
            if step_action == "navigate" and not _url_grounded(step.get("url"), context):
                raise HandsOrchestrationError(
                    "browser URL is not grounded in the accepted USER conversation"
                )
            if step_action == "fill":
                _require_material(step.get("text"), context, "browser fill text")
            if step_action in {"download", "upload"}:
                step["root"] = _require_material(
                    step.get("root"), context, "browser file root"
                ).casefold()
                step["path"] = _require_material(
                    step.get("path"), context, "browser file path"
                )
        return NormalizedAction(operation=action.operation, parameters={"plan": plan})

    def _normalize_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ) -> NormalizedAction:
        self._registry.require(action.operation)
        if not _evidence_grounded(action.evidence, context.latest_user_text):
            raise HandsOrchestrationError(
                "planner action evidence is not verbatim-grounded in the latest USER turn"
            )
        if action.operation in _APP_OPERATIONS:
            return self._normalize_app_action(action, context)
        if action.operation == "set_master_volume":
            percent = float(action.parameters["percent"])
            if not _number_grounded(percent, context.latest_user_text):
                raise HandsOrchestrationError(
                    "volume percentage is not grounded in the latest USER turn"
                )
            return NormalizedAction(action.operation, {"percent": percent})
        if action.operation == "set_clipboard_text":
            return NormalizedAction(
                action.operation,
                {
                    "text": _require_material(
                        action.parameters.get("text"), context, "clipboard text"
                    )
                },
            )
        if action.operation in _FILE_WRITE_OPERATIONS:
            return self._normalize_file_action(action, context)
        if action.operation in _DOCUMENT_OPERATIONS:
            return self._normalize_document_action(action, context)
        if action.operation == "execute_browser_plan":
            return self._normalize_browser_action(action, context)
        if action.operation == "set_display_brightness":
            percent = int(action.parameters["percent"])
            if not _number_grounded(percent, context.latest_user_text):
                raise HandsOrchestrationError(
                    "brightness percentage is not grounded in the latest USER turn"
                )
            params: dict[str, Any] = {"percent": percent}
            display = action.parameters.get("display")
            if display:
                params["display"] = _require_material(display, context, "display target")
            return NormalizedAction(action.operation, params)
        if action.operation == "get_display_brightness":
            display = action.parameters.get("display")
            return NormalizedAction(
                action.operation,
                (
                    {"display": _require_material(display, context, "display target")}
                    if display
                    else {}
                ),
            )
        if action.operation in {"pair_bluetooth_device", "unpair_bluetooth_device"}:
            return NormalizedAction(
                action.operation,
                {
                    "name": _require_material(
                        action.parameters.get("name"), context, "Bluetooth device name"
                    )
                },
            )
        if action.operation in {"search_software", "list_installed_software"}:
            return NormalizedAction(
                action.operation,
                {
                    "query": _require_material(
                        action.parameters.get("query"), context, "software query"
                    )
                },
            )
        if action.operation in {"install_package", "uninstall_package"}:
            return NormalizedAction(
                action.operation,
                {
                    "package_id": _require_material(
                        action.parameters.get("package_id"),
                        context,
                        "exact WinGet package ID",
                        latest_only=True,
                    )
                },
            )
        if action.operation.startswith("git_"):
            repo = str(action.parameters.get("repo") or "").strip().casefold()
            if not repo or not _repo_grounded(repo, context):
                raise HandsOrchestrationError(
                    "development repository is not grounded in the accepted USER conversation"
                )
            params: dict[str, Any] = {"repo": repo}
            if action.operation == "git_create_branch":
                params["branch"] = _require_material(
                    action.parameters.get("branch"), context, "Git branch name"
                )
            elif action.operation == "git_stage_paths":
                paths = action.parameters.get("paths")
                if not isinstance(paths, list) or not paths:
                    raise HandsOrchestrationError("Git stage requires explicit paths")
                params["paths"] = [
                    _require_material(path, context, "Git path") for path in paths
                ]
            elif action.operation == "git_commit":
                params["message"] = _require_material(
                    action.parameters.get("message"),
                    context,
                    "Git commit message",
                    latest_only=True,
                )
            return NormalizedAction(action.operation, params)
        if action.operation in {"file_info", "read_file", "read_document"}:
            root = str(action.parameters.get("root") or "project").casefold()
            if root != "project":
                root = _require_material(root, context, "read root").casefold()
            path = _require_material(action.parameters.get("path"), context, "read path")
            return NormalizedAction(action.operation, {"root": root, "path": path})
        if action.operation in {"list_directory", "list_project_files"}:
            root = str(action.parameters.get("root") or "project").casefold()
            if root != "project":
                root = _require_material(root, context, "read root").casefold()
            path = str(action.parameters.get("path") or "")
            if path:
                path = _require_material(path, context, "read path")
            return NormalizedAction(
                action.operation,
                {
                    "root": root,
                    "path": path,
                    "max_results": int(action.parameters.get("max_results", 20)),
                },
            )
        if action.operation == "search_project":
            root = str(action.parameters.get("root") or "project").casefold()
            if root != "project":
                root = _require_material(root, context, "read root").casefold()
            path = str(action.parameters.get("path") or "")
            if path:
                path = _require_material(path, context, "read path")
            # Search text is a read-only implementation detail and may be semantically
            # derived from the USER's question. The executor still bounds its length.
            return NormalizedAction(
                action.operation,
                {
                    "root": root,
                    "path": path,
                    "query": str(action.parameters["query"]),
                    "max_results": int(action.parameters.get("max_results", 20)),
                },
            )
        if action.operation in _POWER_OPERATIONS or not action.parameters:
            return NormalizedAction(action.operation, {})
        return NormalizedAction(action.operation, dict(action.parameters))

    @staticmethod
    def _observation(
        action: NormalizedAction,
        result: CapabilityResult,
        *,
        step_number: int,
    ) -> dict[str, Any]:
        return {
            "step": step_number,
            "operation": action.operation,
            "status": result.status.value,
            "ok": result.ok,
            "reason": result.reason,
            "data": _safe_preview(result.data),
            "verified": bool(result.data.get("verification_passed", result.ok)),
        }

    async def execute_goal(
        self,
        *,
        session_id: str,
        goal: str,
        recent_user_turns: tuple[str, ...] = (),
    ) -> dict[str, object]:
        latest = str(goal).strip()
        if not latest:
            raise HandsOrchestrationError("Hands requires a non-empty accepted USER goal")
        context = GroundingContext(latest, recent_user_turns)
        available = self._available_operations()
        route_groups = self._route_groups(available)
        if not route_groups:
            raise HandsOrchestrationError("no executable Hands capabilities are available")

        try:
            selected = await self._planner.route(
                goal=latest,
                recent_user_turns=recent_user_turns,
                route_groups=route_groups,
            )
        except HandsPlanningError:
            raise
        candidates = self._candidate_operations(selected, route_groups)
        if not candidates:
            raise HandsOrchestrationError("Hands routing produced no executable operations")

        LOGGER.info(
            "Hands semantic route | provider=%s | model=%s | groups=%s | candidates=%s",
            self._planner.provider_name,
            self._planner.model_name,
            ",".join(selected),
            ",".join(item.operation for item in candidates),
        )

        observations: list[dict[str, Any]] = []
        results: list[CapabilityResult] = []
        entity_trace: list[dict[str, str]] = []
        attempted: set[str] = set()

        for step_number in range(1, _MAX_ACTIONS + 1):
            decision = await self._planner.next_action(
                goal=latest,
                recent_user_turns=recent_user_turns,
                candidate_operations=candidates,
                observations=tuple(observations),
            )
            if decision.clarification_question is not None:
                return {
                    "ok": False,
                    "status": "clarification_required",
                    "goal": latest,
                    "clarification_question": decision.clarification_question,
                    "completed_steps": len(results),
                    "route_groups": list(selected),
                    "observations": observations,
                }
            if decision.goal_complete:
                if not results:
                    raise HandsOrchestrationError(
                        "planner claimed goal completion without any verified execution"
                    )
                return {
                    "ok": True,
                    "status": "succeeded",
                    "goal": latest,
                    "completed_steps": len(results),
                    "route_groups": list(selected),
                    "results": [self._result_payload(item) for item in results],
                    "entity_trace": entity_trace,
                    "observations": observations,
                }
            action = decision.action
            if action is None:
                raise HandsOrchestrationError(
                    "planner returned neither an action, clarification, nor completion"
                )

            normalized = await asyncio.to_thread(
                self._normalize_action,
                action,
                context,
            )
            action_fingerprint = _fingerprint(
                normalized.operation, normalized.parameters
            )
            if action_fingerprint in attempted:
                raise HandsOrchestrationError(
                    "planner repeated an identical action instead of making progress"
                )
            attempted.add(action_fingerprint)
            entity_trace.extend(normalized.entity_trace)
            LOGGER.info(
                "Hands planned action | step=%s | operation=%s | parameter_keys=%s | "
                "entity_refs=%s",
                step_number,
                normalized.operation,
                ",".join(sorted(normalized.parameters)),
                len(normalized.entity_trace),
            )

            result = await asyncio.to_thread(
                self._runtime.execute_operation,
                session_id=session_id,
                operation=normalized.operation,
                parameters=normalized.parameters,
                origin=ActionOrigin.DIRECT_USER,
            )
            results.append(result)
            observation = self._observation(
                normalized,
                result,
                step_number=step_number,
            )
            observations.append(observation)
            LOGGER.info(
                "Hands execution observation | step=%s | operation=%s | status=%s | "
                "ok=%s | verified=%s",
                step_number,
                normalized.operation,
                result.status.value,
                result.ok,
                observation["verified"],
            )

            if result.ok:
                continue
            if result.status in {CapabilityStatus.INVALID, CapabilityStatus.UNAVAILABLE}:
                if "app_ui" in selected:
                    visual = next(
                        (group for group in route_groups if group.key == "visual_fallback"),
                        None,
                    )
                    if visual is not None and all(
                        item.operation != "execute_visual_desktop_task"
                        for item in candidates
                    ):
                        candidates = (*candidates, *visual.operations)
                continue
            return {
                "ok": False,
                "status": "failed",
                "goal": latest,
                "completed_steps": sum(item.ok for item in results),
                "failed_operation": normalized.operation,
                "reason": result.reason or result.status.value,
                "route_groups": list(selected),
                "results": [self._result_payload(item) for item in results],
                "entity_trace": entity_trace,
                "observations": observations,
            }

        return {
            "ok": False,
            "status": "max_steps_exceeded",
            "goal": latest,
            "completed_steps": sum(item.ok for item in results),
            "reason": f"Hands exceeded the bounded {_MAX_ACTIONS}-action goal loop",
            "route_groups": list(selected),
            "results": [self._result_payload(item) for item in results],
            "entity_trace": entity_trace,
            "observations": observations,
        }

    @staticmethod
    def _result_payload(result: CapabilityResult) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "status": result.status.value,
            "operation": result.operation,
            "capability": result.capability_key,
            "data": result.data,
            "reason": result.reason,
            "truncated": result.truncated,
            "provenance": list(result.provenance),
        }
