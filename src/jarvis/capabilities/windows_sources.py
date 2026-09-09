"""Read-only discovery adapters for mature Windows capability surfaces."""

from __future__ import annotations

import json
import pathlib
import platform
import shutil
import subprocess
import time

import jarvis.capabilities.discovery as discovery
import jarvis.capabilities.models as models


class WinAppCliSchemaSource:
    """Discover only the agent-relevant `winapp ui` command family."""

    source_id = "windows.winapp"

    def __init__(self, executable: str | None = None, *, runner=subprocess.run) -> None:
        self._executable = executable
        self._runner = runner

    def discover(self) -> models.DiscoverySnapshot:
        started = time.monotonic()
        if platform.system() != "Windows":
            return models.DiscoverySnapshot(
                source_id=self.source_id,
                state=models.DiscoveryState.UNAVAILABLE,
                reason="Microsoft winapp discovery currently requires Windows",
            )
        executable = self._executable or shutil.which("winapp")
        if not executable:
            return models.DiscoverySnapshot(
                source_id=self.source_id,
                state=models.DiscoveryState.UNAVAILABLE,
                reason="Microsoft winapp CLI is not installed",
            )
        try:
            completed = self._runner(
                [str(executable), "--cli-schema"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise discovery.CapabilityDiscoveryError(
                f"winapp schema discovery failed: {type(exc).__name__}"
            ) from exc
        if completed.returncode != 0:
            raise discovery.CapabilityDiscoveryError("winapp schema command failed")
        try:
            payload = json.loads(completed.stdout)
            ui = payload["subcommands"]["ui"]
            commands = ui["subcommands"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise discovery.CapabilityDiscoveryError(
                "winapp schema is missing ui subcommands"
            ) from exc
        if not isinstance(commands, dict):
            raise discovery.CapabilityDiscoveryError("winapp ui schema is malformed")
        operations = sorted(
            name
            for name, value in commands.items()
            if isinstance(name, str)
            and isinstance(value, dict)
            and not bool(value.get("hidden", False))
        )
        capability = models.CapabilityDescriptor.create(
            capability_id="desktop.ui",
            source_id=self.source_id,
            kind=models.CapabilityKind.STRUCTURED_AUTOMATION,
            name="Microsoft winapp UI Automation",
            description=(
                "Dynamically discovered Windows UI Automation surface. Step 7 inventories "
                "this surface but intentionally does not enable desktop mutation."
            ),
            operations=operations,
            metadata={
                "executable": str(executable),
                "version": payload.get("version"),
                "schema_version": payload.get("schemaVersion"),
            },
            execution_enabled=False,
        )
        return models.DiscoverySnapshot(
            source_id=self.source_id,
            state=models.DiscoveryState.AVAILABLE,
            capabilities=(capability,),
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )


class WindowsOdrSource:
    """Inventory Windows On-Device Agent Registry entries without starting servers."""

    source_id = "windows.odr"

    def __init__(self, executable: str | None = None, *, runner=subprocess.run) -> None:
        self._executable = executable
        self._runner = runner

    @staticmethod
    def _candidate() -> str | None:
        discovered = shutil.which("odr") or shutil.which("odr.exe")
        if discovered:
            return discovered
        system_root = pathlib.Path("C:/Windows/System32/odr.exe")
        return str(system_root) if system_root.is_file() else None

    def discover(self) -> models.DiscoverySnapshot:
        started = time.monotonic()
        if platform.system() != "Windows":
            return models.DiscoverySnapshot(
                source_id=self.source_id,
                state=models.DiscoveryState.UNAVAILABLE,
                reason="Windows On-Device Agent Registry requires Windows",
            )
        executable = self._executable or self._candidate()
        if not executable:
            return models.DiscoverySnapshot(
                source_id=self.source_id,
                state=models.DiscoveryState.UNAVAILABLE,
                reason="Windows On-Device Agent Registry is not available",
            )
        try:
            completed = self._runner(
                [str(executable), "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise discovery.CapabilityDiscoveryError(
                f"ODR inventory failed: {type(exc).__name__}"
            ) from exc
        if completed.returncode != 0:
            return models.DiscoverySnapshot(
                source_id=self.source_id,
                state=models.DiscoveryState.DEGRADED,
                reason="ODR inventory command returned a non-zero status",
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )
        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise discovery.CapabilityDiscoveryError("ODR inventory returned invalid JSON") from exc
        entries = payload if isinstance(payload, list) else payload.get("servers", [])
        if not isinstance(entries, list):
            raise discovery.CapabilityDiscoveryError("ODR inventory shape is unsupported")
        capabilities: list[models.CapabilityDescriptor] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("id") or entry.get("name") or f"server-{index + 1}"
            name = str(raw_name).strip()
            if not name:
                continue
            capabilities.append(
                models.CapabilityDescriptor.create(
                    capability_id=f"mcp.{index + 1}",
                    source_id=self.source_id,
                    kind=models.CapabilityKind.SEMANTIC_CONNECTOR,
                    name=name,
                    description=str(entry.get("description") or "Registered Windows MCP server"),
                    metadata={"registry_entry": name},
                    execution_enabled=False,
                )
            )
        return models.DiscoverySnapshot(
            source_id=self.source_id,
            state=models.DiscoveryState.AVAILABLE,
            capabilities=tuple(capabilities),
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )
