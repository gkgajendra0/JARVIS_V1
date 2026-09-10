"""Single voice-facing goal boundary for provider-neutral JARVIS Hands."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlparse

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.hands.models import HandsWorkflowStep
from jarvis.hands.registry import HandsCapabilityRegistry
from jarvis.hands.workflow import HandsWorkflowRunner

_MAX_PLAN_JSON_CHARS = 20_000
_MAX_APP_CHARS = 160


def _build_use_computer_schema() -> dict[str, object]:
    """Build the voice tool contract from the canonical Hands registry.

    The language model owns semantic interpretation of the user's goal. The schema
    constrains it to canonical JARVIS operation names; deterministic code below owns
    target/material grounding and canonical AuthorityService owns permission.
    """

    registry = HandsCapabilityRegistry.default()
    operations = list(registry.operations)
    operation_names = [item.operation for item in operations]
    operation_guide = "\n".join(
        f"- {item.operation}: {item.description}" for item in operations
    )
    return {
        "type": "function",
        "name": "use_computer",
        "description": (
            "Accomplish the latest USER computer goal through JARVIS Hands. "
            "Use this tool when the USER is asking JARVIS to operate the computer, "
            "regardless of conversational wording, language style, politeness, or word order. "
            "Do not call it for hypothetical discussion, explanations, capability questions, "
            "or a mere mention of an action. Translate the requested outcome into a short "
            "bounded semantic plan. Prefer native/semantic operations over UI, structured UI "
            "over visual fallback, and never invent material values. Available operations:\n"
            + operation_guide
            + "\nTo start/open/play a named installed local application or game, use open_app. "
            "Use search_software only for software/WinGet discovery or as a discovery step "
            "inside an explicit install request. Named songs/playlists/controls inside an app "
            "belong to execute_windows_plan; browser goals belong to execute_browser_plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": HandsWorkflowRunner.MAX_STEPS,
                    "description": "Bounded semantic operations required to achieve the latest USER goal.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": operation_names,
                                "description": "Canonical JARVIS Hands operation name.",
                            },
                            "parameters": {
                                "type": "object",
                                "description": (
                                    "Operation parameters. Material targets and values must come "
                                    "from the USER request or bounded conversation context; only "
                                    "implementation details such as semantic UI selectors may be inferred."
                                ),
                            },
                        },
                        "required": ["operation", "parameters"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
    }


_USE_COMPUTER_RAW_SCHEMA = _build_use_computer_schema()
_OPERATION_ALIASES = {
    "set_volume": "set_master_volume",
    "get_volume": "get_master_volume",
    "mute_volume": "mute_master_volume",
    "unmute_volume": "unmute_master_volume",
    "create_file": "create_text_file",
    "write_file": "create_text_file",
    "list_bluetooth": "list_bluetooth_devices",
    "get_bluetooth_devices": "list_bluetooth_devices",
    "winget_search": "search_software",
    "search_winget": "search_software",
    "software_search": "search_software",
    "git_repo_status": "git_status",
}
_CURRENT_TARGET_MARKERS = (
    "it",
    "this app",
    "that app",
    "this window",
    "that window",
    "current window",
    "already open",
    "already running",
)
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
_WINDOW_OPERATIONS = {
    "close_app",
    "focus_window",
    "maximize_window",
    "minimize_window",
    "restore_window",
    "move_window_to_next_monitor",
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
_DISPLAY_OPERATIONS = {
    "list_displays",
    "get_display_brightness",
    "set_display_brightness",
}
_BLUETOOTH_OPERATIONS = {
    "list_bluetooth_devices",
    "pair_bluetooth_device",
    "unpair_bluetooth_device",
}
_POWER_OPERATIONS = {
    "lock_workstation",
    "sleep_workstation",
    "sign_out",
    "restart_workstation",
    "shutdown_workstation",
}
_SOFTWARE_OPERATIONS = {
    "search_software",
    "list_installed_software",
    "install_package",
    "uninstall_package",
}
_DEVELOPMENT_OPERATIONS = {
    "git_status",
    "git_active_branch",
    "git_create_branch",
    "git_stage_paths",
    "git_commit",
    "git_push_current",
}


class HandsGoalGroundingError(ValueError):
    pass


def _normalized(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _spoken_punctuation_normalized(value: object) -> str:
    text = str(value).casefold()
    for symbol, spoken in (
        ("\\", " backslash "),
        ("/", " slash "),
        ("_", " underscore "),
        ("-", " dash "),
        (".", " dot "),
    ):
        text = text.replace(symbol, spoken)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    padded = f" {_normalized(text)} "
    return any(f" {_normalized(marker)} " in padded for marker in markers)


def _material_in_text(value: object, text: str) -> bool:
    material = _normalized(value)
    normalized_text = _normalized(text)
    if bool(material) and material in normalized_text:
        return True
    spoken_material = _spoken_punctuation_normalized(value)
    return bool(spoken_material) and spoken_material in normalized_text


def _require_material(value: object, user_text: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or not _material_in_text(text, user_text):
        raise HandsGoalGroundingError(
            f"{field} must be explicitly grounded in the latest user request"
        )
    return text


def _url_grounded(value: object, user_text: str) -> bool:
    url = str(value or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    if host and _material_in_text(host, user_text):
        return True
    return _material_in_text(url, user_text)


def _repo_grounded(repo: str, user_text: str) -> bool:
    if _material_in_text(repo, user_text):
        return True
    if repo.casefold() != "jarvis":
        return False
    return _contains_marker(
        user_text,
        ("your repo", "your repository", "this repo", "current repo", "the repo"),
    )


def _bounded_app(value: object) -> str:
    app = " ".join(str(value).split())
    if not app or len(app) > _MAX_APP_CHARS:
        raise HandsGoalGroundingError("app target must be a bounded non-empty name")
    return app


class HandsGoalAgentTools:
    """Expose one goal-oriented computer tool while keeping executors internal."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        conversation: ConversationSession,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._runtime = runtime
        self._conversation = conversation
        self._runner = HandsWorkflowRunner(runtime, registry=runtime.hands_registry)

    @property
    def tools(self) -> list:
        return [self.use_computer]

    def _latest_user_turn(self) -> ConversationTurn:
        turn = next(
            (
                candidate
                for candidate in reversed(self._conversation.turns)
                if candidate.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None:
            raise HandsGoalGroundingError(
                "JARVIS Hands requires a latest accepted user utterance"
            )
        return turn

    def _recently_grounded_app(self, app: str) -> bool:
        normalized_app = _normalized(app)
        if not normalized_app:
            return False
        for turn in reversed(self._conversation.turns[-8:]):
            if turn.role is ConversationRole.USER and normalized_app in _normalized(
                turn.text
            ):
                return True
        return False

    def _validate_app_target(
        self,
        *,
        app: str,
        user_text: str,
        apps_opened_in_plan: set[str],
        allow_context: bool,
    ) -> None:
        normalized_app = _normalized(app)
        if normalized_app in _normalized(user_text):
            return
        if normalized_app in apps_opened_in_plan:
            return
        if (
            allow_context
            and _contains_marker(user_text, _CURRENT_TARGET_MARKERS)
            and self._recently_grounded_app(app)
        ):
            return
        raise HandsGoalGroundingError(
            "model-selected app target is not grounded in the current or recent user request"
        )

    @staticmethod
    def _ground_file_parameters(
        operation: str, parameters: dict[str, Any], user_text: str
    ) -> dict[str, Any]:
        if operation in {"copy_path", "move_path"}:
            return {
                "source_root": _require_material(
                    parameters.get("source_root"), user_text, "source root"
                ).casefold(),
                "source_path": _require_material(
                    parameters.get("source_path"), user_text, "source path"
                ),
                "dest_root": _require_material(
                    parameters.get("dest_root"), user_text, "destination root"
                ).casefold(),
                "dest_path": _require_material(
                    parameters.get("dest_path"), user_text, "destination path"
                ),
                "overwrite": bool(parameters.get("overwrite", False)),
            }
        if operation == "rename_path":
            return {
                "root": _require_material(
                    parameters.get("root"), user_text, "root"
                ).casefold(),
                "path": _require_material(parameters.get("path"), user_text, "path"),
                "new_path": _require_material(
                    parameters.get("new_path"), user_text, "new path"
                ),
                "overwrite": bool(parameters.get("overwrite", False)),
            }
        grounded: dict[str, Any] = {
            "root": _require_material(
                parameters.get("root"), user_text, "root"
            ).casefold(),
            "path": _require_material(parameters.get("path"), user_text, "path"),
        }
        if operation in {"create_text_file", "replace_text_file", "append_text_file"}:
            grounded["text"] = _require_material(
                parameters.get("text"), user_text, "text"
            )
        return grounded

    @staticmethod
    def _ground_document_parameters(
        operation: str, parameters: dict[str, Any], user_text: str
    ) -> dict[str, Any]:
        grounded: dict[str, Any] = {
            "root": _require_material(
                parameters.get("root"), user_text, "root"
            ).casefold(),
            "path": _require_material(
                parameters.get("path"), user_text, "document path"
            ),
        }
        if operation in {"create_docx", "append_docx_paragraph"}:
            grounded["text"] = _require_material(
                parameters.get("text"), user_text, "document text"
            )
        elif operation in {"create_pptx", "add_pptx_text_slide"}:
            grounded["title"] = _require_material(
                parameters.get("title"), user_text, "slide title"
            )
            body = str(parameters.get("body") or "")
            if body:
                grounded["body"] = _require_material(body, user_text, "slide body")
            else:
                grounded["body"] = ""
        elif operation == "create_xlsx":
            sheet = str(parameters.get("sheet") or "").strip()
            if sheet:
                grounded["sheet"] = _require_material(
                    sheet, user_text, "worksheet name"
                )
        elif operation == "set_xlsx_cell":
            sheet = str(parameters.get("sheet") or "").strip()
            if sheet:
                grounded["sheet"] = _require_material(
                    sheet, user_text, "worksheet name"
                )
            grounded["cell"] = _require_material(
                parameters.get("cell"), user_text, "cell"
            )
            value = parameters.get("value")
            if value is None:
                if not _contains_marker(user_text, ("clear", "empty", "blank")):
                    raise HandsGoalGroundingError(
                        "clearing a spreadsheet cell must be explicit in the latest user request"
                    )
            elif not _material_in_text(value, user_text):
                raise HandsGoalGroundingError(
                    "spreadsheet cell value must be grounded in the latest user request"
                )
            grounded["value"] = value
        return grounded

    @staticmethod
    def _ground_browser_parameters(
        parameters: dict[str, Any], user_text: str
    ) -> dict[str, Any]:
        raw_plan = parameters.get("plan")
        if not isinstance(raw_plan, list) or not raw_plan:
            raise HandsGoalGroundingError("browser Hands requires a non-empty plan")
        plan: list[dict[str, Any]] = []
        for raw_step in raw_plan:
            if not isinstance(raw_step, dict):
                raise HandsGoalGroundingError("browser plan steps must be objects")
            step = dict(raw_step)
            action = str(step.get("action") or "").strip().casefold()
            if action == "navigate" and not _url_grounded(step.get("url"), user_text):
                raise HandsGoalGroundingError(
                    "browser URL must be grounded in the latest user request"
                )
            if action == "fill":
                _require_material(step.get("text"), user_text, "browser fill text")
            if action in {"download", "upload"}:
                step["root"] = _require_material(
                    step.get("root"), user_text, "browser file root"
                ).casefold()
                step["path"] = _require_material(
                    step.get("path"), user_text, "browser file path"
                )
            plan.append(step)
        return {"plan": plan}

    @staticmethod
    def _ground_device_parameters(
        operation: str, parameters: dict[str, Any], user_text: str
    ) -> dict[str, Any]:
        if operation == "set_display_brightness":
            percent = int(parameters.get("percent"))
            requested = [int(value) for value in re.findall(r"\b\d+\b", user_text)]
            if percent not in requested:
                raise HandsGoalGroundingError(
                    "brightness percentage must come directly from the latest user request"
                )
            grounded: dict[str, Any] = {"percent": percent}
            display = str(parameters.get("display") or "").strip()
            if display:
                grounded["display"] = _require_material(
                    display, user_text, "display target"
                )
            return grounded
        if operation == "get_display_brightness":
            display = str(parameters.get("display") or "").strip()
            return (
                {"display": _require_material(display, user_text, "display target")}
                if display
                else {}
            )
        if operation in {"pair_bluetooth_device", "unpair_bluetooth_device"}:
            return {
                "name": _require_material(
                    parameters.get("name"), user_text, "Bluetooth device name"
                )
            }
        return {}

    @staticmethod
    def _ground_software_parameters(
        operation: str, parameters: dict[str, Any], user_text: str
    ) -> dict[str, Any]:
        if operation in {"search_software", "list_installed_software"}:
            return {
                "query": _require_material(
                    parameters.get("query"), user_text, "software query"
                )
            }
        return {
            "package_id": _require_material(
                parameters.get("package_id"), user_text, "exact WinGet package ID"
            )
        }

    @staticmethod
    def _ground_development_parameters(
        operation: str, parameters: dict[str, Any], user_text: str
    ) -> dict[str, Any]:
        repo = str(parameters.get("repo") or "").strip().casefold()
        if not repo or not _repo_grounded(repo, user_text):
            raise HandsGoalGroundingError(
                "development repository must be grounded in the latest user request"
            )
        grounded: dict[str, Any] = {"repo": repo}
        if operation == "git_create_branch":
            grounded["branch"] = _require_material(
                parameters.get("branch"), user_text, "Git branch name"
            )
        elif operation == "git_stage_paths":
            paths = parameters.get("paths")
            if not isinstance(paths, list) or not paths:
                raise HandsGoalGroundingError("Git stage requires explicit paths")
            grounded["paths"] = [
                _require_material(path, user_text, "Git path") for path in paths
            ]
        elif operation == "git_commit":
            grounded["message"] = _require_material(
                parameters.get("message"), user_text, "Git commit message"
            )
        return grounded

    def _normalize_step(
        self,
        raw: object,
        *,
        user_text: str,
        apps_opened_in_plan: set[str],
    ) -> HandsWorkflowStep:
        if not isinstance(raw, dict):
            raise HandsGoalGroundingError("each Hands plan step must be an object")
        requested_operation = str(raw.get("operation", "")).strip().casefold()
        operation = _OPERATION_ALIASES.get(requested_operation, requested_operation)
        semantic = self._runtime.hands_registry.require(operation)
        # The active model establishes semantic action intent by choosing use_computer
        # for the latest accepted USER turn. Do not re-parse natural language here with
        # a keyword/verb allow-list. This boundary validates canonical operation identity,
        # target/material grounding and bounded conversational references; canonical
        # AuthorityService independently owns risk, approval, permits and audit.

        raw_parameters = raw.get("parameters", {})
        if not isinstance(raw_parameters, dict):
            raise HandsGoalGroundingError("Hands step parameters must be an object")
        parameters: dict[str, Any] = dict(raw_parameters)

        if operation == "set_master_volume":
            percent = float(parameters.get("percent"))
            requested_numbers = [
                float(value) for value in re.findall(r"\b\d+(?:\.\d+)?\b", user_text)
            ]
            if not any(abs(percent - value) < 0.001 for value in requested_numbers):
                raise HandsGoalGroundingError(
                    "volume percentage must come directly from the latest user request"
                )
            parameters = {"percent": percent}
        elif operation == "set_clipboard_text":
            text = str(parameters.get("text", ""))
            if not _material_in_text(text, user_text):
                raise HandsGoalGroundingError(
                    "clipboard text must be explicitly present in the latest user request"
                )
            parameters = {"text": text}
        elif operation in _APP_OPERATIONS:
            app = _bounded_app(parameters.get("app"))
            self._validate_app_target(
                app=app,
                user_text=user_text,
                apps_opened_in_plan=apps_opened_in_plan,
                allow_context=(
                    operation in _WINDOW_OPERATIONS or operation == "open_app"
                ),
            )
            if operation == "open_app":
                parameters = {"app": app}
                apps_opened_in_plan.add(_normalized(app))
            elif operation == "execute_windows_plan":
                plan = parameters.get("plan")
                if not isinstance(plan, list) or not plan:
                    raise HandsGoalGroundingError(
                        "structured app UI step requires a non-empty plan"
                    )
                if any(
                    isinstance(item, dict)
                    and str(item.get("action", "")).strip().casefold() == "launch"
                    for item in plan
                ):
                    raise HandsGoalGroundingError(
                        "goal plans must launch apps through app.lifecycle, not app UI"
                    )
                parameters = {
                    "app": app,
                    "task": user_text,
                    "plan": plan,
                    "allow_existing_app": True,
                }
            elif operation == "execute_visual_desktop_task":
                parameters = {"app": app, "task": user_text}
            else:
                parameters = {"app": app}
        elif operation in _FILE_WRITE_OPERATIONS:
            parameters = self._ground_file_parameters(operation, parameters, user_text)
        elif operation in _DOCUMENT_OPERATIONS:
            parameters = self._ground_document_parameters(
                operation, parameters, user_text
            )
        elif operation == "execute_browser_plan":
            parameters = self._ground_browser_parameters(parameters, user_text)
        elif operation in _DISPLAY_OPERATIONS or operation in _BLUETOOTH_OPERATIONS:
            parameters = self._ground_device_parameters(
                operation, parameters, user_text
            )
        elif operation in _POWER_OPERATIONS:
            parameters = {}
        elif operation in _SOFTWARE_OPERATIONS:
            parameters = self._ground_software_parameters(
                operation, parameters, user_text
            )
        elif operation in _DEVELOPMENT_OPERATIONS:
            parameters = self._ground_development_parameters(
                operation, parameters, user_text
            )
        else:
            parameters = {}

        if semantic.operation != operation:
            raise HandsGoalGroundingError(
                "Hands registry returned an inconsistent operation"
            )
        return HandsWorkflowStep(operation=operation, parameters=parameters)

    def _parse_plan(
        self, plan_json: str, user_text: str
    ) -> tuple[HandsWorkflowStep, ...]:
        if not isinstance(plan_json, str) or not plan_json.strip():
            raise HandsGoalGroundingError("Hands goal plan must be non-empty JSON")
        if len(plan_json) > _MAX_PLAN_JSON_CHARS:
            raise HandsGoalGroundingError(
                "Hands goal plan exceeds the bounded input limit"
            )
        try:
            decoded = json.loads(plan_json)
        except json.JSONDecodeError as exc:
            raise HandsGoalGroundingError("Hands goal plan is invalid JSON") from exc
        if not isinstance(decoded, list) or not decoded:
            raise HandsGoalGroundingError(
                "Hands goal plan must be a non-empty JSON array"
            )
        if len(decoded) > self._runner.MAX_STEPS:
            raise HandsGoalGroundingError(
                f"Hands goal plan exceeds {self._runner.MAX_STEPS} semantic steps"
            )
        opened: set[str] = set()
        return tuple(
            self._normalize_step(
                item,
                user_text=user_text,
                apps_opened_in_plan=opened,
            )
            for item in decoded
        )

    async def execute_goal(self, *, plan_json: str) -> dict[str, object]:
        turn = self._latest_user_turn()
        steps = self._parse_plan(plan_json, turn.text)
        workflow = await asyncio.to_thread(
            self._runner.execute,
            session_id=self._conversation.session_id,
            steps=steps,
        )
        results = [
            {
                "ok": result.ok,
                "status": result.status.value,
                "operation": result.operation,
                "capability": result.capability_key,
                "data": result.data,
                "reason": result.reason,
                "provenance": list(result.provenance),
            }
            for result in workflow.results
        ]
        return {
            "ok": workflow.ok,
            "status": "succeeded" if workflow.ok else "failed",
            "goal": turn.text,
            "completed_steps": workflow.completed_steps,
            "failed_operation": workflow.failed_operation,
            "reason": workflow.reason,
            "results": results,
            "canonical_user_turn_id": turn.turn_id,
        }

    @function_tool(raw_schema=_USE_COMPUTER_RAW_SCHEMA)
    async def use_computer(
        self,
        raw_arguments: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        """Execute a schema-constrained semantic Hands plan for the latest USER goal."""
        del context
        try:
            plan = raw_arguments.get("plan")
            if not isinstance(plan, list):
                raise HandsGoalGroundingError("Hands tool plan must be an array")
            return await self.execute_goal(plan_json=json.dumps(plan))
        except (HandsGoalGroundingError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
