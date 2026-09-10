from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one anchor in {path}, found {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"expected one regex anchor in {path}, found {count}")
    file.write_text(updated, encoding="utf-8")


# Generic installed-app lifecycle. The user/model supplies only a display-name query;
# Windows AppsFolder supplies the stable app identity and default launch verb.
replace_once(
    "src/jarvis/capabilities/windows_native.py",
    "from jarvis.computer.structured_windows import (\n    AllowlistedWindowsLauncher,\n    StructuredWindowsError,\n    WinAppCliBackend,\n)\n",
    "from jarvis.computer.structured_windows import StructuredWindowsError, WinAppCliBackend\n"
    "from jarvis.hands.app_catalog import (\n"
    "    AppCatalog,\n"
    "    AppCatalogError,\n"
    "    InstalledApp,\n"
    "    WindowsAppsFolderCatalog,\n"
    "    validate_app_name,\n"
    ")\n",
)
regex_once(
    "src/jarvis/capabilities/windows_native.py",
    r"class AppLifecycleBackend\(Protocol\):.*\Z",
    '''class AppLifecycleBackend(Protocol):
    def open(self, app: InstalledApp) -> dict[str, Any]: ...


class _InjectedBackendCatalog:
    """Identity shim used only when tests/custom code inject an executor backend."""

    def entries(self) -> tuple[InstalledApp, ...]:
        return ()

    def resolve(self, query: str) -> InstalledApp:
        name = validate_app_name(query)
        return InstalledApp(display_name=name, app_id=name, source="injected_backend")

    def launch(self, app: InstalledApp) -> None:
        raise AppCatalogError(f"injected backend catalogue cannot launch {app.display_name}")


class CatalogAppLifecycleBackend:
    """Launch one resolved Windows AppsFolder identity and verify it with winapp."""

    def __init__(
        self,
        catalog: AppCatalog,
        *,
        ui_factory=WinAppCliBackend,
    ) -> None:
        self._catalog = catalog
        self._ui_factory = ui_factory

    def open(self, app: InstalledApp) -> dict[str, Any]:
        ui = self._ui_factory()
        status = ui.status(app.ui_target, check=False)
        launched = False
        if int(status.payload.get("exit_code", 1)) != 0:
            self._catalog.launch(app)
            launched = True
        ready = ui.wait_until_running(app.ui_target, timeout_seconds=10.0)
        return {
            "app": app.payload(),
            "launched": launched,
            "running": int(ready.payload.get("exit_code", 1)) == 0,
        }


class AppLifecycleExecutor:
    capability_key = "app:lifecycle"
    operations = ("open_app",)

    def __init__(
        self,
        backend: AppLifecycleBackend | None = None,
        *,
        catalog: AppCatalog | None = None,
    ) -> None:
        self._backend = backend
        self._catalog = catalog or (
            _InjectedBackendCatalog() if backend is not None else WindowsAppsFolderCatalog()
        )
        self.descriptor = CapabilityDescriptor.create(
            capability_id="lifecycle",
            source_id="app",
            kind=CapabilityKind.NATIVE_API,
            name="Windows installed application lifecycle",
            description=(
                "Resolve Start-menu applications dynamically through Windows AppsFolder, "
                "launch the resolved Shell item, and verify the application is running."
            ),
            operations=list(self.operations),
            metadata={
                "catalog": "Windows Shell AppsFolder",
                "dynamic_installed_apps": True,
                "model_supplied_executable": False,
                "raw_shell": False,
            },
            execution_enabled=_execution_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation != "open_app":
            raise ValueError("unsupported application lifecycle operation")
        query = validate_app_name(request.parameters.get("app", ""))
        try:
            app = self._catalog.resolve(query)
        except AppCatalogError as exc:
            raise ValueError(str(exc)) from exc
        return PreparedCapability(
            request=request,
            target={
                "app_id": app.app_id,
                "display_name": app.display_name,
                "domain": "app.lifecycle",
            },
            parameters={"app": app.payload()},
            material_summary=f"Open Windows application: {app.display_name}",
            attributes=ActionAttributes(reversible_local_change=True),
            execution_payload={"app": app.payload()},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        payload = dict(prepared.execution_payload["app"])
        app = InstalledApp(
            display_name=str(payload["display_name"]),
            app_id=str(payload["app_id"]),
            source=str(payload.get("source", "windows_apps_folder")),
        )
        try:
            backend = self._backend or CatalogAppLifecycleBackend(self._catalog)
            data = backend.open(app)
            verified = bool(data.get("running"))
            data["verification_passed"] = verified
        except (
            AppCatalogError,
            NativeWindowsError,
            StructuredWindowsError,
            OSError,
            RuntimeError,
        ) as exc:
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("Windows Shell AppsFolder", "Microsoft winapp"),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            started,
            data=data,
            reason=None if verified else "application launch verification failed",
            provenance=("Windows Shell AppsFolder", "Microsoft winapp"),
        )
''',
)

# Structured UI works with any safe already-running app identity. Generic launch is
# owned by app.lifecycle; nested launch is retained only for the legacy smoke path.
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    "from jarvis.computer.structured_windows import (\n",
    "from jarvis.hands.app_catalog import validate_app_name\n"
    "from jarvis.computer.structured_windows import (\n",
)
regex_once(
    "src/jarvis/capabilities/windows_control.py",
    r"def _normalize_app\(value: object\) -> str:\n.*?\n\ndef _normalize_task",
    '''def _normalize_app(value: object) -> str:
    return validate_app_name(value)


def _normalize_task''',
)
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    "_READ_STRUCTURED_ACTIONS = {\n    \"inspect\",\n    \"search\",\n    \"get_value\",\n    \"verify_value\",\n}\n",
    '''_READ_STRUCTURED_ACTIONS = {
    "inspect",
    "search",
    "get_value",
    "verify_value",
}
_STRUCTURED_BLOCKED_UI_TERMS = (
    "save",
    "save as",
    "print",
    "share",
    "send",
    "delete",
    "remove",
    "open file",
    "open dialog",
    "install",
    "uninstall",
    "download",
    "upload",
    "security",
    "permission",
    "settings",
    "password",
    "credential",
    "api key",
    "token",
)
_STRUCTURED_BROWSER_APP_NAMES = {
    "chrome",
    "google chrome",
    "edge",
    "microsoft edge",
    "firefox",
    "mozilla firefox",
}
''',
)
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    "def _extract_value(payload: dict[str, Any]) -> str:\n",
    '''def _normalized_grounding(value: object) -> str:
    return " ".join(re.sub(r"[^\\w]+", " ", str(value).casefold()).split())


def _validate_plan_against_task(
    plan: tuple[dict[str, Any], ...],
    task: str,
) -> None:
    normalized_task = _normalized_grounding(task)
    grounded_values: set[str] = set()
    for step in plan:
        action = str(step["action"])
        for field in ("selector", "query"):
            value = step.get(field)
            normalized = _normalized_grounding(value) if value is not None else ""
            if normalized and any(
                _normalized_grounding(term) in normalized
                for term in _STRUCTURED_BLOCKED_UI_TERMS
            ):
                raise ValueError(
                    "structured app UI plan crosses a blocked persistent/high-risk intent"
                )
        if action == "search":
            query = _normalized_grounding(step.get("query", ""))
            if not query or query not in normalized_task:
                raise ValueError(
                    "structured app UI search content is not grounded in the user goal"
                )
        if action in {"send_text", "set_value"}:
            material = _normalized_grounding(step.get("text", ""))
            if not material or material not in normalized_task:
                raise ValueError(
                    "structured app UI material text is not grounded in the user goal"
                )
            grounded_values.add(material)
        if action == "verify_value":
            expected = _normalized_grounding(step.get("expected", ""))
            if not expected or (
                expected not in normalized_task and expected not in grounded_values
            ):
                raise ValueError(
                    "structured app UI verification value is not grounded in the user goal"
                )


def _extract_value(payload: dict[str, Any]) -> str:
''',
)
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    "        plan = _normalize_plan(request.parameters.get(\"plan\"))\n        allow_existing_app = _bool(request.parameters.get(\"allow_existing_app\"))\n        mutating = any(step[\"action\"] in _MUTATING_STRUCTURED_ACTIONS for step in plan)\n        if not mutating:\n            raise ValueError(\n                \"desktop control plan must contain at least one control action\"\n            )\n        reads_private_state = any(\n            step[\"action\"] in _READ_STRUCTURED_ACTIONS for step in plan\n        )\n",
    '''        plan = _normalize_plan(request.parameters.get("plan"))
        if _normalized_grounding(app) in _STRUCTURED_BROWSER_APP_NAMES:
            raise ValueError(
                "browser UI interaction belongs to the dedicated browser capability"
            )
        _validate_plan_against_task(plan, task)
        allow_existing_app = _bool(request.parameters.get("allow_existing_app"))
        mutating = any(step["action"] in _MUTATING_STRUCTURED_ACTIONS for step in plan)
        reads_private_state = any(
            step["action"] in _READ_STRUCTURED_ACTIONS for step in plan
        )
        if not mutating and not reads_private_state:
            raise ValueError("structured app UI plan has no executable action")
        if any(step["action"] == "launch" for step in plan) and app not in _safe_apps():
            raise ValueError(
                "generic application launch belongs to app.lifecycle; nested UI launch "
                "is retained only for legacy bounded smoke targets"
            )
''',
)
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    '''            attributes=ActionAttributes(
                private_read=reads_private_state,
                reversible_local_change=True,
                scope=ActionScope.LIMITED,
            ),''',
    '''            attributes=ActionAttributes(
                private_read=reads_private_state,
                reversible_local_change=mutating,
                scope=ActionScope.LIMITED,
            ),''',
)
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    '''            metadata={
                "backend": "Microsoft winapp UI Automation",
                "approved_apps": list(_safe_apps()),
                "raw_shell": False,
                "browser_control": False,
            },''',
    '''            metadata={
                "backend": "Microsoft winapp UI Automation",
                "generic_running_apps": True,
                "legacy_nested_launch_apps": list(_safe_apps()),
                "raw_shell": False,
                "browser_control": False,
            },''',
)
replace_once(
    "src/jarvis/capabilities/windows_control.py",
    '''            existing = ui.status(app, check=False)
            if int(existing.payload.get("exit_code", 1)) != 0:
                launcher.launch(app)
                ui.wait_until_running(app, timeout_seconds=6.0)
            provider = self._provider_factory(self._provider_name)''',
    '''            existing = ui.status(app, check=False)
            if int(existing.payload.get("exit_code", 1)) != 0:
                raise CapabilityExecutionError(
                    "visual app UI target is not running; launch through app.lifecycle first"
                )
            provider = self._provider_factory(self._provider_name)''',
)

# If multiple executors later satisfy one semantic operation, resolve by the product
# registry's substrate preference rather than by model/tool naming.
replace_once(
    "src/jarvis/capabilities/runtime.py",
    "from jarvis.hands.registry import HandsCapabilityRegistry\n",
    "from jarvis.hands.models import ExecutionSubstrate\n"
    "from jarvis.hands.registry import HandsCapabilityRegistry\n",
)
regex_once(
    "src/jarvis/capabilities/runtime.py",
    r"    def capability_for_operation\(self, operation: str\) -> str \| None:\n.*?\n\n    def execute_operation",
    '''    def capability_for_operation(self, operation: str) -> str | None:
        normalized = str(operation).strip()
        candidates = tuple(
            key
            for key, executor in self._executors.items()
            if normalized in executor.operations
        )
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

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

    def execute_operation''',
)

# Live voice exposes one goal-oriented Hands action boundary.
replace_once(
    "src/jarvis/voice/capability_tools.py",
    "from jarvis.voice.hands_tools import HandsAgentTools\n",
    "from jarvis.voice.hands_goal_tools import HandsGoalAgentTools\n",
)
replace_once(
    "src/jarvis/voice/capability_tools.py",
    "        self._hands = HandsAgentTools(runtime, conversation)\n",
    "        self._hands = HandsGoalAgentTools(runtime, conversation)\n",
)

regex_once(
    "src/jarvis/voice/agent.py",
    r"When `computer_action` is available,.*?If a tool result\n"
    r"is denied, unavailable, failed, or unverified, say so briefly and do not pretend the\n"
    r"action happened\.\n",
    '''When `use_computer` is available, treat it as the single JARVIS Hands boundary for
computer outcomes. The USER states the desired result; never ask them to choose a
capability, executor, application adapter, or sequence of clicks. Build a short semantic
plan and let the governed Hands runtime choose the best available execution substrate.
Prefer native/semantic operations, then dedicated integrations, then structured app UI,
then owner-enabled visual Computer Use. Do not expose that routing ceremony in ordinary
speech.

Application names are dynamic installed-app data, not a hard-coded skill list. For
"open Apple Music", plan an `open_app` step with app="Apple Music"; app.lifecycle resolves
that user-named target against the Windows installed-app catalogue. Do not claim only a
small fixed set of applications is supported. For a goal such as "play Kesariya on Apple
Music", launch through app.lifecycle, use bounded app UI only for navigation/search/play
steps that lack a better semantic integration, and use native media/audio capabilities for
playback state or volume where appropriate.

The `plan_json` argument contains implementation details only; the canonical goal always
comes from the latest accepted USER utterance. Material values such as typed text, search
content, clipboard text, percentages, and application targets must stay grounded in that
goal. Harmless intermediate UI navigation such as finding a Search control may be inferred
by JARVIS; this does not authorize blocked persistent/high-consequence actions such as
save, send, delete, install, credential entry, shell/terminal commands, security changes,
or other capability families that are not yet exposed.

Every semantic step still passes independently through CapabilityRuntime and canonical
AuthorityService. Treat tool results as authoritative: if execution is denied, unavailable,
failed, or unverified, say so briefly and never pretend the goal completed. If an app UI
layout is unknown, use the same `use_computer` tool to inspect/search bounded UI state and
continue the goal; do not make the USER provide manual click-by-click instructions.
''',
)

# PyWinRT namespaces are modular. Media.Control's async surface needs Foundation.
replace_once(
    "pyproject.toml",
    '    "winrt-runtime==3.2.1; platform_system == \'Windows\'",\n    "winrt-Windows.Media.Control==3.2.1; platform_system == \'Windows\'",\n',
    '    "winrt-runtime==3.2.1; platform_system == \'Windows\'",\n'
    '    "winrt-Windows.Foundation==3.2.1; platform_system == \'Windows\'",\n'
    '    "winrt-Windows.Media.Control==3.2.1; platform_system == \'Windows\'",\n',
)
replace_once(
    ".github/workflows/code-quality.yml",
    "          import winrt.windows.media.control;\n",
    "          import winrt.windows.foundation; import winrt.windows.media.control;\n",
)
replace_once(
    "src/jarvis/computer/hands_smoke.py",
    '    "winrt.windows.media.control": "Windows media sessions",\n',
    '    "winrt.windows.foundation": "Windows Runtime Foundation",\n'
    '    "winrt.windows.media.control": "Windows media sessions",\n',
)

print("goal-oriented Hands architecture v2 refactor applied")
