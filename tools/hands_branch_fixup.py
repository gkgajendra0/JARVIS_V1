from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one anchor in {path}, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"expected exactly one regex anchor in {path}, found {count}")
    file.write_text(updated, encoding="utf-8")


replace_once(
    "src/jarvis/capabilities/windows_native.py",
    '            operation = prepared.request.operation\n            if operation == "list_windows":',
    '            operation = prepared.request.operation\n            verified = True\n            if operation == "list_windows":',
)

regex_once(
    "src/jarvis/capabilities/windows_control.py",
    r"def _safe_apps\(\) -> tuple\[str, \.\.\.\]:\n.*?\n\ndef _normalize_app",
    '''def _safe_apps() -> tuple[str, ...]:
    defaults = set(AllowlistedWindowsLauncher.supported_apps())
    configured = os.getenv("JARVIS_DESKTOP_CONTROL_APPS", "")
    if not configured.strip():
        return tuple(sorted(defaults))
    requested = {
        item.strip().casefold()
        for item in configured.split(",")
        if item.strip()
    }
    return tuple(sorted(defaults & requested))


def _normalize_app''',
)

replace_once(
    "src/jarvis/voice/computer_tools.py",
    '    "already khula",\n)\n\n\nclass ComputerControlGroundingError',
    '''    "already khula",
)
_BLOCKED_UI_INTENT_TERMS = (
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


class ComputerControlGroundingError''',
)

replace_once(
    "src/jarvis/voice/computer_tools.py",
    'def _existing_app_authorized(text: str) -> bool:\n    normalized = _normalized(text)\n    return any(_normalized(marker) in normalized for marker in _EXISTING_APP_MARKERS)\n\n\nclass ComputerControlAgentTools',
    '''def _existing_app_authorized(text: str) -> bool:
    normalized = _normalized(text)
    return any(_normalized(marker) in normalized for marker in _EXISTING_APP_MARKERS)


def _material_is_grounded(material: object, user_text: str) -> bool:
    normalized_material = _normalized(str(material))
    return bool(normalized_material) and normalized_material in _normalized(user_text)


def _validate_structured_plan(plan: object, user_text: str) -> list[dict[str, object]]:
    if not isinstance(plan, list) or not plan:
        raise ComputerControlGroundingError(
            "structured computer-control plan must be a non-empty JSON array"
        )
    normalized_user = _normalized(user_text)
    validated: list[dict[str, object]] = []
    for index, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            raise ComputerControlGroundingError(
                f"structured plan step {index} must be an object"
            )
        action = str(item.get("action", "")).strip().casefold()
        for field in ("selector", "query"):
            value = str(item.get(field, "")).strip()
            normalized_value = _normalized(value)
            if normalized_value and any(
                _normalized(term) in normalized_value
                for term in _BLOCKED_UI_INTENT_TERMS
            ):
                raise ComputerControlGroundingError(
                    "structured plan contains an action outside the bounded app UI scope"
                )
        if action in {"send_text", "set_value"} and not _material_is_grounded(
            item.get("text", ""), user_text
        ):
            raise ComputerControlGroundingError(
                "structured plan typed text is not grounded in the latest user request"
            )
        if action == "verify_value" and not _material_is_grounded(
            item.get("expected", ""), user_text
        ):
            raise ComputerControlGroundingError(
                "structured plan verification value is not grounded in the latest user request"
            )
        if action in {"click", "invoke"}:
            selector = _normalized(str(item.get("selector", "")))
            if not selector or selector not in normalized_user:
                raise ComputerControlGroundingError(
                    "structured plan UI mutation selector is not grounded in the latest user request"
                )
        validated.append(dict(item))
    return validated


class ComputerControlAgentTools''',
)

replace_once(
    "src/jarvis/voice/computer_tools.py",
    '            operation = "execute_windows_plan"\n            parameters = {',
    '            plan = _validate_structured_plan(plan, turn.text)\n            operation = "execute_windows_plan"\n            parameters = {',
)

replace_once(
    "src/jarvis/voice/hands_tools.py",
    '\n        parameters: dict[str, object] = {}\n        if operation == "set_master_volume":',
    '''
        if operation == "play_media":
            normalized_request = _normalized(turn.text)
            simple_play = normalized_request in {"play", "jarvis play"}
            resume_markers = (
                "resume",
                "resume it",
                "continue",
                "continue it",
                "play it",
                "play again",
            )
            if not simple_play and not _contains_marker(turn.text, resume_markers):
                raise HandsToolGroundingError(
                    "play_media only resumes the current media session; selecting a named song "
                    "or source requires a dedicated integration or app UI capability"
                )

        parameters: dict[str, object] = {}
        if operation == "set_master_volume":''',
)

replace_once(
    "src/jarvis/voice/agent.py",
    "When `control_computer` is available, treat it as bounded JARVIS hands, NOT general\n",
    '''When `computer_action` is available, prefer it for semantic computer operations that
have a native executor: system audio, current-media playback controls, clipboard text,
top-level window management, and approved application launch. Material values and targets
must come from the latest canonical USER request; never substitute a different percentage,
clipboard payload, application, or window target. `play_media` means resume the current
media session only. It must never be used to interpret "play <named song/artist/playlist>";
named-media selection needs a dedicated media integration or the bounded app-UI path.
A successful `computer_action` result is the only basis for claiming that the native
computer action completed.

When `control_computer` is available, treat it as the bounded application-UI fallback, NOT general
''',
)

print("Hands hardening patch applied")
