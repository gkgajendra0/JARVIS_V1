"""Owner browser chat: same guarded runtime, no separate goal or approval store."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from jarvis.owner_text_web import OwnerWebGateway, build_http_server

pytestmark = pytest.mark.asyncio

GOAL = "goal_3bf2a80a14ecb70dd5b6"
GATE = "gate_0123456789abcdef"


class FakeGoalTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_owner_objectives(self, context):
        self.calls.append("list")
        return {
            "ok": True,
            "objectives": [
                {
                    "goal_id": GOAL,
                    "owner_request": "Acquire TV control",
                    "goal_state": "waiting_information",
                    "phase": "research",
                }
            ],
        }

    async def get_owner_objective_status(self, context, goal_id):
        self.calls.append("status:" + goal_id)
        return {
            "ok": True,
            "goal_id": goal_id,
            "goal_state": "waiting_information",
            "phase": "research",
            "verified_completion": False,
        }


class FakeWorkTools:
    async def list_background_work(self, context):
        return {"ok": True, "work": [{"work_id": "work_a", "state": "waiting"}]}


class FakeGateRegistry:
    def pending_gate_ids(self):
        return [GATE]


class FakeConsole:
    def __init__(self) -> None:
        self._tools = FakeGoalTools()
        self._work_tools = FakeWorkTools()
        self._gates = FakeGateRegistry()
        self.submitted: list[str] = []
        self.reviewed = False

    async def submit(self, text):
        self.submitted.append(text)
        if text == "gates":
            self.reviewed = True
            return {
                "ok": True,
                "status": "gates_listed",
                "gates": [
                    {
                        "gate_id": GATE,
                        "kind": "architecture",
                        "artifact_digest": "digest",
                        "proposal": {"action": "test-only"},
                    }
                ],
            }
        if text == f"approve {GATE}" and self.reviewed:
            return {"ok": False, "status": "windows_hello_required"}
        return {"ok": False, "status": "gate_not_reviewed"}


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.block: asyncio.Event | None = None

    async def submit(self, text):
        self.calls.append(text)
        if self.block is not None:
            await self.block.wait()
        return {"ok": True, "status": "chat_message", "message": "State checked."}


def _gateway(loop):
    console = FakeConsole()
    chat = FakeChat()
    gateway = OwnerWebGateway(loop=loop, console=console, chat=chat)
    return gateway, console, chat


async def test_state_reads_exact_existing_goal_without_new_turn():
    gateway, console, chat = _gateway(asyncio.get_running_loop())
    state = await gateway.status()
    assert state["ok"] is True
    assert state["goal_id"] == GOAL
    assert state["goal"]["goal_state"] == "waiting_information"
    assert state["verified_goal_completion"] is False
    assert state["pending_gate_count"] == 1
    assert len(state["work"]) == 1
    assert console._tools.calls == ["list", "status:" + GOAL]
    assert console.submitted == []
    assert chat.calls == []


async def test_chat_idempotency_and_in_flight_polling():
    gateway, _, chat = _gateway(asyncio.get_running_loop())
    chat.block = asyncio.Event()
    request_id = "request_12345678"
    assert (await gateway.submit(request_id, "Check the existing TV goal"))[
        "reused"
    ] is False
    assert (await gateway.submit(request_id, "Check the existing TV goal"))[
        "reused"
    ] is True
    assert (await gateway.request_result(request_id))["state"] == "processing"
    await asyncio.sleep(0)
    assert chat.calls == ["Check the existing TV goal"]
    chat.block.set()
    await gateway._requests[request_id]
    result = await gateway.request_result(request_id)
    assert result["state"] == "finished"
    assert result["result"]["message"] == "State checked."
    assert chat.calls == ["Check the existing TV goal"]


async def test_invalid_requests_do_not_mutate_runtime():
    gateway, console, chat = _gateway(asyncio.get_running_loop())
    assert (await gateway.submit("x", "Hi"))["ok"] is False
    assert (await gateway.submit("request_12345678", ""))["ok"] is False
    assert (await gateway.submit("request_12345678", "a" * 2049))["ok"] is False
    assert (await gateway.decide_gate("bad", "approve"))["ok"] is False
    assert (await gateway.decide_gate(GATE, "something_else"))["ok"] is False
    assert console.submitted == []
    assert chat.calls == []


async def test_gate_decision_requires_review_and_keeps_existing_windows_gate():
    gateway, console, _ = _gateway(asyncio.get_running_loop())
    denied = await gateway.decide_gate(GATE, "approve")
    assert denied["status"] == "gate_not_reviewed"
    listing = await gateway.review_gates()
    assert listing["gates"][0]["gate_id"] == GATE
    request_id = "decision_12345678"
    assert (await gateway.submit_gate_decision(request_id, GATE, "approve"))[
        "reused"
    ] is False
    assert (await gateway.submit_gate_decision(request_id, GATE, "approve"))[
        "reused"
    ] is True
    await gateway._requests[request_id]
    outcome = await gateway.request_result(request_id)
    assert outcome["result"]["status"] == "windows_hello_required"
    assert console.submitted == ["gates", "approve " + GATE]


def _http_request(port, path, *, method="GET", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        data=data,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


async def test_loopback_http_requires_csrf_and_same_origin():
    gateway, _, chat = _gateway(asyncio.get_running_loop())
    server = build_http_server(gateway, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        port = server.server_port
        status, html = await asyncio.to_thread(_http_request, port, "/")
        assert status == 200
        assert "Owner Workspace" in html
        assert "owner_text_web.html" not in html
        assert "innerHTML" not in html
        match = re.search(r'name="jarvis-csrf" content="([^"]+)"', html)
        assert match is not None
        token = match.group(1)
        status, _ = await asyncio.to_thread(_http_request, port, "/api/state")
        assert status == 403
        secure = {"X-Jarvis-CSRF": token}
        status, data = await asyncio.to_thread(
            _http_request, port, "/api/state", headers=secure
        )
        assert status == 200
        assert json.loads(data)["goal_id"] == GOAL
        payload = {"request_id": "request_12345678", "text": "Status of my TV"}
        status, _ = await asyncio.to_thread(
            _http_request,
            port,
            "/api/chat",
            method="POST",
            payload=payload,
            headers={
                **secure,
                "Content-Type": "application/json",
                "Origin": "http://malicious.example",
            },
        )
        assert status == 403
        assert chat.calls == []
        status, data = await asyncio.to_thread(
            _http_request,
            port,
            "/api/chat",
            method="POST",
            payload=payload,
            headers={
                **secure,
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
            },
        )
        assert status == 200
        await gateway._requests[payload["request_id"]]
        status, data = await asyncio.to_thread(
            _http_request,
            port,
            "/api/requests/" + payload["request_id"],
            headers=secure,
        )
        assert status == 200
        assert json.loads(data)["state"] == "finished"
        assert chat.calls == ["Status of my TV"]
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=5)



async def test_browser_chat_and_guarded_review_real_dom():
    """Exercise the actual browser JS; mocks stop at the canonical tool boundary."""
    playwright_api = pytest.importorskip("playwright.async_api")
    gateway, console, chat = _gateway(asyncio.get_running_loop())
    server = build_http_server(gateway, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with playwright_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(f"http://127.0.0.1:{server.server_port}/")
                await page.locator("#statePill").get_by_text(
                    "waiting information"
                ).wait_for(timeout=12000)
                assert chat.calls == []
                assert console.submitted == []

                await page.locator("#messageInput").fill("Status of my TV")
                await page.locator("#sendButton").click()
                await page.locator(".message.assistant .bubble").get_by_text(
                    "State checked."
                ).wait_for(timeout=12000)
                assert chat.calls == ["Status of my TV"]

                await page.locator("#reviewGates").click()
                await page.locator(".gate").wait_for(timeout=12000)
                assert console.submitted == ["gates"]
                # Confirm is required; dismissing it must not submit approval.
                page.once(
                    "dialog", lambda dialog: asyncio.create_task(dialog.dismiss())
                )
                await page.locator(".gate .approve").click()
                # No API changes were made by merely reading the proposal.
                assert console.submitted == ["gates"]
            finally:
                await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=5)
