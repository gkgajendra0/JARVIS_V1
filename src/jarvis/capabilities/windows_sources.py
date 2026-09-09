"""Read-only discovery adapters for mature Windows capability surfaces."""

from __future__ import annotations

import json
import pathlib
import platform
import shutil
import subprocess
import time
from collections import abc

from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)


Runner = abc.Callable[..., subprocess.CompletedProcess[str]]
Clock = abc.Callable[[], float]


class WinAppCliSchemaSource:
    """Discover the installed Microsoft winapp UI surface from `--cli-schema`.

    Only the `ui` command family is imported. Other winapp command families
    (packaging, signing, certificates, install, etc.) are deliberately excluded.
    """

    SOURCE_ID = "windows.winapp"

    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: Runner = subprocess.run,
        monotonic: Clock = time.perf_counter,
    ) -> None:
        self._executable = executable
        self._runner = runner
        self._monotonic = monotonic

    @property
    def source_id(self) -> str:
        return self.SOURCE_ID

    def discover(self) -> DiscoverySnapshot:
        if platform.system() != "Windows":
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.UNAVAILABLE,
                reason="winapp discovery requires Windows",
            )
        executable = self._executable or shutil.which("winapp")
        if not executable:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.UNAVAILABLE,
                reason="winapp executable not found",
            )

        started = self._monotonic()
        try:
            completed = self._runner(
                [executable, "--cli-schema"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(self._monotonic() - started) * 1000,
            )

        elapsed_ms = (self._monotonic() - started) * 1000
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason=detail[:500] or f"winapp exited {completed.returncode}",
                elapsed_ms=elapsed_ms,
            )

        try:
            schema = json.loads(completed.stdout or "")
            capability = self._parse_ui_capability(schema, executable)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason=f"invalid winapp schema: {exc}",
                elapsed_ms=elapsed_ms,
            )

        return DiscoverySnapshot(
            source_id=self.source_id,
            state=DiscoveryState.AVAILABLE,
            capabilities=(capability,),
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def _parse_ui_capability(
        cls,
        schema: object,
        executable: str,
    ) -> CapabilityDescriptor:
        if not isinstance(schema, dict):
            raise TypeError("root must be an object")
        subcommands = schema.get("subcommands")
        if not isinstance(subcommands, dict):
            raise TypeError("missing subcommands")
        ui = subcommands.get("ui")
        if not isinstance(ui, dict):
            raise TypeError("missing ui command family")
        ui_subcommands = ui.get("subcommands")
        if not isinstance(ui_subcommands, dict):
            raise TypeError("ui command family has no subcommands")

        operations = [
            name
            for name, node in ui_subcommands.items()
            if isinstance(name, str)
            and isinstance(node, dict)
            and not bool(node.get("hidden", False))
        ]
        if not operations:
            raise ValueError("ui command family exposes no visible operations")

        description = str(ui.get("description") or "Windows UI automation via winapp")
        version = str(schema.get("version") or "unknown")
        return CapabilityDescriptor.create(
            capability_id="desktop.ui",
            source_id=cls.SOURCE_ID,
            kind=CapabilityKind.STRUCTURED_AUTOMATION,
            name="Microsoft winapp UI Automation",
            description=description,
            operations=operations,
            metadata={
                "provider": "Microsoft",
                "schema_version": str(schema.get("schemaVersion") or "unknown"),
                "winapp_version": version,
                "executable_name": pathlib.Path(executable).name,
                "discovery_command": "winapp --cli-schema",
                "metadata_is_untrusted": True,
            },
        )


class WindowsOdrSource:
    """Inventory MCP servers registered in the Windows On-Device Registry.

    This source does not run, connect to, or call any discovered MCP server.
    """

    SOURCE_ID = "windows.odr"

    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: Runner = subprocess.run,
        monotonic: Clock = time.perf_counter,
    ) -> None:
        self._executable = executable
        self._runner = runner
        self._monotonic = monotonic

    @property
    def source_id(self) -> str:
        return self.SOURCE_ID

    def discover(self) -> DiscoverySnapshot:
        if platform.system() != "Windows":
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.UNAVAILABLE,
                reason="Windows ODR requires Windows",
            )
        executable = self._executable or shutil.which("odr.exe") or shutil.which("odr")
        if not executable:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.UNAVAILABLE,
                reason="Windows On-Device Agent Registry is not available",
            )

        started = self._monotonic()
        try:
            completed = self._runner(
                [executable, "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8.0,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(self._monotonic() - started) * 1000,
            )

        elapsed_ms = (self._monotonic() - started) * 1000
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason=detail[:500] or f"odr exited {completed.returncode}",
                elapsed_ms=elapsed_ms,
            )

        try:
            decoded = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason=f"invalid ODR JSON: {exc}",
                elapsed_ms=elapsed_ms,
            )
        if not isinstance(decoded, list):
            return DiscoverySnapshot(
                source_id=self.source_id,
                state=DiscoveryState.FAILED,
                reason="invalid ODR JSON: root must be a list",
                elapsed_ms=elapsed_ms,
            )

        capabilities: list[CapabilityDescriptor] = []
        ignored = 0
        for index, item in enumerate(decoded):
            try:
                capabilities.append(self._descriptor(item, index=index))
            except (TypeError, ValueError):
                ignored += 1

        state = DiscoveryState.DEGRADED if ignored else DiscoveryState.AVAILABLE
        reason = f"ignored_invalid_entries:{ignored}" if ignored else None
        return DiscoverySnapshot(
            source_id=self.source_id,
            state=state,
            capabilities=tuple(capabilities),
            reason=reason,
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def _descriptor(cls, item: object, *, index: int) -> CapabilityDescriptor:
        if not isinstance(item, dict):
            raise TypeError("ODR entry must be an object")
        manifest = item.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        manifest_server = manifest.get("server")
        manifest_server = manifest_server if isinstance(manifest_server, dict) else {}
        config = manifest_server.get("mcp_config")
        config = config if isinstance(config, dict) else {}

        raw_name = (
            item.get("id")
            or item.get("name")
            or manifest_server.get("id")
            or manifest_server.get("name")
            or manifest.get("name")
        )
        if not isinstance(raw_name, str) or not raw_name.strip():
            raw_name = f"registered-server-{index + 1}"
        name = raw_name.strip()
        safe_id = "".join(
            character.lower() if character.isalnum() else "." for character in name
        ).strip(".")
        safe_id = ".".join(part for part in safe_id.split(".") if part)
        if not safe_id:
            safe_id = f"server.{index + 1}"

        description = (
            item.get("description")
            or manifest.get("description")
            or manifest_server.get("description")
            or "MCP server registered in the Windows On-Device Agent Registry"
        )
        return CapabilityDescriptor.create(
            capability_id=f"mcp.{safe_id}",
            source_id=cls.SOURCE_ID,
            kind=CapabilityKind.SEMANTIC_CONNECTOR,
            name=name,
            description=str(description),
            metadata={
                "provider": "Windows ODR",
                "has_launch_command": bool(config.get("command")),
                "transport_hint": str(config.get("transport") or "unknown"),
                "discovery_command": "odr.exe list",
                "metadata_is_untrusted": True,
                "tools_discovered": False,
            },
        )
