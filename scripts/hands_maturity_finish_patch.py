from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return updated


# 1. Reconcile planner response contract with the iterative act/observe loop.
path = Path("src/jarvis/hands/contracts.py")
text = path.read_text(encoding="utf-8")
text = regex_once(
    text,
    r"@dataclass\(frozen=True, slots=True\)\nclass PlannedAction:.*\Z",
    '''@dataclass(frozen=True, slots=True)
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
            operation=str(getattr(action, "operation")),
            parameters=parameters_model.model_dump(exclude_none=True),
            evidence=str(getattr(action, "evidence")),
        )
    )
''',
    "planner contract tail",
)
path.write_text(text, encoding="utf-8")

# 2. Make planner return explicit PlannerTurn completion state.
path = Path("src/jarvis/hands/planner.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    PlannedAction,\n",
    "    PlannerTurn,\n",
    "planner import",
)
text = replace_once(
    text,
    "- Set ``continue_after_success`` true only when another action will still be required to\n  finish the same user goal. Otherwise set it false.\n",
    "- After each observation, set ``goal_complete=true`` only when the entire original USER\n  goal is now visibly/semantically satisfied. Return no action in that case. Otherwise\n  return exactly one next action.\n",
    "planner completion prompt",
)
text = replace_once(
    text,
    "    ) -> PlannedAction | str:\n",
    "    ) -> PlannerTurn:\n",
    "planner return annotation",
)
path.write_text(text, encoding="utf-8")

# 3. Replace the old model-generated plan_json voice boundary with a zero-argument handoff.
Path("src/jarvis/voice/hands_goal_tools.py").write_text(
    '''"""Single voice-facing handoff to the mature JARVIS Hands orchestrator."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.hands.orchestrator import HandsOrchestrationError, HandsOrchestrator
from jarvis.hands.planner import HandsPlanningError

# Compatibility alias for older imports/tests while the implementation is no longer a
# phrase/keyword grounding parser.
HandsGoalGroundingError = HandsOrchestrationError


class HandsGoalAgentTools:
    """Hand the canonical USER goal to Hands; the realtime model never builds plans."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        conversation: ConversationSession,
        *,
        orchestrator: HandsOrchestrator | None = None,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._runtime = runtime
        self._conversation = conversation
        self._orchestrator = orchestrator

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
            raise HandsOrchestrationError(
                "JARVIS Hands requires a latest accepted USER utterance"
            )
        return turn

    def _recent_user_turns(self, latest: ConversationTurn) -> tuple[str, ...]:
        users = [
            turn.text
            for turn in self._conversation.turns
            if turn.role is ConversationRole.USER and turn.turn_id != latest.turn_id
        ]
        return tuple(users[-6:])

    def _get_orchestrator(self) -> HandsOrchestrator:
        if self._orchestrator is not None:
            return self._orchestrator
        planner = self._runtime.hands_planner
        if planner is None:
            raise HandsOrchestrationError(
                "JARVIS Hands semantic planner is not configured"
            )
        self._orchestrator = HandsOrchestrator(self._runtime, planner)
        return self._orchestrator

    async def execute_goal(self) -> dict[str, object]:
        turn = self._latest_user_turn()
        result = await self._get_orchestrator().execute_goal(
            session_id=self._conversation.session_id,
            goal=turn.text,
            recent_user_turns=self._recent_user_turns(turn),
        )
        result["canonical_user_turn_id"] = turn.turn_id
        return result

    @function_tool()
    async def use_computer(self, context: RunContext) -> dict[str, object]:
        """Hand the latest accepted USER computer goal to JARVIS Hands.

        Call this whenever the USER asks JARVIS to operate or inspect the local computer.
        Do not construct capability names, operation plans, selectors, app IDs, package IDs,
        or execution parameters yourself. This tool takes no plan arguments: JARVIS Hands
        internally performs semantic routing, canonical entity resolution, strongly typed
        planning, proportional Authority, verified execution, and bounded recovery.

        If the result has status ``clarification_required``, ask the returned clarification
        question. Otherwise treat the tool result as authoritative and never claim success
        for denied, failed, unavailable, or unverified work.
        """
        del context
        try:
            return await self.execute_goal()
        except (HandsOrchestrationError, HandsPlanningError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
''',
    encoding="utf-8",
)

# 4. CapabilityRuntime owns the dedicated Hands planner and filters disabled single executors.
path = Path("src/jarvis/capabilities/runtime.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        hands_registry: HandsCapabilityRegistry | None = None,\n",
    "        hands_registry: HandsCapabilityRegistry | None = None,\n        hands_planner=None,\n",
    "runtime ctor planner parameter",
)
text = replace_once(
    text,
    "        self._hands_registry = hands_registry or HandsCapabilityRegistry.default()\n        self._catalog: CapabilityCatalog | None = None\n",
    "        self._hands_registry = hands_registry or HandsCapabilityRegistry.default()\n        self._hands_planner = hands_planner\n        self._catalog: CapabilityCatalog | None = None\n",
    "runtime planner storage",
)
text = replace_once(
    text,
    "    @property\n    def hands_registry(self) -> HandsCapabilityRegistry:\n        return self._hands_registry\n\n",
    "    @property\n    def hands_registry(self) -> HandsCapabilityRegistry:\n        return self._hands_registry\n\n    @property\n    def hands_planner(self):\n        return self._hands_planner\n\n",
    "runtime planner property",
)
text = replace_once(
    text,
    "        if len(candidates) == 1:\n            return candidates[0]\n",
    "        if len(candidates) == 1:\n            descriptor = self.catalog.by_key(candidates[0])\n            return (\n                candidates[0]\n                if descriptor is not None and descriptor.execution_enabled\n                else None\n            )\n",
    "single executor availability",
)
text = replace_once(
    text,
    "def build_default_capability_runtime(\n    *,\n    ai_provider: str | None = None,\n) -> CapabilityRuntime:\n",
    "def build_default_capability_runtime(\n    *,\n    ai_provider: str | None = None,\n    hands_planner_model: str | None = None,\n) -> CapabilityRuntime:\n",
    "runtime builder signature",
)
text = replace_once(
    text,
    "    return CapabilityRuntime(\n        executors=executor_tuple,\n        resolver=resolver,\n        authority=CapabilityAuthorityBroker(),\n        hands_registry=HandsCapabilityRegistry.default(),\n    )\n",
    "    hands_planner = None\n    if ai_provider is not None:\n        from jarvis.hands.planner import build_hands_planner\n\n        hands_planner = build_hands_planner(\n            provider=ai_provider,\n            model=hands_planner_model,\n        )\n    return CapabilityRuntime(\n        executors=executor_tuple,\n        resolver=resolver,\n        authority=CapabilityAuthorityBroker(),\n        hands_registry=HandsCapabilityRegistry.default(),\n        hands_planner=hands_planner,\n    )\n",
    "runtime builder planner",
)
path.write_text(text, encoding="utf-8")

# 5. Add optional planner model configuration.
path = Path("src/jarvis/config.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    gemini_realtime_voice: str = \"Charon\"\n",
    "    gemini_realtime_voice: str = \"Charon\"\n    hands_planner_model: str | None = None\n",
    "config planner field",
)
text = replace_once(
    text,
    "            \"memory_semantic_recall_model\",\n",
    "            \"memory_semantic_recall_model\",\n            \"hands_planner_model\",\n",
    "config optional planner normalization",
)
text = replace_once(
    text,
    "            gemini_realtime_voice=_configured_required_text(\n                \"JARVIS_GEMINI_REALTIME_VOICE\", \"Charon\", machine\n            ),\n",
    "            gemini_realtime_voice=_configured_required_text(\n                \"JARVIS_GEMINI_REALTIME_VOICE\", \"Charon\", machine\n            ),\n            hands_planner_model=_configured_optional_text(\n                \"JARVIS_HANDS_PLANNER_MODEL\", machine\n            ),\n",
    "config planner environment",
)
path.write_text(text, encoding="utf-8")

# 6. Build and report the dedicated Hands planner in production.
path = Path("src/jarvis/voice/production_runtime.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    capability_runtime = build_default_capability_runtime(\n        ai_provider=config.ai_provider\n    )\n",
    "    capability_runtime = build_default_capability_runtime(\n        ai_provider=config.ai_provider,\n        hands_planner_model=config.hands_planner_model,\n    )\n",
    "production planner build",
)
text = replace_once(
    text,
    "    browser_hands = capability_catalog.by_key(\"browser:playwright\")\n    LOGGER.info(\n        \"Governed capability runtime configured: capabilities=%s read_executors=2 \"\n        \"structured_desktop_control=%s visual_fallback=%s browser_control=%s \"\n        \"raw_shell=False\",\n        len(capability_catalog.capabilities),\n        bool(structured_hands and structured_hands.execution_enabled),\n        bool(visual_hands and visual_hands.execution_enabled),\n        bool(browser_hands and browser_hands.execution_enabled),\n    )\n",
    "    browser_hands = capability_catalog.by_key(\"browser:playwright\")\n    hands_planner = capability_runtime.hands_planner\n    LOGGER.info(\n        \"Governed capability runtime configured: capabilities=%s \"\n        \"structured_desktop_control=%s visual_fallback=%s browser_control=%s \"\n        \"hands_planner=%s/%s raw_shell=False\",\n        len(capability_catalog.capabilities),\n        bool(structured_hands and structured_hands.execution_enabled),\n        bool(visual_hands and visual_hands.execution_enabled),\n        bool(browser_hands and browser_hands.execution_enabled),\n        getattr(hands_planner, \"provider_name\", \"none\"),\n        getattr(hands_planner, \"model_name\", \"none\"),\n    )\n",
    "production planner log",
)
path.write_text(text, encoding="utf-8")

# 7. Expose only the specialist Hands boundary to the realtime brain. Legacy direct
# inspect_local remains callable internally but is not a second competing model tool.
path = Path("src/jarvis/voice/capability_tools.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    def tools(self) -> list:\n        return [self.inspect_local, *self._hands.tools]\n",
    "    def tools(self) -> list:\n        return [*self._hands.tools]\n",
    "single Hands tool surface",
)
path.write_text(text, encoding="utf-8")

# 8. Update voice policy: the realtime model hands off, it does not plan.
path = Path("src/jarvis/voice/agent.py")
text = path.read_text(encoding="utf-8")
text = regex_once(
    text,
    r"When `use_computer` is available, treat it as the single JARVIS Hands boundary.*?(?=\nWhen local vision diagnostics are available)",
    '''When `use_computer` is available, treat it as the single JARVIS Hands specialist
handoff for local computer outcomes and reads. If the latest accepted USER utterance asks
JARVIS to operate or inspect the local computer, call `use_computer`. Do not build a plan,
choose internal capability names, invent app IDs, selectors, package IDs, paths, or
execution parameters. The tool intentionally takes no plan arguments: the canonical goal
is the latest accepted USER utterance already owned by JARVIS.

Hands internally performs semantic routing over a small relevant capability shortlist,
canonical entity resolution against machine-owned sources, strongly typed planning,
proportional Authority, one-time permit validation, verified execution, and bounded
observation/replanning. Do not ask the USER to rephrase merely because you do not know an
internal tool or application adapter, and do not ask them for click-by-click instructions.

If `use_computer` returns `status=clarification_required`, ask its returned
`clarification_question` because Hands has determined that material ambiguity genuinely
blocks safe progress. Otherwise the tool result is authoritative: never claim success for
denied, failed, unavailable, or unverified work, and never claim that a later part of a
multi-step goal completed merely because an earlier action succeeded.

''',
    "voice Hands instructions",
)
path.write_text(text, encoding="utf-8")

# 9. Replace old phrase-parser tests with specialist handoff tests.
Path("tests/test_hands_goal_tools.py").write_text(
    '''from __future__ import annotations

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.hands_goal_tools import HandsGoalAgentTools


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in handoff-only tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in handoff-only tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in handoff-only tests")

    def close(self) -> None:
        pass


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    async def execute_goal(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "status": "succeeded", "completed_steps": 1}


def runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


@pytest.mark.asyncio
async def test_voice_hands_handoff_uses_exact_latest_user_goal_without_plan_json() -> None:
    conversation = ConversationSession(session_id="hands-handoff")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Open Apple Music")
    latest = conversation.accept_turn(
        ConversationRole.USER,
        "Could you get FIFA going for me?",
    )
    fake = FakeOrchestrator()
    tools = HandsGoalAgentTools(runtime(), conversation, orchestrator=fake)

    result = await tools.execute_goal()

    assert result["ok"] is True
    assert result["canonical_user_turn_id"] == latest.turn_id
    assert fake.calls == [
        {
            "session_id": "hands-handoff",
            "goal": "Could you get FIFA going for me?",
            "recent_user_turns": ("Open Apple Music",),
        }
    ]


def test_voice_exposes_one_hands_specialist_tool() -> None:
    conversation = ConversationSession(session_id="hands-tool-surface")
    conversation.start()
    tools = HandsGoalAgentTools(runtime(), conversation, orchestrator=FakeOrchestrator())

    assert [tool.id for tool in tools.tools] == ["use_computer"]
''',
    encoding="utf-8",
)

# 10. Production composition now exposes one local-computer specialist tool.
Path("tests/test_production_hands_voice_wiring.py").write_text(
    '''from __future__ import annotations

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationSession
from jarvis.voice import canonical_active_speaker_runtime as active_runtime
from jarvis.voice.capability_tools import LocalReadAgentTools


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run while composing voice tools")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run while composing voice tools")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run while composing voice tools")

    def close(self) -> None:
        pass


def _runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def _conversation() -> ConversationSession:
    conversation = ConversationSession(session_id="production-hands-voice-wiring")
    conversation.start()
    return conversation


def test_local_computer_toolset_exposes_only_hands_specialist_boundary() -> None:
    toolset = LocalReadAgentTools(_runtime(), _conversation())
    assert [tool.id for tool in toolset.tools] == ["use_computer"]


def test_production_session_bundle_includes_hands_specialist_tool(monkeypatch) -> None:
    runtime = _runtime()
    conversation = _conversation()
    sentinel_hands = object()
    seen = []

    class FakeLocalReadAgentTools:
        def __init__(self, capability_runtime, session_conversation) -> None:
            seen.append((capability_runtime, session_conversation))

        @property
        def tools(self) -> list[object]:
            return [sentinel_hands]

    monkeypatch.setattr(active_runtime, "LocalReadAgentTools", FakeLocalReadAgentTools)
    bundle = active_runtime._SessionToolBundle(
        None,
        lambda: conversation,
        memory_runtime=None,
        memory_query_coordinator=None,
        research_service=None,
        capability_runtime=runtime,
    )

    assert bundle.tools == [sentinel_hands]
    assert seen == [(runtime, conversation)]
''',
    encoding="utf-8",
)
