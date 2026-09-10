from __future__ import annotations

from pathlib import Path


PATH = Path("src/jarvis/capabilities/windows_native.py")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one anchor, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)


replace_once(
    '''def _execution_enabled() -> bool:
    return platform.system() == "Windows"


def _result(''',
    '''def _execution_enabled() -> bool:
    return platform.system() == "Windows"


def _approval_preview(text: str, *, limit: int = 120) -> str:
    compact = " ".join(str(text).split())
    preview = compact if len(compact) <= limit else compact[: limit - 3] + "..."
    return f"{preview!r} ({len(str(text))} chars)"


def _audio_summary(operation: str, params: dict[str, Any]) -> str:
    if operation == "set_master_volume":
        return f"Set Windows master volume to {float(params['percent']):g}%"
    if operation == "mute_master_volume":
        return "Mute Windows master output"
    if operation == "unmute_master_volume":
        return "Unmute Windows master output"
    return "Read Windows master volume and mute state"


def _media_summary(operation: str) -> str:
    labels = {
        "get_current_media": "Read current Windows media session and metadata",
        "play_media": "Resume the current Windows media session",
        "pause_media": "Pause the current Windows media session",
        "toggle_media_playback": "Toggle play/pause for the current Windows media session",
        "next_media": "Skip to next item in the current Windows media session",
        "previous_media": "Return to previous item in the current Windows media session",
        "stop_media": "Stop the current Windows media session",
    }
    return labels[operation]


def _clipboard_summary(operation: str, params: dict[str, Any]) -> str:
    if operation == "set_clipboard_text":
        return f"Set Windows clipboard text to {_approval_preview(str(params['text']))}"
    if operation == "clear_clipboard":
        return "Clear Windows clipboard contents"
    return "Read bounded Unicode text from the Windows clipboard"


def _window_summary(operation: str, params: dict[str, Any]) -> str:
    if operation == "list_windows":
        return "List visible top-level Windows application windows"
    app = str(params["app"])
    labels = {
        "focus_window": "Focus",
        "maximize_window": "Maximize",
        "minimize_window": "Minimize",
        "restore_window": "Restore",
        "move_window_to_next_monitor": "Move to next monitor",
    }
    return f"{labels[operation]} Windows app window: {app}"


def _result(''',
)
replace_once(
    'material_summary=f"Windows audio action: {request.operation}",',
    'material_summary=_audio_summary(request.operation, params),',
)
replace_once(
    'material_summary=f"Windows media action: {request.operation}",',
    'material_summary=_media_summary(request.operation),',
)
replace_once(
    'material_summary=f"Windows clipboard action: {request.operation}",',
    'material_summary=_clipboard_summary(request.operation, params),',
)
replace_once(
    'material_summary=f"Windows window action: {request.operation}",',
    'material_summary=_window_summary(request.operation, params),',
)

PATH.write_text(text, encoding="utf-8")
print("native H1 approval summaries hardened")
