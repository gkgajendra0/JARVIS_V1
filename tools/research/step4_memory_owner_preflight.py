"""Read-only owner-machine readiness check for isolated memory model trials.

No provider calls, local device control, database access, network scans,
secret values or model downloads. Reports only coarse resource and package
availability; requires NO API credentials to execute.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Any


def installed_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def read_gpu_capacity() -> dict[str, Any]:
    if not shutil.which("nvidia-smi"):
        return {"available": False, "reason": "nvidia_smi_not_on_path"}
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        entries = []
        for line in completed.stdout.strip().splitlines():
            parts = line.split(",")
            if len(parts) != 2:
                continue
            entries.append(
                {
                    "total_mib": int(parts[0].strip()),
                    "free_mib": int(parts[1].strip()),
                }
            )
        if not entries:
            return {"available": False, "reason": "gpu_query_empty"}
        return {"available": True, "devices": entries}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"available": False, "reason": "gpu_query_failed"}


def report_readiness(*, check_gpu: bool = False) -> dict[str, Any]:
    packages = (
        "langmem",
        "hindsight-client",
        "langchain-google-genai",
        "langchain-openai",
        "google-genai",
        "openai",
        "pydantic",
        "psutil",
    )
    ram_available_mib: int | None = None
    if installed_version("psutil"):
        import psutil

        ram_available_mib = psutil.virtual_memory().available // 1048576
    return {
        "mode": "READ_ONLY_NO_NETWORK_NO_MODEL",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "operating_system": platform.system(),
        "available_ram_mib": ram_available_mib,
        "gpu": read_gpu_capacity() if check_gpu else {"checked": False},
        "packages": {package: installed_version(package) for package in packages},
        "credential_presence_not_values": {
            "google_api_key": bool(os.environ.get("GOOGLE_API_KEY")),
            "openai_api_key": bool(os.environ.get("OPENAI_API_KEY")),
        },
        "model_calls": 0,
        "memory_writes": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-gpu",
        action="store_true",
        help="Query nvidia-smi locally; no GPU model is loaded.",
    )
    args = parser.parse_args()
    print(json.dumps(report_readiness(check_gpu=args.check_gpu), indent=2))


if __name__ == "__main__":
    main()
