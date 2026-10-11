"""Local browser text channel over the *existing* governed JARVIS runtime.

No microphone, no parallel GICC/Work database, no new approval mechanism.
Only 127.0.0.1 is served; writes require same-origin + unpredictable CSRF.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import sys
import threading
import webbrowser
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any

LOGGER = logging.getLogger(__name__)
TV_GOAL_ID = "goal_3bf2a80a14ecb70dd5b6"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_GATE_ID = re.compile(r"^gate_[0-9a-f]{16}$")
_MAX_BODY = 8192


class OwnerWebGateway:
    """Schedule browser requests on the canonical runtime's asyncio loop."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        console: Any,
        chat: Any,
        goal_id: str = TV_GOAL_ID,
    ) -> None:
        self.loop = loop
        self.console = console
        self.chat = chat
        self.goal_id = goal_id
        self._turn_lock = asyncio.Lock()
        self._requests: dict[str, asyncio.Task[dict[str, object]]] = {}

    async def status(self) -> dict[str, object]:
        """Read state without creating an owner turn or a new goal."""
        listing = await self.console._tools.list_owner_objectives(None)
        if listing.get("ok") is not True:
            return {"ok": False, "status": "goal_listing_unavailable"}
        goals = listing.get("objectives")
        if not isinstance(goals, list):
            return {"ok": False, "status": "goal_listing_invalid"}
        detail = await self.console._tools.get_owner_objective_status(
            None, self.goal_id
        )
        work = (
            {"ok": True, "work": []}
            if self.console._work_tools is None
            else await self.console._work_tools.list_background_work(None)
        )
        gates = (
            []
            if self.console._gates is None
            else self.console._gates.pending_gate_ids()
        )
        return {
            "ok": True,
            "goal_id": self.goal_id,
            "goal": detail,
            "active_goals": [
                g for g in goals if isinstance(g, dict)
            ],
            "work": work.get("work", []) if work.get("ok") else [],
            "work_available": bool(work.get("ok")),
            "pending_gate_count": len(gates),
            "real_machine_accepted": bool(
                detail.get("verified_completion") is True
            ),
        }

    async def _run_turn(self, text: str) -> dict[str, object]:
        async with self._turn_lock:
            return await self.chat.submit(text)

    async def submit(self, request_id: str, text: str) -> dict[str, object]:
        if not _REQUEST_ID.fullmatch(request_id):
            return {"ok": False, "status": "invalid_request_id"}
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 2048:
            return {"ok": False, "status": "invalid_message_length"}
        if request_id in self._requests:
            return {"ok": True, "request_id": request_id, "reused": True}
        if sum(not task.done() for task in self._requests.values()) >= 4:
            return {"ok": False, "status": "queue_full"}
        # Bound history and never evict an in-flight request.
        for key, task in list(self._requests.items()):
            if len(self._requests) < 64:
                break
            if task.done():
                del self._requests[key]
        task = asyncio.create_task(self._run_turn(text), name="owner-web-text-turn")
        self._requests[request_id] = task
        return {"ok": True, "request_id": request_id, "reused": False}

    async def request_result(self, request_id: str) -> dict[str, object]:
        task = self._requests.get(request_id)
        if task is None:
            return {"ok": False, "status": "unknown_request"}
        if not task.done():
            return {"ok": True, "state": "processing"}
        try:
            outcome = task.result()
        except Exception:
            LOGGER.exception("JARVIS owner web turn failed")
            return {
                "ok": False,
                "state": "finished",
                "status": "runtime_error",
                "message": "JARVIS could not process this turn. No success is claimed.",
            }
        return {"ok": True, "state": "finished", "result": outcome}

    async def review_gates(self) -> dict[str, object]:
        async with self._turn_lock:
            # This is a deliberate owner review operation. Listing grants
            # visibility only; actual decisions stay bound to existing gates.
            return await self.console.submit("gates")

    async def decide_gate(
        self, gate_id: str, decision: str
    ) -> dict[str, object]:
        if not _GATE_ID.fullmatch(gate_id):
            return {"ok": False, "status": "invalid_gate_id"}
        if decision not in {"approve", "reject"}:
            return {"ok": False, "status": "invalid_gate_decision"}
        async with self._turn_lock:
            # Exact reviewed gate, authoritative original OWNER action,
            # Windows Hello and promotion policy are verified by WorkAgentTools.
            return await self.console.submit(f"{decision} {gate_id}")


def build_http_server(
    gateway: OwnerWebGateway, *, port: int = 8765
) -> ThreadingHTTPServer:
    """Server accepts *only* local IPv4 loopback traffic."""
    token = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    origin = f"http://127.0.0.1:{port}"
    html = (
        resources.files("jarvis")
        .joinpath("owner_text_web.html")
        .read_text(encoding="utf-8")
        .replace("__JARVIS_CSRF__", token)
        .replace("__JARVIS_NONCE__", nonce)
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "JarvisLocalChat"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            LOGGER.info("Web UI: " + format, *args)

        def _headers(self, status: int, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; "
                f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "connect-src 'self'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'",
            )

        def _json(self, status: int, result: object) -> None:
            body = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _valid_host(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{port}"

        def _api_authorized(self, *, write: bool = False) -> bool:
            if self.headers.get("X-Jarvis-CSRF") != token:
                return False
            if write and self.headers.get("Origin") != origin:
                return False
            return True

        def _invoke(self, coroutine: Any) -> dict[str, object]:
            future = asyncio.run_coroutine_threadsafe(coroutine, gateway.loop)
            try:
                return future.result(timeout=12.0)
            except FutureTimeout:
                # Do NOT cancel an in-flight owner operation or claim success.
                return {"ok": False, "status": "runtime_busy"}
            except Exception:
                LOGGER.exception("Owner text web request failed")
                return {"ok": False, "status": "runtime_unavailable"}

        def do_GET(self) -> None:
            if not self._valid_host():
                self._json(403, {"ok": False, "status": "invalid_host"})
                return
            if self.path == "/":
                body = html.encode("utf-8")
                self._headers(200, "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._api_authorized():
                self._json(403, {"ok": False, "status": "not_authorized"})
                return
            if self.path == "/api/state":
                self._json(200, self._invoke(gateway.status()))
            elif self.path.startswith("/api/requests/"):
                request_id = self.path.removeprefix("/api/requests/")
                if not _REQUEST_ID.fullmatch(request_id):
                    self._json(400, {"ok": False, "status": "invalid_request_id"})
                else:
                    self._json(200, self._invoke(gateway.request_result(request_id)))
            else:
                self._json(404, {"ok": False, "status": "not_found"})

        def do_POST(self) -> None:
            if not self._valid_host() or not self._api_authorized(write=True):
                self._json(403, {"ok": False, "status": "not_authorized"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != (
                "application/json"
            ):
                self._json(415, {"ok": False, "status": "json_required"})
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or int(length) > _MAX_BODY:
                self._json(413, {"ok": False, "status": "body_too_large"})
                return
            try:
                payload = json.loads(self.rfile.read(int(length)))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"ok": False, "status": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._json(400, {"ok": False, "status": "invalid_payload"})
                return
            if self.path == "/api/chat":
                request_id, message = payload.get("request_id"), payload.get("text")
                if not isinstance(request_id, str) or not isinstance(message, str):
                    self._json(400, {"ok": False, "status": "invalid_payload"})
                    return
                result = self._invoke(gateway.submit(request_id, message))
            elif self.path == "/api/gates/review":
                result = self._invoke(gateway.review_gates())
            elif self.path == "/api/gates/decide":
                gate_id, decision = payload.get("gate_id"), payload.get("decision")
                if not isinstance(gate_id, str) or not isinstance(decision, str):
                    self._json(400, {"ok": False, "status": "invalid_payload"})
                    return
                result = self._invoke(gateway.decide_gate(gate_id, decision))
            else:
                self._json(404, {"ok": False, "status": "not_found"})
                return
            self._json(200 if result.get("ok") else 409, result)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


async def _run(port: int = 8765) -> None:
    from jarvis.config import JarvisConfig
    from jarvis.engineering_change.gates import GateService
    from jarvis.owner_text_chat import OwnerNaturalTextChat, build_text_chat_client
    from jarvis.owner_text_console import OwnerTextConversation
    from jarvis.conversation import ConversationSession
    from jarvis.voice.gicc_tools import GiccAgentTools
    from jarvis.voice.production_runtime import build_production_voice_runtime
    from jarvis.voice.work_tools import WorkAgentTools

    config = JarvisConfig.from_environment()
    if (
        config.runtime_lane.value != "development"
        or config.gicc_mode.value != "apply"
        or not config.work_orchestration_enabled
    ):
        raise RuntimeError(
            "Local web chat requires development lane, GICC APPLY and Work enabled."
        )
    controller = build_production_voice_runtime(config)
    gicc, work = controller._gicc_runtime, controller._work_runtime
    if gicc is None or work is None:
        raise RuntimeError("Canonical GICC/Work runtime unavailable")

    conversation = ConversationSession()
    conversation.start()
    tools = GiccAgentTools(
        gicc.coordinator,
        conversation,
        gicc.store,
        execution_runtime=gicc,
        objective_status=gicc.objective_status,
        telemetry=gicc.telemetry,
    )
    console = OwnerTextConversation(
        tools,
        conversation,
        work_tools=WorkAgentTools(
            work, conversation, objective_status=gicc.objective_status
        ),
        gates=GateService(work.changes.store, verify_owner=lambda *_: False),
    )
    chat = OwnerNaturalTextChat(
        console=console,
        conversation=conversation,
        client=build_text_chat_client(config),
    )
    gateway = OwnerWebGateway(
        loop=asyncio.get_running_loop(), console=console, chat=chat
    )
    server = build_http_server(gateway, port=port)
    thread = threading.Thread(
        target=server.serve_forever, name="jarvis-owner-web", daemon=True
    )
    gicc.start()
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    print(f"JARVIS TEXT WEB UI: {url} | microphone OFF | existing goal only")
    webbrowser.open(url)
    try:
        await asyncio.Event().wait()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        await gicc.close()
        await work.aclose()
        capability = controller._capability_runtime
        if capability is not None:
            capability.close()
        research = controller._research_service
        if research is not None:
            await research.close()
        memory = controller._memory_runtime
        if memory is not None:
            await memory.close()


def main() -> int:
    try:
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"JARVIS text web UI failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
