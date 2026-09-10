"""Governed persistent local-file actions for JARVIS Hands H2."""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import tempfile
import time
from typing import Any

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.local_reads import default_project_root
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

_MAX_TEXT_BYTES = 1_000_000
_MAX_COPY_BYTES = 250_000_000
_SENSITIVE_EXACT = {
    ".env",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "secrets",
    "secrets.json",
}
_SENSITIVE_SUFFIXES = {".kdbx", ".key", ".p12", ".pem", ".pfx"}
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


class LocalWriteValidationError(ValueError):
    """Raised before any persistent write when a target is outside policy."""


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _is_sensitive_name(name: str) -> bool:
    candidate = str(name).casefold()
    if candidate in _SENSITIVE_EXACT:
        return True
    if candidate.startswith(".env"):
        return True
    if candidate.startswith(("credentials", "secrets")):
        return True
    return pathlib.Path(candidate).suffix in _SENSITIVE_SUFFIXES


def _parse_extra_roots(raw: str | None) -> dict[str, pathlib.Path]:
    roots: dict[str, pathlib.Path] = {}
    if not raw:
        return roots
    for item in raw.split(";"):
        entry = item.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise LocalWriteValidationError(
                "JARVIS_LOCAL_WRITE_ROOTS entries must use alias=path"
            )
        alias, value = entry.split("=", 1)
        normalized = alias.strip().casefold()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", normalized):
            raise LocalWriteValidationError("invalid local write root alias")
        roots[normalized] = pathlib.Path(value.strip()).expanduser().resolve()
    return roots


def _default_write_roots() -> dict[str, pathlib.Path]:
    home = pathlib.Path.home().resolve()
    candidates = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
    }
    return {alias: path.resolve() for alias, path in candidates.items() if path.is_dir()}


def _is_within(candidate: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


class ApprovedWriteRootPolicy:
    """Separate write roots; the JARVIS source tree is never writable by default."""

    def __init__(
        self,
        *,
        roots: dict[str, str | pathlib.Path] | None = None,
        jarvis_root: str | pathlib.Path | None = None,
        include_user_defaults: bool = True,
    ) -> None:
        configured: dict[str, pathlib.Path] = (
            _default_write_roots() if include_user_defaults else {}
        )
        configured.update(_parse_extra_roots(os.getenv("JARVIS_LOCAL_WRITE_ROOTS")))
        for alias, value in (roots or {}).items():
            normalized = str(alias).strip().casefold()
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", normalized):
                raise LocalWriteValidationError("invalid local write root alias")
            configured[normalized] = pathlib.Path(value).expanduser().resolve()

        protected = pathlib.Path(jarvis_root or default_project_root()).resolve()
        if not configured:
            raise LocalWriteValidationError("no approved local write roots are configured")
        for alias, root in configured.items():
            if not root.is_dir():
                raise LocalWriteValidationError(
                    f"approved local write root does not exist: {alias}"
                )
            if _is_within(root, protected) or _is_within(protected, root):
                raise LocalWriteValidationError(
                    "JARVIS project/source tree cannot be an ordinary local write root"
                )
        self._roots = configured

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._roots))

    def root(self, alias: str) -> pathlib.Path:
        normalized = str(alias).strip().casefold()
        try:
            return self._roots[normalized]
        except KeyError as exc:
            raise LocalWriteValidationError("unknown approved local write root") from exc

    def resolve(
        self,
        alias: str,
        relative_path: str,
        *,
        allow_root: bool = False,
    ) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
        root = self.root(alias)
        raw = str(relative_path or "").strip()
        pure = pathlib.PurePath(raw)
        if pure.is_absolute() or pathlib.PureWindowsPath(raw).is_absolute():
            raise LocalWriteValidationError("absolute local write paths are not allowed")
        if any(part == ".." for part in pure.parts):
            raise LocalWriteValidationError("parent path traversal is not allowed")
        if any(part.casefold() == ".git" for part in pure.parts):
            raise LocalWriteValidationError("Git internals are blocked from local write actions")
        if any(_is_sensitive_name(part) for part in pure.parts):
            raise LocalWriteValidationError("credential/secret-like paths are blocked")

        target = (root / raw).resolve(strict=False)
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise LocalWriteValidationError("local write target escapes approved root") from exc
        if not allow_root and not relative.parts:
            raise LocalWriteValidationError("write action requires a path below the root")

        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise LocalWriteValidationError("symlink paths are blocked from local writes")
        return root, target, relative


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".jarvis-", suffix=".tmp", dir=path.parent)
    temp = pathlib.Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _preview(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text).split())
    if len(compact) > limit:
        compact = compact[: limit - 3] + "..."
    return compact


class LocalFileWriteExecutor:
    capability_key = "local:files.write"
    operations = (
        "append_text_file",
        "copy_path",
        "create_text_file",
        "make_directory",
        "move_path",
        "rename_path",
        "replace_text_file",
        "trash_path",
    )

    def __init__(self, roots: ApprovedWriteRootPolicy | None = None) -> None:
        self.roots = roots or ApprovedWriteRootPolicy()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="files.write",
            source_id="local",
            kind=CapabilityKind.NATIVE_API,
            name="Governed local file writes",
            description=(
                "Persistent file and folder actions inside separate approved user write roots; "
                "the JARVIS source tree is excluded."
            ),
            operations=list(self.operations),
            metadata={"root_aliases": list(self.roots.aliases), "delete_mode": "recycle_bin"},
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise LocalWriteValidationError("unsupported local file write operation")
        params = dict(request.parameters)
        operation = request.operation
        payload: dict[str, Any] = {}
        summary: str

        if operation in {"copy_path", "move_path"}:
            source_root = str(params.get("source_root") or "").strip().casefold()
            source_path = str(params.get("source_path") or "").strip()
            dest_root = str(params.get("dest_root") or "").strip().casefold()
            dest_path = str(params.get("dest_path") or "").strip()
            _, source, source_rel = self.roots.resolve(source_root, source_path)
            _, dest, dest_rel = self.roots.resolve(dest_root, dest_path)
            overwrite = bool(params.get("overwrite", False))
            if source == dest:
                raise LocalWriteValidationError("source and destination must differ")
            payload.update(
                source=str(source),
                destination=str(dest),
                overwrite=overwrite,
            )
            params = {
                "source_root": source_root,
                "source_path": source_rel.as_posix(),
                "dest_root": dest_root,
                "dest_path": dest_rel.as_posix(),
                "overwrite": overwrite,
            }
            summary = (
                f"{operation.removesuffix('_path').replace('_', ' ').title()} "
                f"{source_root}:{source_rel.as_posix()} -> {dest_root}:{dest_rel.as_posix()}"
            )
        elif operation == "rename_path":
            root_alias = str(params.get("root") or "").strip().casefold()
            path = str(params.get("path") or "").strip()
            new_path = str(params.get("new_path") or "").strip()
            _, source, source_rel = self.roots.resolve(root_alias, path)
            _, dest, dest_rel = self.roots.resolve(root_alias, new_path)
            overwrite = bool(params.get("overwrite", False))
            if source == dest:
                raise LocalWriteValidationError("rename source and destination must differ")
            payload.update(source=str(source), destination=str(dest), overwrite=overwrite)
            params = {
                "root": root_alias,
                "path": source_rel.as_posix(),
                "new_path": dest_rel.as_posix(),
                "overwrite": overwrite,
            }
            summary = (
                f"Rename {root_alias}:{source_rel.as_posix()} -> {dest_rel.as_posix()}"
            )
        else:
            root_alias = str(params.get("root") or "").strip().casefold()
            path = str(params.get("path") or "").strip()
            _, target, relative = self.roots.resolve(root_alias, path)
            payload["target"] = str(target)
            params = {"root": root_alias, "path": relative.as_posix()}
            if operation in {"create_text_file", "replace_text_file", "append_text_file"}:
                text = str(request.parameters.get("text") or "")
                encoded = text.encode("utf-8")
                if not text or len(encoded) > _MAX_TEXT_BYTES:
                    raise LocalWriteValidationError("text payload is empty or exceeds size limit")
                if _contains_secret(text):
                    raise LocalWriteValidationError("credential-like text is blocked from file writes")
                params["text"] = text
                payload["text"] = text
                summary = (
                    f"{operation.replace('_', ' ')} {root_alias}:{relative.as_posix()} "
                    f"with {_preview(text)!r} ({len(text)} chars)"
                )
            elif operation == "make_directory":
                summary = f"Create directory {root_alias}:{relative.as_posix()}"
            else:
                summary = f"Move to recycle bin {root_alias}:{relative.as_posix()}"

        attributes = ActionAttributes(
            persistent_write=True,
            destructive=operation == "trash_path",
        )
        return PreparedCapability(
            request=request,
            target={"domain": "files.write", "operation": operation},
            parameters=params,
            material_summary=summary,
            attributes=attributes,
            execution_payload=payload,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        operation = prepared.request.operation
        try:
            data = self._execute_operation(operation, prepared.execution_payload)
        except (LocalWriteValidationError, OSError, shutil.Error) as exc:
            return self._result(
                prepared,
                CapabilityStatus.FAILED,
                started,
                reason=str(exc),
            )
        return self._result(
            prepared,
            CapabilityStatus.SUCCEEDED,
            started,
            data={**data, "verification_passed": True},
            provenance=("pathlib/shutil atomic filesystem operations",),
        )

    def _execute_operation(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation in {"copy_path", "move_path", "rename_path"}:
            source = pathlib.Path(str(payload["source"]))
            dest = pathlib.Path(str(payload["destination"]))
            overwrite = bool(payload["overwrite"])
            if not source.exists() or source.is_symlink():
                raise LocalWriteValidationError("source does not exist or is a symlink")
            if source.is_file() and source.stat().st_size > _MAX_COPY_BYTES:
                raise LocalWriteValidationError("source exceeds bounded file-operation limit")
            if dest.exists() and not overwrite:
                raise LocalWriteValidationError("destination exists and overwrite was not explicit")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if operation == "copy_path":
                if source.is_dir():
                    if dest.exists():
                        raise LocalWriteValidationError("directory copy cannot overwrite a destination")
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)
                if not dest.exists():
                    raise OSError("copy verification failed")
                return {"destination_exists": True, "source_exists": True}
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(source), str(dest))
            if source.exists() or not dest.exists():
                raise OSError("move/rename verification failed")
            return {"destination_exists": True, "source_exists": False}

        target = pathlib.Path(str(payload["target"]))
        if operation == "make_directory":
            if target.exists():
                raise LocalWriteValidationError("directory target already exists")
            target.mkdir(parents=True, exist_ok=False)
            if not target.is_dir():
                raise OSError("directory creation verification failed")
            return {"directory_exists": True}

        if operation in {"create_text_file", "replace_text_file", "append_text_file"}:
            text = str(payload["text"])
            if operation == "create_text_file" and target.exists():
                raise LocalWriteValidationError("file already exists")
            if operation in {"replace_text_file", "append_text_file"} and not target.is_file():
                raise LocalWriteValidationError("target file does not exist")
            final_text = text
            if operation == "append_text_file":
                if target.stat().st_size > _MAX_TEXT_BYTES:
                    raise LocalWriteValidationError("existing text file exceeds append limit")
                existing = target.read_text(encoding="utf-8")
                if len(existing.encode("utf-8")) + len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
                    raise LocalWriteValidationError("appended file would exceed text size limit")
                final_text = existing + text
            expected = _sha256_bytes(final_text.encode("utf-8"))
            _atomic_write_text(target, final_text)
            if not target.is_file() or _sha256_file(target) != expected:
                raise OSError("post-write content verification failed")
            return {
                "path_exists": True,
                "size_bytes": target.stat().st_size,
                "sha256": expected,
            }

        if operation == "trash_path":
            if not target.exists() or target.is_symlink():
                raise LocalWriteValidationError("trash target does not exist or is a symlink")
            try:
                from send2trash import send2trash
            except ImportError as exc:
                raise LocalWriteValidationError(
                    "recoverable deletion requires the jarvis[hands-files] extra"
                ) from exc
            send2trash(str(target))
            if target.exists():
                raise OSError("recycle-bin move verification failed")
            return {"original_path_exists": False, "recovery": "recycle_bin"}

        raise LocalWriteValidationError("unsupported prepared file operation")

    @staticmethod
    def _result(
        prepared: PreparedCapability,
        status: CapabilityStatus,
        started: float,
        *,
        data: dict[str, Any] | None = None,
        reason: str | None = None,
        provenance: tuple[str, ...] = (),
    ) -> CapabilityResult:
        return CapabilityResult(
            status=status,
            capability_key=prepared.request.capability_key,
            operation=prepared.request.operation,
            data=data or {},
            reason=reason,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
            provenance=provenance,
        )
