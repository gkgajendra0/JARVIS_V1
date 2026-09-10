from __future__ import annotations

import re
from pathlib import Path


SOURCE = Path("src/jarvis/voice/hands_goal_tools.py")
TESTS = Path("tests/test_hands_goal_tools.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def regex_once(
    text: str,
    pattern: str,
    replacement: str,
    label: str,
    *,
    flags: int = 0,
) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return updated


def patch_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from jarvis.hands.models import HandsWorkflowStep\n",
        "from jarvis.hands.models import HandsWorkflowStep\n"
        "from jarvis.hands.registry import HandsCapabilityRegistry\n",
        "registry import",
    )

    schema_block = '''_MAX_APP_CHARS = 160


def _build_use_computer_schema() -> dict[str, object]:
    """Build the voice tool contract from the canonical Hands registry.

    The language model owns semantic interpretation of the user's goal. The schema
    constrains it to canonical JARVIS operation names; deterministic code below owns
    target/material grounding and canonical AuthorityService owns permission.
    """

    registry = HandsCapabilityRegistry.default()
    operations = list(registry.operations)
    operation_names = [item.operation for item in operations]
    operation_guide = "\\n".join(
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
            "over visual fallback, and never invent material values. Available operations:\\n"
            + operation_guide
            + "\\nTo start/open/play a named installed local application or game, use open_app. "
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
'''
    text = replace_once(
        text,
        "_MAX_APP_CHARS = 160\n",
        schema_block,
        "schema insertion",
    )

    # Delete natural-language operation/verb allow-lists. The model/tool layer owns
    # semantic interpretation; deterministic code owns structural grounding and safety.
    text = regex_once(
        text,
        r'_MEDIA_CONTEXT_MARKERS = \(.*?\n_APP_OPERATIONS = \{',
        '_APP_OPERATIONS = {',
        "operation intent block",
        flags=re.DOTALL,
    )
    text = regex_once(
        text,
        r'_MUTATING_OPERATIONS = \{.*?\n\n\nclass HandsGoalGroundingError',
        'class HandsGoalGroundingError',
        "phrase grammar block",
        flags=re.DOTALL,
    )
    text = regex_once(
        text,
        r'def _strip_request_prefixes\(text: str\) -> str:.*?\n\n\ndef _require_material',
        'def _require_material',
        "explicit phrase parser",
        flags=re.DOTALL,
    )
    text = regex_once(
        text,
        r'def _browser_warranted\(user_text: str\) -> bool:.*?\n\n\ndef _repo_grounded',
        'def _repo_grounded',
        "browser phrase warrant",
        flags=re.DOTALL,
    )

    normalize_pattern = (
        r'        semantic = self\._runtime\.hands_registry\.require\(operation\)\n'
        r'.*?'
        r'        raw_parameters = raw\.get\("parameters", \{\}\)\n'
    )
    normalize_replacement = '''        semantic = self._runtime.hands_registry.require(operation)
        # The active model establishes semantic action intent by choosing use_computer
        # for the latest accepted USER turn. Do not re-parse natural language here with
        # a keyword/verb allow-list. This boundary validates canonical operation identity,
        # target/material grounding and bounded conversational references; canonical
        # AuthorityService independently owns risk, approval, permits and audit.

        raw_parameters = raw.get("parameters", {})
'''
    text = regex_once(
        text,
        normalize_pattern,
        normalize_replacement,
        "normalize-step semantic boundary",
        flags=re.DOTALL,
    )

    text = replace_once(
        text,
        "                allow_context=operation in _WINDOW_OPERATIONS,\n",
        "                allow_context=(\n"
        "                    operation in _WINDOW_OPERATIONS or operation == \"open_app\"\n"
        "                ),\n",
        "contextual app resolution",
    )

    tool_replacement = '''    @function_tool(raw_schema=_USE_COMPUTER_RAW_SCHEMA)
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
'''
    text = regex_once(
        text,
        r'    @function_tool\(\)\n    async def use_computer\(.*?\n            raise ToolError\(str\(exc\)\) from exc\n?$',
        tool_replacement,
        "raw use_computer tool",
        flags=re.DOTALL,
    )

    SOURCE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    tests = TESTS.read_text(encoding="utf-8")

    tests = regex_once(
        tests,
        r'\ndef test_declarative_power_statement_does_not_authorize_restart\(\) -> None:.*?(?=\n\ndef )',
        '\n',
        "old declarative phrase test",
        flags=re.DOTALL,
    )
    tests = regex_once(
        tests,
        r'\ndef test_app_launch_request_does_not_warrant_software_discovery\(\) -> None:.*?(?=\n\ndef )',
        '\n',
        "old software phrase test",
        flags=re.DOTALL,
    )

    if "test_semantic_app_grounding_is_not_tied_to_designated_command_phrases" in tests:
        raise SystemExit("semantic intent v2 tests already present")

    tests += '''

@pytest.mark.parametrize(
    "utterance",
    [
        "Jarvis, fire up FIFA for me.",
        "Could we get FIFA going?",
        "FIFA chala do.",
        "I would like FIFA running, please.",
        "Can you get FIFA started?",
        "Let's launch FIFA.",
    ],
)
def test_semantic_app_grounding_is_not_tied_to_designated_command_phrases(
    utterance: str,
) -> None:
    grounded = parse(tools(utterance), "open_app", {"app": "FIFA"})
    assert grounded == {"app": "FIFA"}


def test_phrase_independence_does_not_allow_model_to_substitute_app_target() -> None:
    with pytest.raises(HandsGoalGroundingError, match="model-selected app target"):
        parse(
            tools("Could we get FIFA going?"),
            "open_app",
            {"app": "Calculator"},
        )


def test_open_app_can_resolve_recent_conversation_target_from_pronoun() -> None:
    conversation = ConversationSession(session_id="hands-contextual-app")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "I want to play FIFA.")
    conversation.accept_turn(ConversationRole.USER, "Could you start it?")
    tool = HandsGoalAgentTools(runtime(), conversation)
    plan = json.dumps([{"operation": "open_app", "parameters": {"app": "FIFA"}}])
    step = tool._parse_plan(plan, tool._latest_user_turn().text)[0]
    assert step.parameters == {"app": "FIFA"}


def test_use_computer_schema_is_generated_from_canonical_registry() -> None:
    from jarvis.hands.registry import HandsCapabilityRegistry
    from jarvis.voice.hands_goal_tools import _USE_COMPUTER_RAW_SCHEMA

    plan = _USE_COMPUTER_RAW_SCHEMA["parameters"]["properties"]["plan"]
    operation_schema = plan["items"]["properties"]["operation"]
    assert set(operation_schema["enum"]) == {
        item.operation for item in HandsCapabilityRegistry.default().operations
    }
    assert plan["maxItems"] == 8
'''
    TESTS.write_text(tests, encoding="utf-8")


if __name__ == "__main__":
    patch_source()
    patch_tests()
