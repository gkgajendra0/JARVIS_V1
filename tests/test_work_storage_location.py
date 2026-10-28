import os

import pytest

from jarvis.self_awareness import default_incident_store_path
from jarvis.work.store import default_work_state_dir


@pytest.mark.skipif(os.name != "nt", reason="Windows portable machine profile")
def test_work_storage_follows_explicit_machine_profile(tmp_path, monkeypatch):
    profile = tmp_path / "portable-state" / "machine.json"
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(profile))
    assert default_work_state_dir() == (profile.parent / "work").resolve()
    assert (
        default_incident_store_path()
        == profile.parent / "operations" / "incidents.sqlite3"
    )
