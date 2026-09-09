"""Semantic capability catalogue for JARVIS Hands."""

from __future__ import annotations

from .models import ExecutionSubstrate, HandsDomain, HandsOperation


class HandsCapabilityRegistry:
    """Own semantic operation definitions independently of concrete executors."""

    def __init__(self, operations: tuple[HandsOperation, ...]) -> None:
        self._operations = {item.operation: item for item in operations}
        if len(self._operations) != len(operations):
            raise ValueError("hands operation names must be unique")

    @classmethod
    def default(cls) -> HandsCapabilityRegistry:
        native = (ExecutionSubstrate.NATIVE_API,)
        native_then_human = (ExecutionSubstrate.NATIVE_API, ExecutionSubstrate.HUMAN)
        ui_fallback = (
            ExecutionSubstrate.STRUCTURED_AUTOMATION,
            ExecutionSubstrate.VISUAL_FALLBACK,
            ExecutionSubstrate.HUMAN,
        )
        return cls(
            (
                HandsOperation(
                    "system_status",
                    HandsDomain.SYSTEM_STATUS,
                    "Read bounded machine health and utilization metadata.",
                    native,
                ),
                HandsOperation(
                    "get_master_volume",
                    HandsDomain.SYSTEM_AUDIO,
                    "Read the current Windows master output volume and mute state.",
                    native_then_human,
                ),
                HandsOperation(
                    "set_master_volume",
                    HandsDomain.SYSTEM_AUDIO,
                    "Set the Windows master output volume to an explicit percentage.",
                    native_then_human,
                ),
                HandsOperation(
                    "mute_master_volume",
                    HandsDomain.SYSTEM_AUDIO,
                    "Mute the Windows master output endpoint.",
                    native_then_human,
                ),
                HandsOperation(
                    "unmute_master_volume",
                    HandsDomain.SYSTEM_AUDIO,
                    "Unmute the Windows master output endpoint.",
                    native_then_human,
                ),
                HandsOperation(
                    "get_current_media",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Read the active Windows media session and current media metadata.",
                    native_then_human,
                ),
                HandsOperation(
                    "play_media",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Play the active Windows media session.",
                    native_then_human,
                ),
                HandsOperation(
                    "pause_media",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Pause the active Windows media session.",
                    native_then_human,
                ),
                HandsOperation(
                    "toggle_media_playback",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Toggle play or pause for the active Windows media session.",
                    native_then_human,
                ),
                HandsOperation(
                    "next_media",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Skip to the next item in the active Windows media session.",
                    native_then_human,
                ),
                HandsOperation(
                    "previous_media",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Return to the previous item in the active Windows media session.",
                    native_then_human,
                ),
                HandsOperation(
                    "stop_media",
                    HandsDomain.MEDIA_PLAYBACK,
                    "Stop the active Windows media session.",
                    native_then_human,
                ),
                HandsOperation(
                    "get_clipboard_text",
                    HandsDomain.CLIPBOARD,
                    "Read bounded Unicode text from the Windows clipboard.",
                    native_then_human,
                ),
                HandsOperation(
                    "set_clipboard_text",
                    HandsDomain.CLIPBOARD,
                    "Replace the Windows clipboard with explicit bounded text.",
                    native_then_human,
                ),
                HandsOperation(
                    "clear_clipboard",
                    HandsDomain.CLIPBOARD,
                    "Clear the current Windows clipboard contents.",
                    native_then_human,
                ),
                HandsOperation(
                    "list_windows",
                    HandsDomain.WINDOW_MANAGEMENT,
                    "List bounded visible top-level Windows applications.",
                    native_then_human,
                ),
                HandsOperation(
                    "focus_window",
                    HandsDomain.WINDOW_MANAGEMENT,
                    "Bring an explicitly named application window to the foreground.",
                    native_then_human,
                ),
                HandsOperation(
                    "maximize_window",
                    HandsDomain.WINDOW_MANAGEMENT,
                    "Maximize an explicitly named application window.",
                    native_then_human,
                ),
                HandsOperation(
                    "minimize_window",
                    HandsDomain.WINDOW_MANAGEMENT,
                    "Minimize an explicitly named application window.",
                    native_then_human,
                ),
                HandsOperation(
                    "restore_window",
                    HandsDomain.WINDOW_MANAGEMENT,
                    "Restore an explicitly named application window.",
                    native_then_human,
                ),
                HandsOperation(
                    "move_window_to_next_monitor",
                    HandsDomain.WINDOW_MANAGEMENT,
                    "Move an explicitly named application window to another monitor.",
                    native_then_human,
                ),
                HandsOperation(
                    "open_app",
                    HandsDomain.APP_LIFECYCLE,
                    "Launch one explicitly approved local application and verify it runs.",
                    native_then_human,
                ),
                HandsOperation(
                    "execute_windows_plan",
                    HandsDomain.APP_UI,
                    "Perform bounded structured UI actions in an approved Windows app.",
                    ui_fallback,
                ),
                HandsOperation(
                    "execute_visual_desktop_task",
                    HandsDomain.VISUAL_COMPUTER,
                    "Use screenshot-based Computer Use only as an explicit fallback.",
                    (ExecutionSubstrate.VISUAL_FALLBACK, ExecutionSubstrate.HUMAN),
                ),
                HandsOperation(
                    "read_file",
                    HandsDomain.FILES_READ,
                    "Read bounded approved local text content.",
                    native,
                ),
                HandsOperation(
                    "read_document",
                    HandsDomain.FILES_READ,
                    "Read an approved local document through the isolated reader.",
                    native,
                ),
            )
        )

    @property
    def operations(self) -> tuple[HandsOperation, ...]:
        return tuple(sorted(self._operations.values(), key=lambda item: item.operation))

    def operation(self, name: str) -> HandsOperation | None:
        return self._operations.get(str(name).strip())

    def require(self, name: str) -> HandsOperation:
        operation = self.operation(name)
        if operation is None:
            raise ValueError(f"unknown JARVIS Hands operation: {name}")
        return operation

    def operations_for(self, domain: HandsDomain) -> tuple[HandsOperation, ...]:
        return tuple(item for item in self.operations if item.domain is domain)
