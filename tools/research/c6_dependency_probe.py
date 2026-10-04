"""Stdlib-only dependency probe for C6 owner-machine acceptance."""

from __future__ import annotations

from importlib import metadata, util
import json


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def probe_dependencies() -> dict[str, object]:
    return {
        "jsonschema_version": _distribution_version("jsonschema"),
        "llmlingua_available": util.find_spec("llmlingua") is not None,
    }


def main() -> None:
    print(json.dumps(probe_dependencies(), sort_keys=True))


if __name__ == "__main__":
    main()
