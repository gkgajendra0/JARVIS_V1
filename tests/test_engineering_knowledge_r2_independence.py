from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_incident_persistence_starts_when_engineeringknowledge_imports_are_blocked(
    tmp_path: Path,
) -> None:
    script = r"""
import importlib.abc
import sys
from pathlib import Path

class BlockEngineeringKnowledge(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "jarvis.engineering_knowledge" or fullname.startswith(
            "jarvis.engineering_knowledge."
        ):
            raise ImportError("EngineeringKnowledge intentionally unavailable")
        return None

sys.meta_path.insert(0, BlockEngineeringKnowledge())

from jarvis.incidents import IncidentService, SqliteIncidentStore

store = SqliteIncidentStore(Path(sys.argv[1]))
service = IncidentService(store)
incident = service.create_manual(
    symptom="r2 independence probe",
    affected_components=("runtime.voice",),
    now_epoch=100.0,
)
loaded = store.get(incident.incident_id)
assert loaded is not None
assert loaded.symptom == "r2 independence probe"
assert not any(
    name == "jarvis.engineering_knowledge"
    or name.startswith("jarvis.engineering_knowledge.")
    for name in sys.modules
)
store.close()
print("R2_INCIDENT_PERSISTENCE_INDEPENDENT")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "incidents.sqlite3")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "R2_INCIDENT_PERSISTENCE_INDEPENDENT" in result.stdout
