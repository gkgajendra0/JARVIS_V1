"""Security and behavior contract for the optional local JARVIS HUD."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.ui.hub import UISnapshotHub
from jarvis.ui.activity import HUDActivityFeed
from jarvis.ui.runtime import (
    build_runtime_hub,
    project_voice_state,
    start_ui_if_enabled,
)
from jarvis.ui.server import create_ui_server


class HubTests(unittest.TestCase):
    def test_voice_offline_keeps_independent_work_and_link(self):
        snapshot = UISnapshotHub(
            voice_provider=lambda: {"state": "offline"},
            work_provider=lambda: [
                {
                    "id": "work_1111111111111111",
                    "type": "research",
                    "state": "waiting_for_owner",
                    "progress": 70,
                    "approximate": True,
                    "milestone": "evidence_gathered",
                    "eta_low_seconds": None,
                    "eta_high_seconds": None,
                    "private_request": "my banking password",
                }
            ],
        ).snapshot()
        self.assertEqual(snapshot["schema"], 2)
        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["voice"], {"state": "offline"})
        self.assertEqual(snapshot["work"][0]["progress"], 70)
        self.assertEqual(snapshot["work"][0]["id"], "work_1111111111111111")
        self.assertEqual(snapshot["attention_count"], 1)
        self.assertNotIn("banking", json.dumps(snapshot))

    def test_work_milestone_does_not_echo_arbitrary_private_slug(self):
        snapshot = UISnapshotHub(
            work_provider=lambda: [
                {"type": "development", "state": "running", "milestone": "secret_password"}
            ]
        ).snapshot()
        self.assertEqual(snapshot["work"], [{"type": "development", "state": "running"}])

    def test_rejects_unknown_optional_fields_and_preserves_valid_telemetry(self):
        snapshot = UISnapshotHub(
            voice_provider=lambda: {"state": "listening"},
            feature_provider=lambda: {
                "work": "disabled", "vision": "ready", "memory": "disabled",
                "learning": "disabled", "hands": "unavailable",
                "research": "ready", "extra": "private"
            },
            model_provider=lambda: {
                "voice": {"name": "gemini", "model": "gemini-live", "api_key": "private"},
                "research": {"name": "exa", "model": "search", "token": "private"},
            },
            vision_provider=lambda: {
                "state": "active", "people": 2, "target": "visible", "frame": "private",
            },
            health_provider=lambda: [{"component": "voice", "state": "warning"}],
        ).snapshot()
        self.assertEqual(snapshot["features"]["work"], "disabled")
        self.assertEqual(snapshot["models"]["voice"], {"name": "gemini", "model": "gemini-live"})
        self.assertEqual(snapshot["vision"], {"state": "active", "people": 2, "target": "visible"})
        self.assertEqual(snapshot["health"], [{"component": "voice", "state": "warning"}])
        self.assertNotIn("private", json.dumps(snapshot))

    def test_unhashable_provider_values_fail_closed_instead_of_crashing_api(self):
        snapshot = UISnapshotHub(
            voice_provider=lambda: {"state": ["speaking"]},
            vision_provider=lambda: {"state": [], "frame": [], "target": []},
            model_provider=lambda: {"voice": {"name": ["secret"]}},
        ).snapshot()
        self.assertEqual(snapshot["voice"], {"state": "offline"})
        self.assertEqual(snapshot["vision"], {"state": "offline"})
        self.assertEqual(snapshot["models"], {})

        only_invalid_voice = UISnapshotHub(voice_provider=lambda: {"state": "admin"}).snapshot()
        self.assertFalse(only_invalid_voice["connected"])

    def test_one_failing_provider_does_not_hide_other_status(self):
        def broken():
            raise RuntimeError("secret credential")

        snapshot = UISnapshotHub(
            voice_provider=broken,
            feature_provider=lambda: {"work": "ready"},
        ).snapshot()
        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["voice"], {"state": "offline"})
        self.assertEqual(snapshot["features"]["work"], "ready")
        self.assertNotIn("secret", json.dumps(snapshot))

    def test_live_work_status_marks_failed_adapter_degraded(self):
        def broken():
            raise OSError("secret work database")

        snapshot = UISnapshotHub(
            voice_provider=lambda: {"state": "standby"},
            feature_provider=lambda: {"work": "ready"},
            work_provider=broken,
        ).snapshot()
        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["features"]["work"], "degraded")
        self.assertNotIn("secret", json.dumps(snapshot))

    def test_disconnected_snapshot_does_not_fake_live_telemetry(self):
        snapshot = UISnapshotHub().snapshot()
        self.assertEqual(snapshot["schema"], 2)
        self.assertFalse(snapshot["connected"])
        self.assertEqual(snapshot["voice"]["state"], "offline")
        self.assertEqual(snapshot["work"], [])
        self.assertEqual(snapshot["health"], [])

    def test_provider_values_are_bounded_and_allowlisted(self):
        hub = UISnapshotHub(
            voice_provider=lambda: {"state": "speaking", "transcript": "secret"},
            work_provider=lambda: [
                {"type": "research", "state": "running", "payload": "secret"}
                for _ in range(60)
            ],
            health_provider=lambda: [
                {"component": "audio", "state": "healthy", "secret": "token"},
                {"component": "X" * 900, "state": "unknown"},
            ],
            vision_provider=lambda: {"state": "active", "frame": "secret"},
        )
        snapshot = hub.snapshot()
        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["voice"], {"state": "speaking"})
        self.assertLessEqual(len(snapshot["work"]), 6)
        self.assertEqual(
            snapshot["health"][0], {"component": "audio", "state": "healthy"}
        )
        self.assertNotIn("secret", json.dumps(snapshot))
        self.assertLess(len(json.dumps(snapshot)), 1800)

    def test_bad_provider_is_isolated(self):
        def broken():
            raise RuntimeError("private path /owner/secrets")

        snapshot = UISnapshotHub(voice_provider=broken).snapshot()
        self.assertFalse(snapshot["connected"])
        self.assertNotIn("private", json.dumps(snapshot))


class ActivityFeedTests(unittest.TestCase):
    def test_canonical_events_are_bounded_and_never_serialize_private_payload(self):
        feed = HUDActivityFeed()
        for _ in range(30):
            feed.observe_turn(SimpleNamespace(role="user", text="private user health data"))
        feed.record_capability(SimpleNamespace(
            status="denied", capability_key="browser:playwright", operation="private-url",
            reason="token secret", data={"password": "abc"},
        ))
        feed.record_research({
            "status": "multi_source_researched", "query": "private query",
            "sources": [{"url": "private source"}], "provider": "exa",
        })
        snapshot = UISnapshotHub(
            voice_provider=lambda: {"state": "standby"},
            activity_provider=feed.snapshot,
        ).snapshot()
        self.assertLessEqual(len(snapshot["activity"]), 12)
        self.assertEqual(snapshot["activity"][0]["kind"], "research")
        self.assertEqual(snapshot["activity"][1]["state"], "denied")
        self.assertEqual(snapshot["activity"][2]["label"], "USER TURN")
        self.assertNotIn("private", json.dumps(snapshot))
        self.assertNotIn("secret", json.dumps(snapshot))
        self.assertNotIn("password", json.dumps(snapshot))

    def test_unknown_status_and_exceptions_cannot_corrupt_feed(self):
        feed = HUDActivityFeed()
        feed.record_capability(SimpleNamespace(
            status="other", capability_key="fake:private", operation="secret", data={},
        ))
        feed.record_research({"status": "private", "query": "secret"})
        feed.observe_turn(SimpleNamespace(role="unknown", text="secret"))
        self.assertEqual(feed.snapshot(), [])

    def test_activity_provider_failure_only_hides_activity(self):
        snapshot = UISnapshotHub(
            voice_provider=lambda: {"state": "speaking"},
            activity_provider=lambda: (_ for _ in ()).throw(ValueError("secret")),
        ).snapshot()
        self.assertEqual(snapshot["voice"]["state"], "speaking")
        self.assertEqual(snapshot["activity"], [])

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.asset_dir = Path(self.tmp.name)
        (self.asset_dir / "index.html").write_text("HUD READY", encoding="utf-8")
        self.server = create_ui_server(UISnapshotHub(), port=0, assets=self.asset_dir)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_snapshot_and_static_work_only_on_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, body = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot["schema"], 2)
        self.assertFalse(snapshot["connected"])
        self.assertEqual(snapshot["activity"], [])
        self.assertEqual(snapshot["features"], {})
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/")[2], b"HUD READY")

    def test_embedded_reactor_styles_can_load_under_csp(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(
            "style-src-attr 'unsafe-inline'", headers["Content-Security-Policy"]
        )

    def test_all_mutating_and_preflight_verbs_are_refused(self):
        self.assertEqual(self.request("OPTIONS", "/api/snapshot")[0], 405)
        self.assertEqual(self.request("PATCH", "/api/snapshot")[0], 405)

    def test_forged_host_origin_and_mutation_are_rejected(self):
        self.assertEqual(
            self.request("GET", "/api/snapshot", {"Host": "evil.example"})[0], 403
        )
        self.assertEqual(
            self.request("GET", "/api/snapshot", {"Origin": "https://evil.example"})[0],
            403,
        )
        self.assertEqual(self.request("POST", "/api/snapshot")[0], 405)
        self.assertEqual(self.request("DELETE", "/api/snapshot")[0], 405)
        self.assertEqual(self.request("GET", "/%2e%2e/pyproject.toml")[0], 404)
        self.assertEqual(self.request("GET", "/src/jarvis/config.py")[0], 404)


class RuntimeAdapterTests(unittest.TestCase):
    def test_hands_ready_requires_an_enabled_real_executor(self):
        catalog = SimpleNamespace(capabilities=(SimpleNamespace(
            key="browser:playwright", execution_enabled=False,
        ),))
        runtime = SimpleNamespace(
            state="idle", vision_service=None, _work_runtime=None,
            _capability_runtime=SimpleNamespace(catalog=catalog),
        )
        hub = build_runtime_hub(runtime, None)
        self.assertEqual(hub.snapshot()["features"]["hands"], "unavailable")
        catalog.capabilities = (SimpleNamespace(
            key="browser:playwright", execution_enabled=True,
        ),)
        self.assertEqual(hub.snapshot()["features"]["hands"], "ready")

    def test_real_work_estimator_projects_progress_without_blocked_request_text(self):
        from jarvis.work.models import WorkItem, WorkState, WorkType

        item = WorkItem(
            request="my private banking request", work_type=WorkType.RESEARCH,
            source_session_id="session", source_turn_id="turn",
            state=WorkState.WAITING_FOR_OWNER,
            status_detail="enter my secret password",
        )
        store = SimpleNamespace(
            list_recent=lambda **kwargs: (item,),
            list_steps=lambda work_id: (),
            list=lambda **kwargs: (),
        )
        runtime = SimpleNamespace(
            state="idle", vision_service=None,
            _work_runtime=SimpleNamespace(store=store, routing_store=None),
        )
        work = build_runtime_hub(runtime, None).snapshot()["work"][0]
        self.assertEqual(work["state"], "waiting_for_owner")
        self.assertEqual(work["progress"], 15)
        self.assertTrue(work["approximate"])
        self.assertNotIn("private", json.dumps(work))
        self.assertNotIn("password", json.dumps(work))

    def test_stale_vision_frame_does_not_display_cached_target_as_live(self):
        runtime = SimpleNamespace(
            state="idle", _work_runtime=None, config=None,
            vision_service=SimpleNamespace(
                running=True,
                diagnostics=SimpleNamespace(status=SimpleNamespace(
                    captured_at=10.0, target_id=3, target_visible=True,
                    armed=True, visible_people=1,
                )),
            ),
        )
        with patch("time.monotonic", return_value=50.0):
            vision = build_runtime_hub(runtime, None).snapshot()["vision"]
        self.assertEqual(vision["state"], "active")
        self.assertEqual(vision["frame"], "stale")
        self.assertNotIn("target", vision)
        self.assertNotIn("people", vision)

    def test_work_projection_uses_real_routing_decision_when_present(self):
        work = SimpleNamespace(
            work_id="work_2222222222222222",
            work_type=SimpleNamespace(value="development"),
            state=SimpleNamespace(value="running"),
        )
        runtime = SimpleNamespace(
            state="idle", vision_service=None,
            _work_runtime=SimpleNamespace(
                routing_store=SimpleNamespace(
                    list_decisions_for_work=lambda work_id, limit: (
                        SimpleNamespace(decision=SimpleNamespace(
                            selected_target_id="chatgpt_plan:gpt-6-astra",
                        )),
                    ) if work_id == "work_2222222222222222" and limit == 1 else (),
                ),
                store=SimpleNamespace(list_recent=lambda **kwargs: (work,)),
            ),
        )
        item = build_runtime_hub(runtime, None).snapshot()["work"][0]
        self.assertEqual(item["model_target"], "chatgpt_plan:gpt-6-astra")

    def test_camera_following_does_not_claim_verified_owner_lock(self):
        runtime = SimpleNamespace(
            state="idle", _work_runtime=None, config=None,
            vision_service=SimpleNamespace(
                running=True,
                diagnostics=SimpleNamespace(status=SimpleNamespace(
                    captured_at=49.0, target_id=7, target_visible=True,
                    armed=True, visible_people=1,
                )),
            ),
        )
        with patch("time.monotonic", return_value=50.0):
            vision = build_runtime_hub(runtime, None).snapshot()["vision"]
        self.assertEqual(vision["state"], "active")
        self.assertEqual(vision["target"], "following")
        self.assertEqual(vision["people"], 1)

    def test_opt_in_server_gets_controller_event_feed(self):
        feed = HUDActivityFeed()
        feed.observe_turn(SimpleNamespace(role="user", text="private"))
        runtime = SimpleNamespace(
            presentation_voice_state="standby", vision_service=None,
            _work_runtime=None, _hud_activity_feed=feed,
        )
        hubs = []

        def capture(hub, *, port=8765):
            hubs.append(hub)
            return SimpleNamespace(close=lambda: None, port=port)

        with patch.dict("os.environ", {"JARVIS_UI_ENABLED": "true"}):
            with patch("jarvis.ui.runtime.UIService", side_effect=capture):
                self.assertIsNotNone(start_ui_if_enabled(runtime, None))
        self.assertEqual(hubs[0].snapshot()["activity"][0]["label"], "USER TURN")

    def test_existing_voice_lifecycle_controls_ui_visual_state(self):
        self.assertEqual(project_voice_state("idle"), "standby")
        self.assertEqual(project_voice_state("active", "listening"), "listening")
        self.assertEqual(project_voice_state("active", "thinking"), "thinking")
        self.assertEqual(project_voice_state("active", "speaking"), "speaking")
        self.assertEqual(project_voice_state("active", "listening", True), "listening")
        self.assertEqual(project_voice_state("recovering"), "recovering")
        self.assertEqual(project_voice_state("stopped"), "offline")

    def test_production_records_map_to_strict_projection(self):
        runtime = SimpleNamespace(
            state="idle",
            _agent_state="unavailable",
            _user_is_speaking=False,
            vision_service=SimpleNamespace(running=True),
            _work_runtime=SimpleNamespace(
                store=SimpleNamespace(
                    list_recent=lambda **kwargs: [
                        SimpleNamespace(
                            work_type=SimpleNamespace(value="research"),
                            state=SimpleNamespace(value="running"),
                            payload="private",
                        )
                    ]
                )
            ),
        )
        self_awareness = SimpleNamespace(
            system_snapshot=lambda **kwargs: [
                SimpleNamespace(
                    descriptor=SimpleNamespace(component_id="voice.runtime"),
                    health=SimpleNamespace(state=SimpleNamespace(value="starting")),
                )
            ]
        )
        snap = build_runtime_hub(runtime, self_awareness).snapshot()
        self.assertTrue(snap["connected"])
        self.assertEqual(snap["voice"]["state"], "standby")
        self.assertEqual(snap["work"], [{"type": "research", "state": "running"}])
        self.assertEqual(
            snap["health"], [{"component": "voice.runtime", "state": "starting"}]
        )
        self.assertEqual(snap["vision"], {"state": "active"})
        self.assertNotIn("private", json.dumps(snap))

    def test_ui_is_opt_in_and_bind_failure_is_nonfatal(self):
        runtime = SimpleNamespace(
            state="idle",
            _agent_state="unavailable",
            _user_is_speaking=False,
            vision_service=None,
            _work_runtime=None,
        )
        with patch.dict("os.environ", {"JARVIS_UI_ENABLED": "false"}):
            self.assertIsNone(start_ui_if_enabled(runtime, None))
        with patch.dict("os.environ", {"JARVIS_UI_ENABLED": "true"}):
            with patch(
                "jarvis.ui.runtime.create_ui_server", side_effect=OSError("busy")
            ):
                self.assertIsNone(start_ui_if_enabled(runtime, None))
            with patch(
                "jarvis.ui.runtime.create_ui_server",
                side_effect=TypeError("bad driver"),
            ):
                self.assertIsNone(start_ui_if_enabled(runtime, None))


class PackagingTests(unittest.TestCase):
    def test_python_distribution_includes_built_hud_and_license(self):
        project = Path(__file__).resolve().parents[1]
        config = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
        patterns = config["tool"]["setuptools"]["package-data"]["jarvis.ui"]
        self.assertIn("assets/index.html", patterns)
        self.assertIn("assets/assets/*.js", patterns)
        self.assertIn("assets/THIRD_PARTY_NOTICES.txt", patterns)


if __name__ == "__main__":
    unittest.main()
