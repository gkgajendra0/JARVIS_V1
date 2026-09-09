"""Bounded read-only local machine awareness."""

from __future__ import annotations

import datetime
import os
import pathlib
import platform
import time
from typing import Any

import psutil

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)


class SystemReadValidationError(ValueError):
    pass


class SystemReadExecutor:
    capability_key = "local:system.read"
    operations = ("list_processes", "system_status")

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor.create(
            capability_id="system.read",
            source_id="local",
            kind=CapabilityKind.NATIVE_API,
            name="Local system awareness",
            description=(
                "Read-only machine status and bounded process metadata using psutil and "
                "standard operating-system APIs."
            ),
            operations=list(self.operations),
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise SystemReadValidationError("unsupported system read operation")
        params = dict(request.parameters)
        if request.operation == "list_processes":
            limit = int(params.get("max_results", 30))
            if limit < 1 or limit > 100:
                raise SystemReadValidationError("max_results must be between 1 and 100")
            params["max_results"] = limit
            attributes = ActionAttributes(private_read=True)
            summary = "Read bounded local process names and states"
        else:
            params = {}
            attributes = ActionAttributes()
            summary = "Read aggregate local machine health and uptime"
        return PreparedCapability(
            request=request,
            target={"machine": platform.node() or "local"},
            parameters=params,
            material_summary=summary,
            attributes=attributes,
            execution_payload={},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            if prepared.request.operation == "system_status":
                data = self._system_status()
                provenance = ("psutil", "platform", "datetime")
            else:
                data = self._list_processes(int(prepared.parameters["max_results"]))
                provenance = ("psutil.process_iter",)
            return CapabilityResult(
                status=CapabilityStatus.SUCCEEDED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data=data,
                elapsed_ms=(time.monotonic() - started) * 1000.0,
                provenance=provenance,
            )
        except (OSError, psutil.Error, ValueError) as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={},
                reason=f"system read failed: {type(exc).__name__}",
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )

    @staticmethod
    def _system_status() -> dict[str, Any]:
        now = datetime.datetime.now().astimezone()
        boot_epoch = float(psutil.boot_time())
        memory = psutil.virtual_memory()
        drive = pathlib.Path(os.environ.get("SystemDrive", "C:") + os.sep)
        if os.name != "nt":
            drive = pathlib.Path("/")
        disk = psutil.disk_usage(str(drive))
        return {
            "local_time": now.isoformat(timespec="seconds"),
            "timezone": str(now.tzinfo),
            "platform": platform.platform(),
            "machine": platform.node(),
            "boot_time_epoch": boot_epoch,
            "uptime_seconds": max(0.0, time.time() - boot_epoch),
            "cpu_logical_count": psutil.cpu_count(logical=True),
            "cpu_physical_count": psutil.cpu_count(logical=False),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_total_bytes": int(memory.total),
            "memory_available_bytes": int(memory.available),
            "memory_percent": float(memory.percent),
            "disk_root": str(drive),
            "disk_total_bytes": int(disk.total),
            "disk_free_bytes": int(disk.free),
            "disk_percent": float(disk.percent),
        }

    @staticmethod
    def _list_processes(max_results: int) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for process in psutil.process_iter(["pid", "name", "status"]):
            try:
                info = process.info
                name = str(info.get("name") or "").strip()
                if not name:
                    continue
                items.append(
                    {
                        "pid": int(info["pid"]),
                        "name": name,
                        "status": str(info.get("status") or "unknown"),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        items.sort(key=lambda item: (str(item["name"]).casefold(), int(item["pid"])))
        truncated = len(items) > max_results
        return {
            "processes": items[:max_results],
            "truncated": truncated,
        }
