"""Strongly typed provider-facing contracts for JARVIS Hands planning.

The conversational model never gets arbitrary shell authority.  A dedicated Hands
planner is constrained to the semantic operations already registered by JARVIS, and
each operation has an explicit parameter model.  Dynamic planner response models are
built only from the small operation shortlist selected for the current user goal.
"""

from __future__ import annotations

import hashlib
import operator
from dataclasses import dataclass
from functools import reduce
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmptyParams(StrictContract):
    pass


class AppParams(StrictContract):
    app: str = Field(min_length=1, max_length=160)


class VolumeParams(StrictContract):
    percent: float = Field(ge=0.0, le=100.0)


class ClipboardTextParams(StrictContract):
    text: str = Field(min_length=1, max_length=10_000)


class ReadPathParams(StrictContract):
    root: str = Field(default="project", min_length=1, max_length=32)
    path: str = Field(min_length=1, max_length=1_000)


class ReadListParams(StrictContract):
    root: str = Field(default="project", min_length=1, max_length=32)
    path: str = Field(default="", max_length=1_000)
    max_results: int = Field(default=20, ge=1, le=50)


class SearchProjectParams(ReadListParams):
    query: str = Field(min_length=1, max_length=300)


class WritePathParams(StrictContract):
    root: str = Field(min_length=1, max_length=32)
    path: str = Field(min_length=1, max_length=1_000)


class WriteTextParams(WritePathParams):
    text: str = Field(min_length=1, max_length=100_000)


class CopyMoveParams(StrictContract):
    source_root: str = Field(min_length=1, max_length=32)
    source_path: str = Field(min_length=1, max_length=1_000)
    dest_root: str = Field(min_length=1, max_length=32)
    dest_path: str = Field(min_length=1, max_length=1_000)
    overwrite: bool = False


class RenameParams(WritePathParams):
    new_path: str = Field(min_length=1, max_length=1_000)
    overwrite: bool = False


class DocTextParams(WritePathParams):
    text: str = Field(min_length=1, max_length=100_000)


class XlsxCreateParams(WritePathParams):
    sheet: str = Field(default="Sheet1", min_length=1, max_length=120)


class XlsxCellParams(WritePathParams):
    sheet: str = Field(default="Sheet1", min_length=1, max_length=120)
    cell: str = Field(min_length=1, max_length=32)
    value: str | int | float | bool | None


class PptxParams(WritePathParams):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=20_000)


class DisplayReadParams(StrictContract):
    display: str | None = Field(default=None, max_length=160)


class DisplaySetParams(DisplayReadParams):
    percent: int = Field(ge=0, le=100)


class BluetoothParams(StrictContract):
    name: str = Field(min_length=1, max_length=300)


class SoftwareQueryParams(StrictContract):
    query: str = Field(min_length=1, max_length=300)


class PackageParams(StrictContract):
    package_id: str = Field(min_length=1, max_length=300)


class RepoParams(StrictContract):
    repo: str = Field(min_length=1, max_length=120)


class RepoBranchParams(RepoParams):
    branch: str = Field(min_length=1, max_length=240)


class RepoPathsParams(RepoParams):
    paths: list[str] = Field(min_length=1, max_length=50)


class RepoCommitParams(RepoParams):
    message: str = Field(min_length=1, max_length=500)


BrowserSelectorKind = Literal["role", "text", "label", "placeholder", "testid"]


class BrowserNavigate(StrictContract):
    action: Literal["navigate"]
    url: str = Field(min_length=1, max_length=2_048)


class BrowserClick(StrictContract):
    action: Literal["click"]
    selector_kind: BrowserSelectorKind
    selector: str = Field(min_length=1, max_length=300)


class BrowserFill(BrowserClick):
    action: Literal["fill"]
    text: str = Field(min_length=1, max_length=10_000)


class BrowserReadText(BrowserClick):
    action: Literal["read_text"]


class BrowserWaitFor(BrowserClick):
    action: Literal["wait_for"]


class BrowserDownload(BrowserClick):
    action: Literal["download"]
    root: str = Field(min_length=1, max_length=32)
    path: str = Field(min_length=1, max_length=1_000)


class BrowserUpload(BrowserClick):
    action: Literal["upload"]
    root: str = Field(min_length=1, max_length=32)
    path: str = Field(min_length=1, max_length=1_000)


class BrowserReadPage(StrictContract):
    action: Literal["read_page"]


BrowserAction = Annotated[
    BrowserNavigate
    | BrowserClick
    | BrowserFill
    | BrowserReadText
    | BrowserWaitFor
    | BrowserDownload
    | BrowserUpload
    | BrowserReadPage,
    Field(discriminator="action"),
]


class BrowserPlanParams(StrictContract):
    plan: list[BrowserAction] = Field(min_length=1, max_length=12)


class WindowsInspect(StrictContract):
    action: Literal["inspect"]
    selector: str | None = Field(default=None, max_length=300)
    depth: int = Field(default=6, ge=1, le=8)
    interactive: bool = True


class WindowsSearch(StrictContract):
    action: Literal["search"]
    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=10, ge=1, le=25)


class WindowsSelectorAction(StrictContract):
    selector: str = Field(min_length=1, max_length=300)


class WindowsGetValue(WindowsSelectorAction):
    action: Literal["get_value"]


class WindowsVerifyValue(WindowsSelectorAction):
    action: Literal["verify_value"]
    expected: str = Field(min_length=1, max_length=500)
    comparison: Literal["equals", "contains"] = "equals"


class WindowsFocus(WindowsSelectorAction):
    action: Literal["focus"]


class WindowsClick(WindowsSelectorAction):
    action: Literal["click"]
    double: bool = False
    right: bool = False


class WindowsInvoke(WindowsSelectorAction):
    action: Literal["invoke"]


class WindowsSendText(StrictContract):
    action: Literal["send_text"]
    selector: str | None = Field(default=None, max_length=300)
    text: str = Field(min_length=1, max_length=500)


class WindowsSetValue(WindowsSelectorAction):
    action: Literal["set_value"]
    text: str = Field(min_length=1, max_length=500)


class WindowsWaitFor(WindowsSelectorAction):
    action: Literal["wait_for"]
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=15.0)
    gone: bool = False


class WindowsWaitUntilRunning(StrictContract):
    action: Literal["wait_until_running"]
    timeout_seconds: float = Field(default=6.0, ge=0.5, le=15.0)


WindowsAction = Annotated[
    WindowsInspect
    | WindowsSearch
    | WindowsGetValue
    | WindowsVerifyValue
    | WindowsFocus
    | WindowsClick
    | WindowsInvoke
    | WindowsSendText
    | WindowsSetValue
    | WindowsWaitFor
    | WindowsWaitUntilRunning,
    Field(discriminator="action"),
]


class WindowsPlanParams(AppParams):
    plan: list[WindowsAction] = Field(min_length=1, max_length=12)


_OPERATION_PARAMETER_MODELS: dict[str, type[BaseModel]] = {
    "system_status": EmptyParams,
    "list_processes": EmptyParams,
    "get_master_volume": EmptyParams,
    "set_master_volume": VolumeParams,
    "mute_master_volume": EmptyParams,
    "unmute_master_volume": EmptyParams,
    "get_current_media": EmptyParams,
    "play_media": EmptyParams,
    "pause_media": EmptyParams,
    "toggle_media_playback": EmptyParams,
    "next_media": EmptyParams,
    "previous_media": EmptyParams,
    "stop_media": EmptyParams,
    "get_clipboard_text": EmptyParams,
    "set_clipboard_text": ClipboardTextParams,
    "clear_clipboard": EmptyParams,
    "list_windows": EmptyParams,
    "focus_window": AppParams,
    "maximize_window": AppParams,
    "minimize_window": AppParams,
    "restore_window": AppParams,
    "move_window_to_next_monitor": AppParams,
    "open_app": AppParams,
    "close_app": AppParams,
    "execute_windows_plan": WindowsPlanParams,
    "execute_visual_desktop_task": AppParams,
    "file_info": ReadPathParams,
    "list_directory": ReadListParams,
    "list_project_files": ReadListParams,
    "read_file": ReadPathParams,
    "read_document": ReadPathParams,
    "search_project": SearchProjectParams,
    "create_text_file": WriteTextParams,
    "replace_text_file": WriteTextParams,
    "append_text_file": WriteTextParams,
    "make_directory": WritePathParams,
    "copy_path": CopyMoveParams,
    "move_path": CopyMoveParams,
    "rename_path": RenameParams,
    "trash_path": WritePathParams,
    "create_docx": DocTextParams,
    "append_docx_paragraph": DocTextParams,
    "create_xlsx": XlsxCreateParams,
    "set_xlsx_cell": XlsxCellParams,
    "create_pptx": PptxParams,
    "add_pptx_text_slide": PptxParams,
    "execute_browser_plan": BrowserPlanParams,
    "list_displays": EmptyParams,
    "get_display_brightness": DisplayReadParams,
    "set_display_brightness": DisplaySetParams,
    "list_bluetooth_devices": EmptyParams,
    "pair_bluetooth_device": BluetoothParams,
    "unpair_bluetooth_device": BluetoothParams,
    "lock_workstation": EmptyParams,
    "sleep_workstation": EmptyParams,
    "sign_out": EmptyParams,
    "restart_workstation": EmptyParams,
    "shutdown_workstation": EmptyParams,
    "search_software": SoftwareQueryParams,
    "list_installed_software": SoftwareQueryParams,
    "install_package": PackageParams,
    "uninstall_package": PackageParams,
    "git_status": RepoParams,
    "git_active_branch": RepoParams,
    "git_create_branch": RepoBranchParams,
    "git_stage_paths": RepoPathsParams,
    "git_commit": RepoCommitParams,
    "git_push_current": RepoParams,
}


def parameter_model_for(operation: str) -> type[BaseModel]:
    try:
        return _OPERATION_PARAMETER_MODELS[str(operation).strip()]
    except KeyError as exc:
        raise ValueError(f"no typed Hands contract for operation: {operation}") from exc


def validate_contract_coverage(operation_names: set[str]) -> None:
    missing = sorted(operation_names - set(_OPERATION_PARAMETER_MODELS))
    extra = sorted(set(_OPERATION_PARAMETER_MODELS) - operation_names)
    if missing or extra:
        raise ValueError(f"Hands contract mismatch: missing={missing}; extra={extra}")


@dataclass(frozen=True, slots=True)
class PlannedAction:
    operation: str
    parameters: dict[str, Any]
    evidence: str


@dataclass(frozen=True, slots=True)
class PlannerTurn:
    action: PlannedAction | None = None
    goal_complete: bool = False
    clarification_question: str | None = None


class PlannerResponseError(ValueError):
    pass


def build_action_response_model(
    operation_names: tuple[str, ...],
) -> type[BaseModel]:
    """Create a strict one-action planner schema from the current shortlist."""

    names = tuple(dict.fromkeys(str(item).strip() for item in operation_names if item))
    if not names:
        raise ValueError("Hands planner requires at least one candidate operation")

    call_models: list[type[BaseModel]] = []
    for operation in names:
        params_model = parameter_model_for(operation)
        literal_operation = Literal[operation]
        model_name = "HandsCall_" + "".join(
            part.capitalize() for part in operation.split("_")
        )
        call_models.append(
            create_model(
                model_name,
                __base__=StrictContract,
                operation=(literal_operation, ...),
                parameters=(params_model, ...),
                evidence=(
                    str,
                    Field(
                        min_length=1,
                        max_length=600,
                        description=(
                            "Short verbatim phrase copied from the accepted USER "
                            "conversation that supports this exact action."
                        ),
                    ),
                ),
            )
        )

    if len(call_models) == 1:
        action_type: Any = call_models[0]
    else:
        union_type = reduce(operator.or_, call_models)
        action_type = Annotated[union_type, Field(discriminator="operation")]

    digest = hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:10]
    return create_model(
        f"HandsPlannerTurn_{digest}",
        __base__=StrictContract,
        actions=(list[action_type], Field(default_factory=list, max_length=1)),
        goal_complete=(bool, False),
        clarification_question=(
            str | None,
            Field(default=None, min_length=1, max_length=400),
        ),
    )


def materialize_planner_response(response: BaseModel) -> PlannerTurn:
    actions = getattr(response, "actions", None)
    clarification = getattr(response, "clarification_question", None)
    goal_complete = bool(getattr(response, "goal_complete", False))
    if not isinstance(actions, list):
        raise PlannerResponseError("planner actions must be a list")
    if clarification:
        if actions or goal_complete:
            raise PlannerResponseError(
                "planner clarification cannot be combined with action/completion"
            )
        return PlannerTurn(clarification_question=str(clarification))
    if goal_complete:
        if actions:
            raise PlannerResponseError(
                "planner completion cannot be combined with another action"
            )
        return PlannerTurn(goal_complete=True)
    if len(actions) != 1:
        raise PlannerResponseError(
            "planner must return exactly one action, completion, or clarification"
        )
    action = actions[0]
    parameters_model = getattr(action, "parameters", None)
    if not isinstance(parameters_model, BaseModel):
        raise PlannerResponseError("planner action parameters were not typed")
    return PlannerTurn(
        action=PlannedAction(
            operation=str(action.operation),
            parameters=parameters_model.model_dump(exclude_none=True),
            evidence=str(action.evidence),
        )
    )
