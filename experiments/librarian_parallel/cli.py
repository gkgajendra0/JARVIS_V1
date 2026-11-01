"""Read-only-by-default command line probe for an external MCP memory server."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bridge import ExperimentConfig, LibrarianError, LibrarianExperiment, McpStdioClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated Librarian MCP experiment")
    parser.add_argument("--config", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("discover", help="Initialize server and list advertised tools only")
    invoke = sub.add_parser("invoke", help="Call an explicitly mapped MCP tool")
    invoke.add_argument("--operation", required=True)
    invoke.add_argument("--project", required=True)
    invoke.add_argument("--query", default="")
    invoke.add_argument("--text", default="")
    invoke.add_argument("--source", default="")
    invoke.add_argument("--target", default="")
    invoke.add_argument("--allow-synthetic-write", action="store_true")
    invoke.add_argument("--show-result", action="store_true",
                        help="Print raw synthetic tool result (otherwise metadata only)")
    args = parser.parse_args(argv)
    try:
        config = ExperimentConfig.from_file(args.config)
        with McpStdioClient(config.command, config.cwd, config.timeout) as client:
            advertised = client.list_tools()
            if args.action == "discover":
                # Only names are displayed: schemas/descriptions may contain secrets.
                print(json.dumps({"status": "connected", "advertised_tools":
                                  sorted(advertised)}, indent=2))
                return 0
            adapter = LibrarianExperiment(config, client)
            result, elapsed_ms = adapter.invoke(
                args.operation, project=args.project, query=args.query,
                text=args.text, source=args.source, target=args.target,
                allow_synthetic_write=args.allow_synthetic_write,
            )
            output = {"status": "ok", "operation": args.operation,
                      "elapsed_ms": elapsed_ms,
                      "result_blocks": len(result.get("content", [])),
                      "structured_content": "structuredContent" in result}
            if args.show_result:
                output["synthetic_result"] = result
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
    except (LibrarianError, OSError, ValueError, json.JSONDecodeError) as exc:
        # Avoid including arbitrary server exceptions or tool payloads in logs.
        print(json.dumps({"status": "failed",
                          "error_type": type(exc).__name__,
                          "message": str(exc) if isinstance(exc, LibrarianError)
                          else "Configuration or process error"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
