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
from jarvis.ui.runtime import (
    build_runtime_hub,
    project_voice_state,
    start_ui_if_enabled,
)
from jarvis.ui.server import create_ui_server


class HubTests(unittest.TestCase):
    def test_disconnected_snapshot_does_not_fake_live_telemetry(self):
        snapshot = UISnapshotHub().snapshot()
        self.assertEqual(snapshot["schema"], 1)
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
        self.assertFalse(json.loads(body)["connected"])
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
