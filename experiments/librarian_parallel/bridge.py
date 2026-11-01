"""Isolated, opt-in MCP client for evaluating an external Librarian service.

This is a protocol adapter, NOT the unpublished Librarian server.
No production Jarvis imports, database access, or model calls.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

PROTOCOL_VERSION = "2025-06-18"
MAX_MCP_LINE_CHARS = 1_048_576
MAX_ARGUMENT_CHARS = 4096
SYNTHETIC_SCOPE = re.compile(r"^synthetic-[a-zA-Z0-9_-]{1,64}$")
WRITE_OPERATIONS = frozenset({"remember", "correct", "forget", "archive", "delete"})


class LibrarianError(RuntimeError):
    """Transport, contract, or safety failure (fail closed)."""


class McpStdioClient:
    """Minimal MCP stdio JSON-RPC client; no network/HTTP assumptions.

    One sequential call at a time. stdout must be valid line-delimited JSON-RPC.
    Child stderr is discarded rather than logging potentially private data.
    """

    def __init__(
        self, command: list[str], cwd: str | None = None, timeout: float = 10.0
    ) -> None:
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) and x for x in command)
        ):
            raise LibrarianError("A nonempty executable/argument list is required")
        if not 0 < timeout <= 120:
            raise LibrarianError("Timeout must be between 0 and 120 seconds")
        self.command = command
        self.cwd = cwd
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[object] = queue.Queue()
        self.sequence = 0
        self._tools: dict[str, dict[str, Any]] | None = None

    def __enter__(self) -> Self:
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
            shell=False,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        try:
            reply = self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "jarvis-librarian-parallel",
                        "version": "0.1.0",
                    },
                },
            )
            if not isinstance(reply, dict) or reply.get("protocolVersion") != PROTOCOL_VERSION:
                raise LibrarianError("Incompatible MCP protocol version")
            self._notify("notifications/initialized")
            return self
        except Exception:
            self.close()
            raise

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                line = self.process.stdout.readline(MAX_MCP_LINE_CHARS + 1)
                if not line:
                    break
                if len(line) > MAX_MCP_LINE_CHARS or not line.endswith("\n"):
                    self.messages.put(LibrarianError("MCP response line exceeds limit"))
                    break
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                        raise ValueError("Not a JSON-RPC object")
                    self.messages.put(value)
                except (ValueError, json.JSONDecodeError):
                    self.messages.put(LibrarianError("Server emitted invalid MCP JSON"))
                    break
        except (UnicodeError, OSError):
            self.messages.put(LibrarianError("Server stdout failed"))
        finally:
            self.messages.put(LibrarianError("MCP server closed stdout"))

    def _send(self, message: Mapping[str, Any]) -> None:
        if (
            self.process is None
            or self.process.poll() is not None
            or self.process.stdin is None
        ):
            raise LibrarianError("MCP server is not running")
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, UnicodeError) as exc:
            raise LibrarianError("Could not send MCP message") from exc

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        self.sequence += 1
        request_id = self.sequence
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LibrarianError("MCP request timeout")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise LibrarianError("MCP request timeout") from exc
            if isinstance(message, BaseException):
                raise message
            if not isinstance(message, dict):
                raise LibrarianError("Invalid MCP response")
            if "id" not in message:
                continue  # notifications, not replies
            if message["id"] != request_id:
                raise LibrarianError("Unexpected MCP response ID")
            if "error" in message:
                # Don't echo arbitrary server errors; they may contain owner data.
                raise LibrarianError("MCP server rejected " + method)
            if "result" not in message:
                raise LibrarianError("Missing MCP result")
            return message["result"]

    def list_tools(self) -> dict[str, dict[str, Any]]:
        if self._tools is not None:
            return self._tools
        discovered: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        for _ in range(25):
            params = {"cursor": cursor} if cursor else {}
            result = self._request("tools/list", params)
            if not isinstance(result, dict) or not isinstance(
                result.get("tools"), list
            ):
                raise LibrarianError("Invalid MCP tools/list response")
            for tool in result["tools"]:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                    raise LibrarianError("Invalid advertised tool")
                if tool["name"] in discovered:
                    raise LibrarianError("Duplicate advertised tool")
                discovered[tool["name"]] = tool
            cursor = result.get("nextCursor")
            if cursor is None:
                self._tools = discovered
                return discovered
            if not isinstance(cursor, str) or not cursor:
                raise LibrarianError("Invalid MCP cursor")
        raise LibrarianError("MCP pagination limit exceeded")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.list_tools():
            raise LibrarianError("Tool not advertised by MCP server")
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise LibrarianError("Invalid MCP tool result")
        if result.get("isError"):
            raise LibrarianError("MCP tool reported failure")
        return result

    def close(self) -> None:
        proc, self.process = self.process, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        for stream in (proc.stdin, proc.stdout):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class ExperimentConfig:
    command: list[str]
    cwd: str | None
    timeout: float
    operations: dict[str, dict[str, Any]]

    @staticmethod
    def from_file(path: str | Path) -> ExperimentConfig:
        source = Path(path).resolve()
        config = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("mode") != "synthetic-only":
            raise LibrarianError("Only synthetic-only experiments are supported")
        command = config.get("command")
        if not isinstance(command, list) or not command:
            raise LibrarianError("Configure an MCP server command list")
        cwd = config.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise LibrarianError("Invalid cwd")
        ops = config.get("operations", {})
        if not isinstance(ops, dict):
            raise LibrarianError("operations must be a map")
        for key, binding in ops.items():
            if not isinstance(binding, dict) or not isinstance(
                binding.get("tool"), str
            ):
                raise LibrarianError("Each operation requires an explicit tool name")
            if not isinstance(binding.get("arguments"), dict):
                raise LibrarianError("Each operation requires an arguments mapping")
            if "{project}" not in json.dumps(binding["arguments"]):
                raise LibrarianError("Each operation must bind project scope")
            if key in WRITE_OPERATIONS and "{source}" not in json.dumps(
                binding["arguments"]
            ):
                raise LibrarianError("Writes must carry explicit synthetic source ID")
        return ExperimentConfig(command, cwd, float(config.get("timeout", 10)), ops)


def _render(value: Any, values: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}"):
            key = value[1:-1]
            if key not in values:
                raise LibrarianError("Unprovided argument placeholder: " + key)
            return values[key]
        if "{" in value or "}" in value:
            raise LibrarianError("Only exact argument placeholders are permitted")
        return value
    if isinstance(value, list):
        return [_render(item, values) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, values) for key, item in value.items()}
    return value


class LibrarianExperiment:
    """Runs a separately configured memory backend without accessing Jarvis state."""

    def __init__(self, config: ExperimentConfig, client: McpStdioClient) -> None:
        self.config = config
        self.client = client

    def invoke(
        self,
        operation: str,
        *,
        project: str,
        query: str = "",
        text: str = "",
        source: str = "",
        target: str = "",
        allow_synthetic_write: bool = False,
    ) -> tuple[dict[str, Any], float]:
        if not SYNTHETIC_SCOPE.fullmatch(project):
            raise LibrarianError("Only synthetic-* project IDs are accepted")
        if operation in WRITE_OPERATIONS and not allow_synthetic_write:
            raise LibrarianError("Write operation requires explicit opt-in")
        binding = self.config.operations.get(operation)
        if binding is None:
            raise LibrarianError("Operation is not mapped to a verified server tool")
        values = {
            "project": project,
            "query": query,
            "text": text,
            "source": source,
            "target": target,
        }
        if any(len(value) > MAX_ARGUMENT_CHARS for value in values.values()):
            raise LibrarianError("Synthetic MCP argument exceeds length limit")
        if operation in WRITE_OPERATIONS and not source.startswith("fixture-"):
            raise LibrarianError("Synthetic writes require a fixture-* source ID")
        arguments = _render(binding["arguments"], values)
        advertised = self.client.list_tools().get(binding["tool"])
        if not isinstance(advertised, dict):
            raise LibrarianError("Mapped operation is not an advertised MCP tool")
        schema = advertised.get("inputSchema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise LibrarianError("MCP tool requires a valid object input schema")
        props = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(props, dict) or not isinstance(required, list):
            raise LibrarianError("Invalid advertised MCP tool input schema")
        if not all(isinstance(name, str) for name in required):
            raise LibrarianError("Invalid MCP required fields")
        if not set(required).issubset(arguments):
            raise LibrarianError("MCP tool arguments missing required input fields")
        if not set(arguments).issubset(props):
            raise LibrarianError("MCP tool mapping contains unadvertised input fields")
        for name, value in arguments.items():
            spec = props[name]
            if not isinstance(spec, dict):
                raise LibrarianError("Invalid advertised MCP input property")
            expected = spec.get("type")
            if expected == "string" and not isinstance(value, str):
                raise LibrarianError("MCP tool mapping input type mismatch")
            if expected == "integer" and type(value) is not int:
                raise LibrarianError("MCP tool mapping input type mismatch")
            if expected == "boolean" and type(value) is not bool:
                raise LibrarianError("MCP tool mapping input type mismatch")
        start = time.perf_counter()
        result = self.client.call_tool(binding["tool"], arguments)
        return result, round((time.perf_counter() - start) * 1000, 3)
