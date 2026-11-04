"""Fresh deployment of the canonical memory database (owner-approved: no
preservation of existing memory records)."""

from types import SimpleNamespace

import pytest
from test_memory_database import FakeSqlCipherDriver, StubKeyProtector

from jarvis.memory import fresh_initialization as fresh
from jarvis.memory.database import SqlCipherMemoryDatabaseFactory
from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)


def opener(database):
    driver = FakeSqlCipherDriver()  # SQLCipher stand-in; the real one is CI'd
    return SqlCipherMemoryDatabaseFactory(
        database,
        key_protector=StubKeyProtector(),
        driver_loader=lambda: driver,
    ).open


def installed_profile(tmp_path):
    """The data folder as installed: old schema-3 memory plus unrelated state."""
    data = tmp_path / "LocalState"
    data.mkdir()
    old = opener(data / "memory.db")
    runner = MemoryMigrationRunner(discover_memory_migrations()[:3])
    factory = SqlCipherMemoryDatabaseFactory(
        data / "memory.db",
        key_protector=StubKeyProtector(),
        driver_loader=lambda: FakeSqlCipherDriver(),
        migration_runner=runner,
    )
    connection = factory.open()
    connection.execute("CREATE TABLE owner_notes (body TEXT)")
    connection.execute("INSERT INTO owner_notes VALUES ('experimental')")
    connection._inner.commit()
    connection.close()
    del old
    unrelated = {
        "machine.json": b'{"schema_version": 1, "settings": {}}',
        "authority/step7_audit.sqlite3": b"authority",
        "identity/owner.template": b"identity",
        "work/state.db": b"work",
        "secrets/x": b"secret",
    }
    for name, body in unrelated.items():
        (data / name).parent.mkdir(parents=True, exist_ok=True)
        (data / name).write_bytes(body)
    return data, unrelated


def snapshot(data):
    return {
        str(p.relative_to(data)): p.read_bytes()
        for p in data.rglob("*")
        if p.is_file() and p.name not in fresh.MEMORY_FILES
    }


def no_jarvis():
    return []


def test_initialize_creates_a_clean_latest_database_and_touches_nothing_else(
    tmp_path, capsys
):
    data, _ = installed_profile(tmp_path)
    before = snapshot(data)
    old_key = (data / "memory.key.dpapi").read_bytes()
    retired_root = tmp_path / "Retired"
    code = fresh.main(
        ["initialize", "--data", str(data), "--retire-to", str(retired_root)],
        opener=opener,
        processes=no_jarvis,
    )
    out = capsys.readouterr().out
    assert code == 0 and "Memory database: PASS" in out
    assert snapshot(data) == before  # configuration, authority, identity, work kept
    (retired,) = list(retired_root.iterdir())
    assert sorted(p.name for p in retired.iterdir()) >= [
        "memory.db",
        "memory.key.dpapi",
    ]
    assert (data / "memory.key.dpapi").read_bytes() != old_key  # a new key
    report = fresh.verify_memory_database(
        opener(data / "memory.db"),
        MemoryMigrationRunner().latest_version,
        expect_empty=True,
    )
    assert report["verdict"] == "PASS"
    assert report["schema_version"] == 7 and report["nonempty_tables"] == []
    assert "experimental" not in out


def test_initialize_refuses_while_jarvis_runs(tmp_path, capsys):
    data, _ = installed_profile(tmp_path)
    code = fresh.main(
        ["initialize", "--data", str(data), "--retire-to", str(tmp_path / "R")],
        opener=opener,
        processes=lambda: [
            SimpleNamespace(
                info={
                    "pid": 42,
                    "name": "python.exe",
                    "cmdline": ["-m", "jarvis.runtime_supervisor"],
                }
            )
        ],
    )
    assert code == 2 and (data / "memory.db").exists()
    assert not (tmp_path / "R").exists()


def test_a_file_in_use_moves_nothing(tmp_path, monkeypatch):
    data, _ = installed_profile(tmp_path)
    (data / "memory.db-wal").write_bytes(b"wal")
    real = type(data).replace

    def replace(self, target):
        if self.name == "memory.db-wal":
            raise PermissionError("in use")
        return real(self, target)

    monkeypatch.setattr(type(data), "replace", replace)
    with pytest.raises(fresh.InitializationError):
        fresh.retire_memory_files(data, tmp_path / "R")
    assert (data / "memory.db").exists() and (data / "memory.key.dpapi").exists()


def test_retired_files_never_stay_inside_the_data_folder(tmp_path):
    data, _ = installed_profile(tmp_path)
    with pytest.raises(fresh.InitializationError):
        fresh.retire_memory_files(data, data / "old")


def test_restore_brings_the_retired_set_back_for_a_code_rollback(tmp_path, capsys):
    data, _ = installed_profile(tmp_path)
    root = tmp_path / "Retired"
    fresh.main(
        ["initialize", "--data", str(data), "--retire-to", str(root)],
        opener=opener,
        processes=no_jarvis,
    )
    (retired,) = list(root.iterdir())
    assert (
        fresh.main(
            [
                "restore",
                "--data",
                str(data),
                "--retire-to",
                str(root),
                "--from",
                str(retired),
            ],
            opener=opener,
            processes=no_jarvis,
        )
        == 0
    )
    runner_version = (
        SqlCipherMemoryDatabaseFactory(
            data / "memory.db",
            key_protector=StubKeyProtector(),
            driver_loader=lambda: FakeSqlCipherDriver(),
            migration_runner=fresh._NoMigrationForTests(),
        )
        .open()
        .execute("PRAGMA user_version")
        .fetchone()[0]
    )
    assert runner_version == 3  # the old schema-3 set is back


def test_verify_reports_a_non_empty_database(tmp_path):
    data, _ = installed_profile(tmp_path)
    report = fresh.verify_memory_database(
        opener(data / "memory.db"), 7, expect_empty=True
    )  # opening migrates 3 -> 7 but the old rows remain
    assert report["verdict"] == "FAIL"
    assert "owner_notes" in report["nonempty_tables"]


def test_jarvis_process_detection():
    procs = [
        SimpleNamespace(
            info={
                "pid": 1,
                "name": "python.exe",
                "cmdline": ["-m", "jarvis.voice.production_runtime"],
            }
        ),
        SimpleNamespace(info={"pid": 2, "name": "jarvis-voice.exe", "cmdline": []}),
        SimpleNamespace(
            info={"pid": 3, "name": "code.exe", "cmdline": ["jarvis_notes.txt"]}
        ),
    ]
    assert fresh.jarvis_processes(lambda: procs) == [1, 2]
