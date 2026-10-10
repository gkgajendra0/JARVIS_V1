"""Configured media routing hints cannot create trusted physical GICC identities."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.goal_intelligence import runtime as gicc_runtime


def test_default_media_target_is_not_automatically_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured TV name is not a verified, active physical device."""

    registered = []
    projected = []

    class RecordingWorld:
        def __init__(self, store: object) -> None:
            self.store = store

        def project_current_computer(self, catalog: object) -> None:
            projected.append(catalog)

        def register_entity(self, entity: object) -> None:
            registered.append(entity)

    class CompositionStop(Exception):
        pass

    def stop_before_planning(**_kwargs: object) -> None:
        raise CompositionStop

    monkeypatch.setattr(gicc_runtime, "WorldRegistry", RecordingWorld)
    monkeypatch.setattr(gicc_runtime, "build_default_goal_store", object)
    monkeypatch.setattr(gicc_runtime, "build_goal_interpreter", stop_before_planning)

    config = SimpleNamespace(
        ai_provider="fixture",
        chatgpt_plan_enabled=False,
        chatgpt_plan_model="fixture",
        hands_planner_model="fixture",
        work_orchestration_model="fixture",
        default_media_target="Living Room TV",
    )
    work_runtime = SimpleNamespace(
        capability_acquisition=object(),
        changes=object(),
    )
    catalog = object()
    capability_runtime = SimpleNamespace(catalog=catalog)
    capability_context = SimpleNamespace(current=lambda: object())

    with pytest.raises(CompositionStop):
        gicc_runtime.build_gicc_apply_runtime(
            config=config,
            capability_runtime=capability_runtime,
            work_runtime=work_runtime,
            capability_context=capability_context,
        )

    assert projected == [catalog]
    assert registered == [], (
        "A media routing preference must not become a verified physical target"
    )
