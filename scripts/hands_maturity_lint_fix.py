from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


path = Path("src/jarvis/hands/contracts.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'operation=str(getattr(action, "operation")),',
    'operation=str(action.operation),',
    "typed action operation access",
)
text = replace_once(
    text,
    'evidence=str(getattr(action, "evidence")),',
    'evidence=str(action.evidence),',
    "typed action evidence access",
)
path.write_text(text, encoding="utf-8")

path = Path("src/jarvis/hands/orchestrator.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from jarvis.hands.entities import AppEntityResolver, EntityResolutionError\n",
    "from jarvis.hands.entities import AppEntityResolver\n",
    "unused entity import",
)
text = replace_once(
    text,
    "from jarvis.hands.planner import HandsPlanningError, HandsRouteGroup\n",
    "from jarvis.hands.planner import HandsRouteGroup\n",
    "unused planning import",
)
text = replace_once(
    text,
    '''        try:
            selected = await self._planner.route(
                goal=latest,
                recent_user_turns=recent_user_turns,
                route_groups=route_groups,
            )
        except HandsPlanningError:
            raise
''',
    '''        selected = await self._planner.route(
            goal=latest,
            recent_user_turns=recent_user_turns,
            route_groups=route_groups,
        )
''',
    "redundant route re-raise",
)
text = replace_once(
    text,
    '''            if decision.goal_complete:
                if not results:
                    raise HandsOrchestrationError(
                        "planner claimed goal completion without any verified execution"
                    )
''',
    '''            if decision.goal_complete:
                if not results or not results[-1].ok:
                    raise HandsOrchestrationError(
                        "planner claimed goal completion without a successful latest execution"
                    )
''',
    "completion verification floor",
)
path.write_text(text, encoding="utf-8")
