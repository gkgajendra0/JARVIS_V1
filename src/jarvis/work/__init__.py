"""Persistent concurrent work orchestration foundation for JARVIS V1.

The package facade is lazy so leaf modules such as work.models can be imported
without initializing the work engine and its model-routing integration.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BrainAction": "jarvis.work.brain",
    "BrainCoordinator": "jarvis.work.brain",
    "BrainDecision": "jarvis.work.brain",
    "BrainRequest": "jarvis.work.brain",
    "WorkActionRegistry": "jarvis.work.engine",
    "WorkAdvanceResult": "jarvis.work.engine",
    "WorkEngine": "jarvis.work.engine",
    "DeliveryPolicy": "jarvis.work.models",
    "WorkItem": "jarvis.work.models",
    "WorkPriority": "jarvis.work.models",
    "WorkState": "jarvis.work.models",
    "WorkStep": "jarvis.work.models",
    "WorkStepState": "jarvis.work.models",
    "WorkType": "jarvis.work.models",
    "WorkOrchestrator": "jarvis.work.orchestrator",
    "WorkSubmission": "jarvis.work.orchestrator",
    "SQLiteWorkStore": "jarvis.work.store",
    "WorkStoreError": "jarvis.work.store",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_EXPORTS))
