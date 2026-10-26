"""Check executable/help/schema compatibility; never control a desktop window."""

import json
import shutil
from pathlib import Path

from jarvis.capabilities.models import DiscoveryState
from jarvis.capabilities.windows_sources import WinAppCliSchemaSource
from jarvis.computer.structured_windows import WinAppCliBackend

expected = Path("E:/Jarvis/Data/LocalState/tools/winapp/winapp.exe").resolve()
resolved = shutil.which("winapp")
assert resolved and Path(resolved).resolve() == expected, resolved
backend = WinAppCliBackend()
probe = backend.probe()
assert probe.payload["exit_code"] == 0
source = WinAppCliSchemaSource().discover()
assert source.state is DiscoveryState.AVAILABLE, (source.state, source.reason)
capability = source.capabilities[0]
assert {"status", "inspect", "invoke", "send-keys"}.issubset(capability.operations), (
    capability.operations
)
print(
    json.dumps(
        {
            "status": "PASS",
            "resolved_executable": resolved,
            "help_probe": "passed",
            "schema_discovery": source.state.value,
            "version": capability.metadata().get("version"),
            "operation_count": len(capability.operations),
            "operations": capability.operations,
            "desktop_actions_performed": False,
        },
        indent=2,
    )
)
