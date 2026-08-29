"""Voice-agent tools for inspecting and explicitly controlling local vision tests."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool

from jarvis.vision.service import VisionService


class VisionAgentTools:
    """Bind one integrated VisionService to a small LiveKit tool surface."""

    def __init__(self, service: VisionService) -> None:
        self._service = service

    @property
    def tools(self) -> list:
        return [self.inspect_vision, self.control_vision_follow]

    @function_tool()
    async def inspect_vision(self, context: RunContext) -> dict[str, object]:
        """Read current tracking/head/framing state and recent vision events.

        This tool does not expose image pixels or general scene understanding. Use it
        for person-track counts, head-detection counts, target/follow state, current
        framing source, adaptive zoom command state, and recent tracking transitions.
        `framing_source` may be `head`, `head_hold`, `body`, or null; do not describe
        a current head detection when the status says `head_hold` or `body`. Do not
        use this tool to infer clothing colour, arbitrary objects, text, furniture,
        facial appearance, identity, or any other visual detail absent from the
        returned fields.
        """
        del context
        report = self._service.report(event_limit=16)
        return {
            "capabilities": [
                "person_track_count",
                "head_detection_count",
                "target_visibility",
                "follow_armed_state",
                "framing_source",
                "adaptive_target_zoom",
                "recent_tracking_transitions",
            ],
            "not_available": [
                "raw_image_pixels",
                "clothing_colour",
                "general_object_recognition",
                "text_or_ocr",
                "scene_description",
                "facial_appearance_or_identity",
            ],
            **report,
        }

    @function_tool()
    async def control_vision_follow(
        self,
        context: RunContext,
        action: str,
    ) -> dict[str, object]:
        """Perform an explicit local vision-test control action.

        Supported actions are `lock`, `arm`, `disarm`, and `clear`. Only call this
        tool when the user explicitly asks for that control. `lock` is deliberately
        restricted to exactly one visible head-confirmed person and does not assert
        that person's identity. Never arm follow merely because a person is visible.
        When follow is armed, adaptive zoom is automatic and uses only the already
        locked BODY track's apparent size; zoom never selects or changes a target.
        """
        del context
        normalized = action.strip().lower()
        try:
            if normalized == "lock":
                result = self._service.lock_only_confirmed_person()
            elif normalized == "arm":
                result = self._service.arm_follow()
            elif normalized == "disarm":
                result = self._service.disarm_follow()
            elif normalized == "clear":
                result = self._service.clear_target()
            else:
                return {
                    "ok": False,
                    "reason": "unsupported action; use lock, arm, disarm, or clear",
                    "vision": self._service.report(event_limit=8),
                }
        except (RuntimeError, ValueError) as exc:
            return {
                "ok": False,
                "reason": str(exc),
                "vision": self._service.report(event_limit=8),
            }

        return {
            **result,
            "vision": self._service.report(event_limit=8),
        }
