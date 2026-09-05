from __future__ import annotations

from enum import Enum


class MemorySourceClass(str, Enum):
    OWNER_EXPLICIT = "owner_explicit"
    OWNER_DIRECT = "owner_direct"
    REFLECTION = "reflection"
    ASSISTANT_OUTPUT = "assistant_output"
    EXTERNAL_WEB = "external_web"
    EXTERNAL_EMAIL = "external_email"
    EXTERNAL_FILE = "external_file"
    RUNTIME_CONFIG = "runtime_config"
    REPOSITORY = "repository"
    TOOL = "tool"


class AuthorityClass(str, Enum):
    OWNER_EXPLICIT = "owner_explicit"
    OWNER_DIRECT = "owner_direct"
    AUTHORITATIVE_RUNTIME = "authoritative_runtime"
    VERIFIED = "verified"
    INFERRED = "inferred"
    UNTRUSTED = "untrusted"


class Sensitivity(str, Enum):
    STANDARD = "standard"
    PRIVATE = "private"
    LOCAL_ONLY = "local_only"
    SECRET_PROHIBITED = "secret_prohibited"


class AssertionState(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    EXPIRED = "expired"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class FreshnessClass(str, Enum):
    STABLE = "stable"
    CHANGEABLE = "changeable"
    TIME_SENSITIVE = "time_sensitive"


class ValueType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class MemoryOperationType(str, Enum):
    CREATE = "create"
    HISTORICAL_CHANGE = "historical_change"
    CORRECT = "correct"
    RETRACT = "retract"
    VERIFY = "verify"
    EXPIRE = "expire"
    FORGET = "forget"
