from __future__ import annotations

from jarvis.voice.vision_tools import VisionAgentTools


class _FakeService:
    def report(self, *, event_limit: int = 12) -> dict[str, object]:
        del event_limit
        return {
            "status": {
                "running": True,
                "detector_persons": 2,
                "visible_people": 1,
                "visible_heads": 1,
                "target_id": 0,
                "target_visible": True,
                "armed": False,
                "framing_source": "head",
            },
            "recent_events": [
                {
                    "sequence": 1,
                    "observed_at": 1.0,
                    "code": "people_count_changed",
                    "message": (
                        "Visible person tracks changed from 0 to 1; "
                        "RF-DETR=2, BoT-SORT=1, heads=1."
                    ),
                }
            ],
            "camera": {
                "active": "lenovo",
                "available": ["lenovo", "pocket3"],
            },
        }

    def switch_camera(self, profile: str) -> dict[str, object]:
        return {
            "ok": True,
            "active_camera": profile,
            "changed": True,
        }


def test_voice_report_hides_detector_candidate_count() -> None:
    tools = VisionAgentTools(_FakeService())  # type: ignore[arg-type]

    report = tools._voice_report(event_limit=8)
    status = report["status"]

    assert isinstance(status, dict)
    assert status["visible_people"] == 1
    assert "detector_persons" not in status
    assert "armed" not in status
    assert "target_id" not in status
    assert "target_visible" not in status
    assert report["camera"] == {
        "active": "lenovo",
        "available": ["lenovo", "pocket3"],
    }
    assert "visible_people is the only canonical visible-person count" in str(
        report["count_semantics"]
    )

    events = report["recent_events"]
    assert isinstance(events, list)
    assert "RF-DETR" not in str(events)
    assert "current visible_people=1" in str(events)


def test_realtime_voice_surface_exposes_camera_switch_not_manual_follow() -> None:
    tools = VisionAgentTools(_FakeService())  # type: ignore[arg-type]

    assert len(tools.tools) == 2
    names = {tool.__name__ for tool in tools.tools}
    assert names == {"inspect_vision", "switch_vision_camera"}
