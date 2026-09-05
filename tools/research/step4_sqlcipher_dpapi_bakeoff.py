from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import sqlite3 as stdlib_sqlite
import subprocess
import sys
from pathlib import Path
from typing import Any

import sqlcipher3

REPO_ROOT = Path(__file__).resolve().parents[2]
DPAPI_PATH = REPO_ROOT / "src" / "jarvis" / "security" / "dpapi.py"


def load_dpapi_types() -> tuple[type[Exception], type[Any]]:
    """Load only the neutral DPAPI module without importing unrelated packages."""
    module_name = "jarvis_step4_security_dpapi_probe"
    spec = importlib.util.spec_from_file_location(module_name, DPAPI_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load DPAPI module from {DPAPI_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.KeyProtectionError, module.WindowsDpapiKeyProtector


KeyProtectionError, WindowsDpapiKeyProtector = load_dpapi_types()

PURPOSE = "memory-sqlcipher-master-key-v1"
KEY_BYTES = 32
MARKERS = {
    "en": "JARVIS_ENCRYPTION_MARKER_ALPHA preferred Jimny tyre 235/75 R15",
    "hi": "जार्विस एन्क्रिप्शन परीक्षण स्मृति",
    "hinglish": "Jarvis meri memory ko encrypted rakho",
}


def scalar(conn: Any, sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    return None if row is None else row[0]


def key_connection(conn: Any, key: bytes) -> None:
    if len(key) != KEY_BYTES:
        raise ValueError("SQLCipher raw key must be 32 bytes")
    conn.execute(f'''PRAGMA key = "x'{key.hex()}'"''')


def open_keyed(path: Path, key: bytes) -> Any:
    conn = sqlcipher3.connect(str(path))
    key_connection(conn, key)
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return conn


def scan_files(paths: list[Path], needles: dict[str, bytes]) -> dict[str, list[str]]:
    leaks: dict[str, list[str]] = {}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        blob = path.read_bytes()
        found = [label for label, needle in needles.items() if needle in blob]
        if found:
            leaks[path.name] = found
    return leaks


def negative_plain_sqlite_open(path: Path) -> bool:
    try:
        conn = stdlib_sqlite.connect(str(path))
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except stdlib_sqlite.DatabaseError:
        return True
    return False


def negative_wrong_key_open(path: Path) -> bool:
    wrong = os.urandom(KEY_BYTES)
    conn = sqlcipher3.connect(str(path))
    try:
        key_connection(conn, wrong)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception:  # noqa: BLE001 - any keyed-open failure proves the wrong key was blocked
        return True
    finally:
        conn.close()
    return False


def corrupt_copy(source: Path, target: Path) -> None:
    shutil.copy2(source, target)
    data = bytearray(target.read_bytes())
    if len(data) < 512:
        raise RuntimeError("database unexpectedly too small for corruption probe")
    # Preserve the 16-byte salt but flip ciphertext in the first encrypted page.
    data[100] ^= 0xFF
    target.write_bytes(data)


def sqlcipher_metadata() -> dict[str, Any]:
    conn = sqlcipher3.connect(":memory:")
    try:
        key_connection(conn, os.urandom(KEY_BYTES))
        sqlite_version = scalar(conn, "SELECT sqlite_version()")
        sqlcipher_version = scalar(conn, "PRAGMA cipher_version")
        cipher_provider = scalar(conn, "PRAGMA cipher_provider")
        cipher_provider_version = scalar(conn, "PRAGMA cipher_provider_version")
        compile_options = [row[0] for row in conn.execute("PRAGMA compile_options")]
    finally:
        conn.close()
    return {
        "sqlcipher3_version": importlib.metadata.version("sqlcipher3"),
        "sqlcipher_version": sqlcipher_version,
        "sqlite_version": sqlite_version,
        "cipher_provider": cipher_provider,
        "cipher_provider_version": cipher_provider_version,
        "compile_options": compile_options,
    }


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This bake-off must run on the Windows owner machine")

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".step4-sqlcipher-results.json"))
    args = parser.parse_args()

    output_path = args.output.resolve()
    work_dir = output_path.parent / ".step4-sqlcipher-work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    db_path = work_dir / "memory.db"
    sealed_key_path = work_dir / "memory.key.dpapi"
    backup_dir = work_dir / "backup"
    backup_dir.mkdir()
    restored_db = work_dir / "restored.db"
    corrupted_db = work_dir / "corrupted.db"

    print("STEP4_SQLCIPHER_STAGE=dpapi", flush=True)
    protector = WindowsDpapiKeyProtector()
    raw_key = os.urandom(KEY_BYTES)
    sealed_key = protector.seal(raw_key, purpose=PURPOSE)
    sealed_key_path.write_bytes(sealed_key)
    recovered_key = protector.unseal(sealed_key, purpose=PURPOSE)
    dpapi_roundtrip = recovered_key == raw_key
    wrong_purpose_rejected = False
    try:
        protector.unseal(sealed_key, purpose=f"{PURPOSE}-wrong")
    except KeyProtectionError:
        wrong_purpose_rejected = True

    package = sqlcipher_metadata()
    compile_options = package["compile_options"]

    print("STEP4_SQLCIPHER_STAGE=create", flush=True)
    conn = sqlcipher3.connect(str(db_path))
    key_connection(conn, raw_key)
    conn.execute("PRAGMA cipher_memory_security = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute(
        """
        CREATE TABLE memory (
            id INTEGER PRIMARY KEY,
            language TEXT NOT NULL,
            body TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            memory_id UNINDEXED,
            body
        )
        """
    )
    rows = [
        (1, "en", MARKERS["en"]),
        (2, "hi", MARKERS["hi"]),
        (3, "hinglish", MARKERS["hinglish"]),
    ]
    conn.executemany("INSERT INTO memory(id, language, body) VALUES (?, ?, ?)", rows)
    conn.executemany(
        "INSERT INTO memory_fts(memory_id, body) VALUES (?, ?)",
        [(memory_id, body) for memory_id, _language, body in rows],
    )
    conn.commit()

    fts_en_hits = scalar(
        conn,
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'Jimny'",
    )
    fts_hi_hits = scalar(
        conn,
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'एन्क्रिप्शन'",
    )
    canonical_count = scalar(conn, "SELECT count(*) FROM memory")

    cipher_status = None
    try:
        cipher_status = scalar(conn, "PRAGMA cipher_status")
    except Exception:  # noqa: BLE001 - cipher_status is optional across SQLCipher builds
        cipher_status = None

    integrity_before = [row[0] for row in conn.execute("PRAGMA cipher_integrity_check")]

    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    needles = {label: text.encode("utf-8") for label, text in MARKERS.items()}
    needles.update({"raw_key": raw_key, "raw_key_hex": raw_key.hex().encode("ascii")})
    live_leaks = scan_files([db_path, wal_path, shm_path, sealed_key_path], needles)

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print("STEP4_SQLCIPHER_STAGE=negative_key_tests", flush=True)
    plaintext_sqlite_blocked = negative_plain_sqlite_open(db_path)
    wrong_key_blocked = negative_wrong_key_open(db_path)
    closed_leaks = scan_files([db_path, sealed_key_path], needles)

    print("STEP4_SQLCIPHER_STAGE=backup_restore", flush=True)
    backup_db = backup_dir / "memory.db"
    backup_key = backup_dir / "memory.key.dpapi"
    shutil.copy2(db_path, backup_db)
    shutil.copy2(sealed_key_path, backup_key)
    shutil.copy2(backup_db, restored_db)
    restored_key = protector.unseal(backup_key.read_bytes(), purpose=PURPOSE)
    restored = open_keyed(restored_db, restored_key)
    restored_count = scalar(restored, "SELECT count(*) FROM memory")
    restored_fts_hits = scalar(
        restored,
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'Jimny'",
    )
    restored.close()

    print("STEP4_SQLCIPHER_STAGE=corruption", flush=True)
    corrupt_copy(db_path, corrupted_db)
    corruption_detected = False
    corruption_detail: str | list[str] | None = None
    try:
        corrupted = open_keyed(corrupted_db, raw_key)
        try:
            report = [
                row[0] for row in corrupted.execute("PRAGMA cipher_integrity_check")
            ]
            corruption_detail = report
            corruption_detected = bool(report)
            if not corruption_detected:
                try:
                    corrupted.execute("SELECT sum(length(body)) FROM memory").fetchone()
                except Exception as exc:  # noqa: BLE001 - any DB failure is valid corruption detection evidence
                    corruption_detected = True
                    corruption_detail = type(exc).__name__
        finally:
            corrupted.close()
    except Exception as exc:  # noqa: BLE001 - open/integrity failure is valid corruption evidence
        corruption_detected = True
        corruption_detail = type(exc).__name__

    print("STEP4_SQLCIPHER_STAGE=forget", flush=True)
    forgetting = open_keyed(db_path, raw_key)
    forgetting.execute("PRAGMA secure_delete = ON")
    forgetting.execute("DELETE FROM memory_fts WHERE memory_id = 2")
    forgetting.execute("DELETE FROM memory WHERE id = 2")
    forgetting.commit()
    forgetting.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    forgetting.execute("VACUUM")
    forgotten_canonical = scalar(forgetting, "SELECT count(*) FROM memory WHERE id = 2")
    forgotten_fts = scalar(
        forgetting,
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'एन्क्रिप्शन'",
    )
    integrity_after = [
        row[0] for row in forgetting.execute("PRAGMA cipher_integrity_check")
    ]
    forgetting.close()

    final_leaks = scan_files([db_path, sealed_key_path], needles)

    checks = {
        "dpapi_roundtrip": dpapi_roundtrip,
        "dpapi_wrong_purpose_rejected": wrong_purpose_rejected,
        "sealed_blob_excludes_raw_key": raw_key not in sealed_key,
        "sealed_blob_excludes_raw_key_hex": raw_key.hex().encode("ascii") not in sealed_key,
        "sqlcipher_version_reported": bool(package["sqlcipher_version"]),
        "cipher_provider_reported": bool(package["cipher_provider"]),
        "fts5_compiled": any("ENABLE_FTS5" in option for option in compile_options),
        "temp_store_compile_option_present": any(
            option.startswith("TEMP_STORE=") for option in compile_options
        ),
        "canonical_rows_created": canonical_count == 3,
        "fts_english": fts_en_hits == 1,
        "fts_hindi": fts_hi_hits == 1,
        "cipher_integrity_before_clean": not integrity_before,
        "plaintext_sqlite_blocked": plaintext_sqlite_blocked,
        "wrong_key_blocked": wrong_key_blocked,
        "live_files_no_plaintext_or_key_leaks": not live_leaks,
        "closed_files_no_plaintext_or_key_leaks": not closed_leaks,
        "same_user_machine_restore_rows": restored_count == 3,
        "same_user_machine_restore_fts": restored_fts_hits == 1,
        "corruption_detected": corruption_detected,
        "forget_removed_canonical": forgotten_canonical == 0,
        "forget_removed_fts": forgotten_fts == 0,
        "cipher_integrity_after_clean": not integrity_after,
        "final_files_no_plaintext_or_key_leaks": not final_leaks,
    }

    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "package": package,
        "checks": checks,
        "leak_scans": {
            "live": live_leaks,
            "closed": closed_leaks,
            "final": final_leaks,
        },
        "cipher_status": cipher_status,
        "corruption_detail": corruption_detail,
        "notes": [
            "Research-only harness; no production memory implementation is created here.",
            "The harness loads the neutral jarvis.security DPAPI module directly so isolated research environments do not import unrelated runtime packages.",
            "DPAPI backup/restore proves only same-user/same-machine recovery; portable recovery remains a separate architecture decision.",
        ],
    }
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
