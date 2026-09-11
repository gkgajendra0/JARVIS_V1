"""Generic multilingual material grounding for voice-originated JARVIS Hands.

The core orchestrator intentionally remains strict and literal for programmatic callers.
Voice transcripts can represent the same spoken material in different scripts. This
adapter proves cross-script equivalence locally, then augments the evidence view consumed
by the existing strict grounding checks. It never changes the canonical USER transcript,
never invents a machine target, and never relaxes identifiers/URLs/paths.
"""

from __future__ import annotations

from collections.abc import Iterable

from jarvis.hands.contracts import PlannedAction
from jarvis.hands.grounding import DEFAULT_GROUNDING, GroundingMode, GroundingService
from jarvis.hands.multilingual import has_contextual_reference
from jarvis.hands.orchestrator import GroundingContext
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator


class GenericGroundedVoiceHandsOrchestrator(VoiceHandsOrchestrator):
    """Voice Hands with one reusable multilingual material-proof layer."""

    def __init__(
        self, *args, grounding: GroundingService | None = None, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self._grounding = grounding or DEFAULT_GROUNDING

    @staticmethod
    def _groundable_materials(
        action: PlannedAction,
    ) -> Iterable[tuple[object, GroundingMode]]:
        params = action.parameters
        operation = action.operation

        # App identity itself is handled by AppEntityResolver, which uses the same
        # GroundingService against the Windows-owned app catalogue.
        if operation == "execute_windows_plan":
            plan = params.get("plan")
            if isinstance(plan, list):
                for step in plan:
                    if not isinstance(step, dict):
                        continue
                    step_action = str(step.get("action") or "").casefold()
                    if step_action == "search" and step.get("query"):
                        yield step["query"], GroundingMode.SEARCH
                    elif step_action in {"send_text", "set_value"} and step.get("text"):
                        yield step["text"], GroundingMode.LITERAL
                    elif step_action == "verify_value" and step.get("expected"):
                        yield step["expected"], GroundingMode.SEARCH
            return

        if operation == "set_clipboard_text" and params.get("text"):
            yield params["text"], GroundingMode.LITERAL
            return

        if operation == "execute_browser_plan":
            plan = params.get("plan")
            if isinstance(plan, list):
                for step in plan:
                    if (
                        isinstance(step, dict)
                        and str(step.get("action") or "").casefold() == "fill"
                        and step.get("text")
                    ):
                        yield step["text"], GroundingMode.LITERAL
            return

        if operation in {"create_text_file", "replace_text_file", "append_text_file"}:
            if params.get("text"):
                yield params["text"], GroundingMode.LITERAL
            return

        if operation in {"create_docx", "append_docx_paragraph"}:
            if params.get("text"):
                yield params["text"], GroundingMode.LITERAL
            return

        if operation in {"create_pptx", "add_pptx_text_slide"}:
            if params.get("title"):
                yield params["title"], GroundingMode.LITERAL
            if params.get("body"):
                yield params["body"], GroundingMode.LITERAL
            return

        if operation == "set_xlsx_cell" and params.get("value") is not None:
            yield params["value"], GroundingMode.LITERAL
            return

        if operation in {"pair_bluetooth_device", "unpair_bluetooth_device"}:
            if params.get("name"):
                yield params["name"], GroundingMode.ENTITY
            return

        if operation in {"search_software", "list_installed_software"}:
            if params.get("query"):
                yield params["query"], GroundingMode.SEARCH
            return

        if (
            operation in {"get_display_brightness", "set_display_brightness"}
            and params.get("display")
        ):
            yield params["display"], GroundingMode.ENTITY

    def _grounding_context(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ) -> GroundingContext:
        latest = context.latest_user_text
        recent = list(context.recent_user_texts)
        latest_aliases: list[str] = []
        recent_aliases: dict[int, list[str]] = {}

        can_reference_recent = has_contextual_reference(latest)
        sources = (latest, *reversed(recent)) if can_reference_recent else (latest,)

        for value, mode in self._groundable_materials(action):
            candidate = str(value or "").strip()
            if not candidate:
                continue
            proof = self._grounding.prove(candidate, sources, mode=mode)
            if not proof.matched or proof.source is None:
                continue
            if proof.source == latest:
                if candidate not in latest_aliases:
                    latest_aliases.append(candidate)
                continue
            for index, source in enumerate(recent):
                if source == proof.source:
                    recent_aliases.setdefault(index, [])
                    if candidate not in recent_aliases[index]:
                        recent_aliases[index].append(candidate)
                    break

        if latest_aliases:
            latest = f"{latest} {' '.join(latest_aliases)}"
        for index, aliases in recent_aliases.items():
            recent[index] = f"{recent[index]} {' '.join(aliases)}"

        return GroundingContext(latest, tuple(recent))

    def _normalize_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ):
        return super()._normalize_action(
            action, self._grounding_context(action, context)
        )
