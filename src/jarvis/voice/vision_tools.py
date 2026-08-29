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

    def _voice_report(self, *, event_limit: int) -> dict[str, object]:
        """Expose tracker truth without detector-candidate telemetry to the LLM."""
        report = self._service.report(event_limit=event_limit)
        raw_status = report.get("status", {})
        status = dict(raw_status) if isinstance(raw_status, dict) else {}
        status.pop("detector_persons", None)

        safe_events: list[dict[str, object]] = []
        raw_events = report.get("recent_events", [])
        if isinstance(raw_events, list):
            for item in raw_events:
                if not isinstance(item, dict):
                    continue
                event = dict(item)
                if event.get("code") == "people_count_changed":
                    visible_people = status.get("visible_people", 0)
                    event["message"] = (
                        "The canonical visible tracked-person count changed; "
                        f"current visible_people={visible_people}."
                    )
                safe_events.append(event)

        return {
            "status": status,
            "recent_events": safe_events,
            "count_semantics": (
                "visible_people is the only canonical visible-person count. "
                "Detector candidate counts are engineering telemetry and are "
                "intentionally not exposed to the voice agent."
            ),
        }

    @function_tool()
    async def inspect_vision(self, context: RunContext) -> dict[str, object]:
        """Read current tracking/head/framing state and recent vision events.

        `status.visible_people` is the ONLY authoritative answer for how many people
        are currently visible to tracking. Detector candidate counts are intentionally
        hidden because multiple low-confidence boxes can belong to the same person.
        This tool does not expose image pixels or general scene understanding. Use it
        for tracked-person count, head-detection count, target/follow state, current
        framing source, adaptive zoom command state, and recent tracking transitions.
        `framing_source` may be `head`, `head_hold`, `body`, or null; do not describe
        a current head detection when the status says `head_hold` or `body`. Do not
        use this tool to infer clothing colour, arbitrary objects, text, furniture,
        facial appearance, identity, or any other visual detail absent from the
        returned fields.
        """
        del context
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
            **self._voice_report(event_limit=16),
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
        restricted to exactly one visible head-confirmed tracked person and does not
        assert that person's identity. A successful `lock` result is authoritative;
        do not contradict it by inventing additional visible people. Never arm follow
        merely because a person is visible. When follow is armed, adaptive zoom is
        automatic and uses only the already locked BODY track's apparent size; zoom
        never selects or changes a target.
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
                    "vision": self._voice_report(event_limit=8),
                }
        except (RuntimeError, ValueError) as exc:
            return {
                "ok": False,
                "reason": str(exc),
                "vision": self._voice_report(event_limit=8),
            }

        return {
            **result,
            "vision": self._voice_report(event_limit=8),
        }
