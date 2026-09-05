from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jarvis.security import KeyProtectionError, KeyProtector

from .migration_runner import MemoryMigrationRunner

_MEMORY_KEY_BYTES = 32
_MEMORY_KEY_PURPOSE = "memory-sqlcipher-master-key:v1"
_EXPECTED_SQLCIPHER_VERSION = "4.17.0 community"
_EXPECTED_SQLITE_VERSION = "3.53.3"


class MemoryDatabaseError(RuntimeError):
    pass


class SqlCipherUnavailableError(MemoryDatabaseError):
    pass


class MemoryDatabaseKeyError(MemoryDatabaseError):
    pass


class MemoryDatabaseEncryptionError(MemoryDatabaseError):
    pass


class MemoryDatabaseKeyStore:
    """Stores only a protector-sealed SQLCipher key beside the memory database."""

    def __init__(
        self,
        key_path: str | Path,
        *,
        key_protector: KeyProtector,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._path = Path(key_path)
        self._protector = key_protector
        self._random_bytes = random_bytes

    @property
    def path(self) -> Path:
        return self._path

    def load_or_create(self, *, database_exists: bool) -> tuple[bytes, bool]:
        key_exists = self._path.exists()
        if database_exists and not key_exists:
            raise MemoryDatabaseKeyError(
                "memory database exists but its protected SQLCipher key is missing"
            )
        if key_exists and not database_exists:
            raise MemoryDatabaseKeyError(
                "protected SQLCipher key exists but the memory database is missing"
            )
        if key_exists:
            return self._unseal_existing(), False

        raw_key = self._random_bytes(_MEMORY_KEY_BYTES)
        if len(raw_key) != _MEMORY_KEY_BYTES:
            raise MemoryDatabaseKeyError("memory key generator did not return 32 bytes")
        try:
            sealed = self._protector.seal(raw_key, purpose=_MEMORY_KEY_PURPOSE)
        except KeyProtectionError as exc:
            raise MemoryDatabaseKeyError("memory database key could not be protected") from exc
        self._write_new(sealed)
        return raw_key, True

    def discard_new(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError as exc:
            raise MemoryDatabaseKeyError(
                "failed to remove newly created protected memory key"
            ) from exc

    def _unseal_existing(self) -> bytes:
        try:
            sealed = self._path.read_bytes()
        except OSError as exc:
            raise MemoryDatabaseKeyError("protected memory key could not be read") from exc
        try:
            raw_key = self._protector.unseal(sealed, purpose=_MEMORY_KEY_PURPOSE)
        except KeyProtectionError as exc:
            raise MemoryDatabaseKeyError("protected memory key could not be unsealed") from exc
        if len(raw_key) != _MEMORY_KEY_BYTES:
            raise MemoryDatabaseKeyError("unsealed memory database key is not 32 bytes")
        return raw_key

    def _write_new(self, sealed: bytes) -> None:
        if not sealed:
            raise MemoryDatabaseKeyError("protected memory key must not be empty")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self._path, flags, 0o600)
        except FileExistsError as exc:
            raise MemoryDatabaseKeyError(
                "protected memory key appeared concurrently during creation"
            ) from exc
        except OSError as exc:
            raise MemoryDatabaseKeyError("protected memory key could not be created") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self._path.unlink(missing_ok=True)
            raise


def default_memory_key_path(database_path: str | Path) -> Path:
    path = Path(database_path)
    return path.with_name(f"{path.stem}.key.dpapi")


def _load_sqlcipher_driver() -> Any:
    try:
        return importlib.import_module("sqlcipher3")
    except ImportError as exc:
        raise SqlCipherUnavailableError(
            "the pinned JARVIS SQLCipher runtime is not installed"
        ) from exc


def _scalar(connection: Any, sql: str) -> Any:
    row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


class SqlCipherMemoryDatabaseFactory:
    """Open the canonical memory DB only through the approved SQLCipher runtime."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        key_protector: KeyProtector,
        key_path: str | Path | None = None,
        driver_loader: Callable[[], Any] = _load_sqlcipher_driver,
        migration_runner: MemoryMigrationRunner | None = None,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_key_path = (
            Path(key_path)
            if key_path is not None
            else default_memory_key_path(self._database_path)
        )
        self._key_store = MemoryDatabaseKeyStore(
            resolved_key_path,
            key_protector=key_protector,
            random_bytes=random_bytes,
        )
        self._driver_loader = driver_loader
        self._migration_runner = migration_runner or MemoryMigrationRunner()

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def key_path(self) -> Path:
        return self._key_store.path

    def open(self) -> Any:
        driver = self._driver_loader()
        database_existed = self._database_path.exists()
        raw_key, key_created = self._key_store.load_or_create(
            database_exists=database_existed
        )
        connection: Any | None = None
        try:
            connection = driver.connect(str(self._database_path))
            self._key_connection(connection, raw_key)
            self._verify_encrypted_connection(connection)
            self._configure_connection(connection)
            self._migration_runner.apply(connection)
            return connection
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            if key_created and not database_existed:
                self._discard_failed_new_database()
            raise
        finally:
            del raw_key

    @staticmethod
    def _key_connection(connection: Any, raw_key: bytes) -> None:
        if len(raw_key) != _MEMORY_KEY_BYTES:
            raise MemoryDatabaseKeyError("SQLCipher raw key must be exactly 32 bytes")
        connection.execute(f'''PRAGMA key = "x'{raw_key.hex()}'"''')

    @staticmethod
    def _verify_encrypted_connection(connection: Any) -> None:
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            cipher_status = _scalar(connection, "PRAGMA cipher_status")
            cipher_version = _scalar(connection, "PRAGMA cipher_version")
            sqlite_version = _scalar(connection, "SELECT sqlite_version()")
        except Exception as exc:
            raise MemoryDatabaseEncryptionError(
                "memory database key or SQLCipher runtime could not be verified"
            ) from exc

        if int(cipher_status or 0) != 1:
            raise MemoryDatabaseEncryptionError(
                "memory database connection is not operating with SQLCipher encryption"
            )
        if str(cipher_version or "").strip() != _EXPECTED_SQLCIPHER_VERSION:
            raise MemoryDatabaseEncryptionError(
                "unsupported SQLCipher engine for canonical memory: "
                f"{cipher_version!r}"
            )
        if str(sqlite_version or "").strip() != _EXPECTED_SQLITE_VERSION:
            raise MemoryDatabaseEncryptionError(
                "unexpected SQLite baseline in canonical memory SQLCipher runtime: "
                f"{sqlite_version!r}"
            )

    @staticmethod
    def _configure_connection(connection: Any) -> None:
        connection.execute("PRAGMA cipher_memory_security = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA secure_delete = ON")
        journal_mode = _scalar(connection, "PRAGMA journal_mode = WAL")
        if str(journal_mode or "").casefold() != "wal":
            raise MemoryDatabaseEncryptionError("canonical memory could not enter WAL mode")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 5000")

    def _discard_failed_new_database(self) -> None:
        cleanup_errors: list[Exception] = []
        for path in (
            self._database_path,
            Path(f"{self._database_path}-wal"),
            Path(f"{self._database_path}-shm"),
        ):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append(exc)
        try:
            self._key_store.discard_new()
        except MemoryDatabaseKeyError as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            raise MemoryDatabaseError(
                "failed to clean up an unsuccessful new memory database"
            ) from cleanup_errors[0]
