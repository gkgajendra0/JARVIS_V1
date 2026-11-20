"""The rehearsal tool's inventory is numbers-only and detects any row change."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)

TOOL = Path(__file__).resolve().parents[1] / "tools" / "memory_migration_rehearsal.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("rehearsal_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_is_numbers_only_and_flags_changed_rows():
    tool = load_tool()
    conn = sqlite3.connect(":memory:")
    MemoryMigrationRunner(discover_memory_migrations()[:7]).apply(conn)
    conn.execute(
        "INSERT INTO personal_learning_suppression VALUES ('plan', 1, 0, 'secret-ish')"
    )
    before = tool.summary(conn)
    text = json.dumps(before)
    assert "secret-ish" not in text and "plan" not in text.replace(
        "personal_learning_suppression", ""
    ).replace("conversation_topic_checkpoint", "")
    assert before["user_version"] == 7
    MemoryMigrationRunner().apply(conn)
    after = tool.summary(conn)
    result = tool.compare(before, after)
    assert result["differing_tables"] == []
    assert result["added_tables"] == ["personal_learning_outcome"]
    conn.execute("UPDATE personal_learning_suppression SET epoch = 2")
    assert tool.compare(before, tool.summary(conn))["differing_tables"] == [
        "personal_learning_suppression"
    ]
