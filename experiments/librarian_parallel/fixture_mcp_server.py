"""Synthetic MCP fixture server; NOT the creator's Librarian implementation.

Only for exercising wire protocol, scoping, corrections, and failure isolation.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    records: dict[str, dict[str, dict[str, str]]] = {}
    tools = [
        {
            "name": "fixture_recall",
            "description": "Synthetic scope-only recall",
            "annotations": {"readOnlyHint": True},
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["project", "query"],
            },
        },
        {
            "name": "fixture_remember",
            "description": "Synthetic fact insertion",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "text": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["project", "text", "source"],
            },
        },
        {
            "name": "fixture_correct",
            "description": "Synthetic source correction",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "text": {"type": "string"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["project", "text", "source", "target"],
            },
        },
        {
            "name": "fixture_forget",
            "description": "Synthetic scoped deletion",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["project", "source", "target"],
            },
        },
    ]
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        parameters = request.get("params", {})
        if method == "initialize":
            answer = {
                "protocolVersion": "2024-11-05"
                if "--wrong-protocol" in sys.argv
                else "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic-memory-fixture", "version": "1"},
            }
        elif method == "tools/list":
            if "--oversized-response" in sys.argv:
                answer = {"tools": tools, "padding": "X" * 1_100_000}
            else:
                answer = {"tools": tools}
        elif method == "tools/call":
            name = parameters.get("name", "")
            args = parameters.get("arguments", {})
            project = args.get("project", "")
            if not project.startswith("synthetic-"):
                answer = {
                    "isError": True,
                    "content": [{"type": "text", "text": "scope rejected"}],
                }
            else:
                store = records.setdefault(project, {})
                if name == "fixture_remember":
                    store[args["source"]] = {
                        "source": args["source"],
                        "text": args["text"],
                        "project": project,
                    }
                    data = {"committed": True}
                elif name == "fixture_recall":
                    data = {"records": list(store.values()), "query": args["query"]}
                    if "--foreign-record" in sys.argv:
                        data["records"].append(
                            {
                                "source": "fixture-foreign",
                                "text": "foreign",
                                "project": "synthetic-other",
                            }
                        )
                elif name == "fixture_correct":
                    old = store.pop(args["target"], None)
                    store[args["source"]] = {
                        "source": args["source"],
                        "text": args["text"],
                    }
                    data = {"corrected": old is not None}
                elif name == "fixture_forget":
                    data = {"forgotten": store.pop(args["target"], None) is not None}
                else:
                    data = {"error": "unknown tool"}
                answer = {
                    "content": [{"type": "text", "text": json.dumps(data)}],
                    "isError": name not in {tool["name"] for tool in tools},
                }
        else:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "error": {"code": -32601, "message": "method not found"},
                    }
                ),
                flush=True,
            )
            continue
        print(
            json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": answer}),
            flush=True,
        )


if __name__ == "__main__":
    main()
