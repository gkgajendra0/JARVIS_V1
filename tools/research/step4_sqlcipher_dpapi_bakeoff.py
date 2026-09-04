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
CRYPTO_PATH = REPO_ROOT / "src" / "jarvis" / "identity" / "crypto.py"


def load_dpapi_types() -> tuple[type[Exception], type[Any]]:
    """Load only the existing DPAPI implementation without importing identity package."""
    module_name = "jarvis_step4_identity_crypto_probe"
    spec = importlib.util.spec_from_file_location(module_name, CRYPTO_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load DPAPI module from {CRYPTO_PATH}")
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
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        conn = stdlib_sqlite.connect(uri, uri=True)
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
    except Exception:
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
    data[100] ^= 0x01
    target.write_bytes(data)


def run_memory_security_subprocess_probe(artifact_dir: Path) -> dict[str, Any]:
    """Probe enhanced SQLCipher memory security without risking the parent process."""
    probe_db = artifact_dir / "memory-security-probe.db"
    child_code = r'''
import os
import sys
import sqlcipher3

path = sys.argv[1]
key = os.urandom(32)
conn = sqlcipher3.connect(path)
conn.execute(f'''PRAGMA key = "x'{key.hex()}'"''')
conn.execute("PRAGMA cipher_memory_security = ON")
conn.execute("CREATE TABLE probe(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
conn.execute("INSERT INTO probe(value) VALUES ('synthetic-memory-security-probe')")
conn.commit()
count = conn.execute("SELECT count(*) FROM probe").fetchone()[0]
conn.close()
print(f"PROBE_OK={count}", flush=True)
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-c", child_code, str(probe_db)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "returncode": None,
            "timed_out": True,
            "stdout": (exc.stdout or "")[-2000:],
            "stderr": (exc.stderr or "")[-4000:],
        }

    return {
        "passed": completed.returncode == 0 and "PROBE_OK=1" in completed.stdout,
        "returncode": completed.returncode,
        "timed_out": False,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-4000:],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir",
        default=".step4-sqlcipher-artifacts",
        help="Synthetic research artifacts only; directory is recreated each run.",
    )
    parser.add_argument(
        "--output",
        default=".step4-sqlcipher-results.json",
        help="UTF-8 JSON result file.",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("This bake-off must run on the real JARVIS Windows machine.")

    artifact_dir = Path(args.artifact_dir)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    print("STEP4_SQLCIPHER_STAGE=memory_security_subprocess_probe", flush=True)
    memory_security_probe = run_memory_security_subprocess_probe(artifact_dir)

    db_path = artifact_dir / "memory.db"
    sealed_key_path = artifact_dir / "memory.key.dpapi"
    backup_dir = artifact_dir / "backup"
    backup_dir.mkdir()
    restored_db = artifact_dir / "restored-memory.db"
    corrupted_db = artifact_dir / "corrupted-memory.db"

    print("STEP4_SQLCIPHER_STAGE=dpapi", flush=True)
    raw_key = os.urandom(KEY_BYTES)
    protector = WindowsDpapiKeyProtector()
    sealed = protector.seal(raw_key, purpose=PURPOSE)
    sealed_key_path.write_bytes(sealed)

    dpapi_roundtrip = protector.unseal(sealed, purpose=PURPOSE) == raw_key
    try:
        protector.unseal(sealed, purpose=PURPOSE + "-wrong")
    except KeyProtectionError:
        dpapi_wrong_purpose_blocked = True
    else:
        dpapi_wrong_purpose_blocked = False

    raw_key_not_in_sealed_blob = raw_key not in sealed

    print("STEP4_SQLCIPHER_STAGE=core_database", flush=True)
    conn = sqlcipher3.connect(str(db_path))
    key_connection(conn, raw_key)

    cipher_version = scalar(conn, "PRAGMA cipher_version")
    sqlite_version = scalar(conn, "SELECT sqlite_version()")
    compile_options = [row[0] for row in conn.execute("PRAGMA compile_options")]
    provider = scalar(conn, "PRAGMA cipher_provider")
    provider_version = scalar(conn, "PRAGMA cipher_provider_version")
    memory_security_default = scalar(conn, "PRAGMA cipher_memory_security")

    if not cipher_version:
        raise RuntimeError("PRAGMA cipher_version returned no SQLCipher version")

    # Keep SQLCipher's enhanced all-SQLite-memory security at its supported
    # default here. It is probed separately in a child process above because
    # native wrapper/platform failures must not erase the at-rest test result.
    conn.execute("PRAGMA temp_store = MEMORY")
    temp_store = scalar(conn, "PRAGMA temp_store")
    conn.execute("PRAGMA secure_delete = ON")
    secure_delete = scalar(conn, "PRAGMA secure_delete")
    journal_mode = scalar(conn, "PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute("PRAGMA synchronous = FULL")

    conn.executescript(
        """
        CREATE TABLE memory (
            id INTEGER PRIMARY KEY,
            language TEXT NOT NULL,
            body TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            memory_id UNINDEXED,
            body
        );
        """
    )
    for index, (language, body) in enumerate(MARKERS.items(), start=1):
        conn.execute(
            "INSERT INTO memory(id, language, body) VALUES (?, ?, ?)",
            (index, language, body),
        )
        conn.execute(
            "INSERT INTO memory_fts(memory_id, body) VALUES (?, ?)",
            (index, body),
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
    except Exception:
        pass

    integrity_before = [row[0] for row in conn.execute("PRAGMA cipher_integrity_check")]

    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    needles = {label: text.encode("utf-8") for label, text in MARKERS.items()}
    needles.update(
        {"raw_key": raw_key, "raw_key_hex": raw_key.hex().encode("ascii")}
    )
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
                except Exception as exc:
                    corruption_detected = True
                    corruption_detail = type(exc).__name__
        finally:
            corrupted.close()
    except Exception as exc:
        corruption_detected = True
        corruption_detail = type(exc).__name__

    print("STEP4_SQLCIPHER_STAGE=forget", flush=True)
    forgetting = open_keyed(db_path, raw_key)
    forgetting.execute("PRAGMA secure_delete = ON")
    forgetting.execute("DELETE FROM memory_fts WHERE memory_id = 2")
    forgetting.execute("DELETE FROM memory WHERE id = 2")
    forgetting.commit()
    forgetting.execute("VACUUM")
    forgotten_canonical = scalar(
        forgetting, "SELECT count(*) FROM memory WHERE id = 2"
    )
    forgotten_fts = scalar(
        forgetting,
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'एन्क्रिप्शन'",
    )
    integrity_after = [
        row[0] for row in forgetting.execute("PRAGMA cipher_integrity_check")
    ]
    forgetting.close()

    final_leaks = scan_files([db_path, sealed_key_path], needles)

    fts5_compiled = any("ENABLE_FTS5" in option for option in compile_options)
    temp_store_compile = next(
        (option for option in compile_options if option.startswith("TEMP_STORE=")),
        None,
    )

    checks = {
        "sqlcipher_present": bool(cipher_version),
        "dpapi_roundtrip": dpapi_roundtrip,
        "dpapi_wrong_purpose_blocked": dpapi_wrong_purpose_blocked,
        "raw_key_not_in_dpapi_blob": raw_key_not_in_sealed_blob,
        "fts5_compiled": fts5_compiled,
        "fts_en_works": fts_en_hits == 1,
        "fts_hi_works": fts_hi_hits == 1,
        "canonical_write_read": canonical_count == 3,
        "temp_store_memory": temp_store == 2,
        "secure_delete_on": secure_delete == 1,
        "wal_mode": str(journal_mode).casefold() == "wal",
        "cipher_integrity_clean_before": integrity_before == [],
        "no_plaintext_leak_while_wal_live": live_leaks == {},
        "stdlib_sqlite_without_key_blocked": plaintext_sqlite_blocked,
        "wrong_sqlcipher_key_blocked": wrong_key_blocked,
        "no_plaintext_leak_after_close": closed_leaks == {},
        "backup_restore_count": restored_count == 3,
        "backup_restore_fts": restored_fts_hits == 1,
        "ciphertext_corruption_detected": corruption_detected,
        "forget_canonical_zero": forgotten_canonical == 0,
        "forget_fts_zero": forgotten_fts == 0,
        "cipher_integrity_clean_after_forget": integrity_after == [],
        "no_plaintext_or_key_leak_final": final_leaks == {},
    }

    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "purpose": "research-only; no production SQLCipher/package approval",
        "package": {
            "sqlcipher3_version": importlib.metadata.version("sqlcipher3"),
            "sqlcipher_version": cipher_version,
            "sqlite_version": sqlite_version,
            "cipher_provider": provider,
            "cipher_provider_version": provider_version,
            "cipher_status": cipher_status,
            "compile_options": compile_options,
            "fts5_compiled": fts5_compiled,
            "temp_store_compile_option": temp_store_compile,
        },
        "runtime": {
            "journal_mode": journal_mode,
            "temp_store": temp_store,
            "secure_delete": secure_delete,
            "cipher_memory_security_default": memory_security_default,
        },
        "enhanced_memory_security_probe": memory_security_probe,
        "leak_scans": {
            "while_wal_live": live_leaks,
            "after_close": closed_leaks,
            "final": final_leaks,
        },
        "corruption_detail": corruption_detail,
        "checks": checks,
        "artifact_dir": str(artifact_dir),
        "notes": [
            "All stored values are synthetic test markers.",
            "The raw database key is never written to the JSON report.",
            "Core PASS evaluates at-rest encryption/storage behavior using SQLCipher's supported default enhanced-memory-security setting.",
            "PRAGMA cipher_memory_security=ON is an optional enhanced all-SQLite-memory feature and is probed in a separate child process so a native wrapper/platform failure cannot erase the core result.",
            "The harness loads the existing identity crypto.py directly to validate the current Windows DPAPI primitive without executing jarvis.identity package initialization; production memory must use a neutral security boundary rather than importing identity internals.",
        ],
    }

    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("STEP4_SQLCIPHER_STAGE=result_written", flush=True)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
