"""Approved-root, read-only local project and document intelligence."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
from typing import Any

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.document_reader import DocumentReaderError, MarkItDownSidecar
from jarvis.capabilities.execution import (
    CapabilityExecutionError,
    PreparedCapability,
)
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)

_MAX_TEXT_BYTES = 1_000_000
_MAX_DOCUMENT_BYTES = 25_000_000
_MAX_RETURN_CHARS = 40_000
_MAX_SEARCH_RESULTS = 50
_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".pptx", ".xls", ".xlsx"}
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
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)


class LocalReadValidationError(ValueError):
    pass


def default_project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _parse_extra_roots(raw: str | None) -> dict[str, pathlib.Path]:
    roots: dict[str, pathlib.Path] = {}
    if not raw:
        return roots
    for item in raw.split(";"):
        entry = item.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise LocalReadValidationError(
                "JARVIS_LOCAL_READ_ROOTS entries must use alias=path"
            )
        alias, value = entry.split("=", 1)
        normalized_alias = alias.strip().casefold()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", normalized_alias):
            raise LocalReadValidationError("invalid local read root alias")
        roots[normalized_alias] = pathlib.Path(value.strip()).expanduser().resolve()
    return roots


def _is_sensitive(path: pathlib.Path) -> bool:
    name = path.name.casefold()
    if name in _SENSITIVE_EXACT:
        return True
    if name.startswith(".env.") and not name.endswith(
        (".example", ".sample", ".template")
    ):
        return True
    if name.startswith(("credentials", "secrets")):
        return True
    return path.suffix.casefold() in _SENSITIVE_SUFFIXES


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _bounded_text(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_RETURN_CHARS:
        return text, False
    return text[:_MAX_RETURN_CHARS], True


def _path_hash(relative: pathlib.Path) -> str:
    return hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16]


class ApprovedRootPolicy:
    """Resolve only relative paths that remain inside explicitly approved roots."""

    def __init__(
        self,
        *,
        project_root: str | pathlib.Path | None = None,
        extra_roots: dict[str, str | pathlib.Path] | None = None,
    ) -> None:
        project = pathlib.Path(project_root or default_project_root()).resolve()
        roots: dict[str, pathlib.Path] = {"project": project}
        roots.update(_parse_extra_roots(os.getenv("JARVIS_LOCAL_READ_ROOTS")))
        for alias, value in (extra_roots or {}).items():
            normalized_alias = str(alias).strip().casefold()
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", normalized_alias):
                raise LocalReadValidationError("invalid local read root alias")
            roots[normalized_alias] = pathlib.Path(value).expanduser().resolve()
        for alias, root in roots.items():
            if not root.is_dir():
                raise LocalReadValidationError(
                    f"approved local read root does not exist: {alias}"
                )
        self._roots = roots

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._roots))

    def root(self, alias: str) -> pathlib.Path:
        normalized = str(alias or "project").strip().casefold()
        try:
            return self._roots[normalized]
        except KeyError as exc:
            raise LocalReadValidationError("unknown approved local read root") from exc

    def resolve(
        self,
        alias: str,
        relative_path: str = "",
    ) -> tuple[pathlib.Path, pathlib.Path]:
        root = self.root(alias)
        raw = str(relative_path or "").strip()
        candidate = pathlib.PurePath(raw)
        if candidate.is_absolute() or pathlib.PureWindowsPath(raw).is_absolute():
            raise LocalReadValidationError("absolute local read paths are not allowed")
        if any(part == ".." for part in candidate.parts):
            raise LocalReadValidationError("parent path traversal is not allowed")
        target = (root / raw).resolve()
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise LocalReadValidationError(
                "local read target escapes approved root"
            ) from exc
        if ".git" in {part.casefold() for part in relative.parts}:
            raise LocalReadValidationError(
                "Git internals are not readable through Step 7"
            )
        if _is_sensitive(relative):
            raise LocalReadValidationError(
                "sensitive credential/secret path is blocked"
            )
        return root, target


class LocalProjectReadExecutor:
    capability_key = "local:project.read"
    operations = (
        "file_info",
        "list_directory",
        "list_project_files",
        "read_document",
        "read_file",
        "search_project",
    )

    def __init__(
        self,
        roots: ApprovedRootPolicy | None = None,
        document_reader: MarkItDownSidecar | None = None,
    ) -> None:
        self.roots = roots or ApprovedRootPolicy()
        self._document_reader = document_reader or MarkItDownSidecar()

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor.create(
            capability_id="project.read",
            source_id="local",
            kind=CapabilityKind.LOCAL_READ,
            name="Approved local project and document reads",
            description=(
                "Bounded read-only access to approved roots with traversal, symlink, "
                "credential-path and secret-release protection."
            ),
            operations=list(self.operations),
            metadata={"root_aliases": list(self.roots.aliases)},
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise LocalReadValidationError("unsupported local project read operation")
        params = dict(request.parameters)
        root_alias = str(params.get("root") or "project").strip().casefold()
        relative_path = str(params.get("path") or "").strip()
        root, target = self.roots.resolve(root_alias, relative_path)
        if (
            request.operation in {"read_file", "read_document", "file_info"}
            and not relative_path
        ):
            raise LocalReadValidationError("this operation requires a relative path")
        if request.operation == "search_project":
            query = str(params.get("query") or "").strip()
            if not query:
                raise LocalReadValidationError("search_project requires a query")
            if len(query) > 300:
                raise LocalReadValidationError("search query is too long")
            params["query"] = query
        max_results = int(params.get("max_results", 20))
        if not 1 <= max_results <= _MAX_SEARCH_RESULTS:
            raise LocalReadValidationError(
                f"max_results must be between 1 and {_MAX_SEARCH_RESULTS}"
            )
        params["max_results"] = max_results
        params["root"] = root_alias
        relative = target.relative_to(root)
        params["path"] = relative.as_posix()
        return PreparedCapability(
            request=request,
            target={
                "root_alias": root_alias,
                "relative_path_hash": _path_hash(relative),
                "scope": request.operation,
            },
            parameters=params,
            material_summary=(
                f"Read approved local {root_alias} resource for {request.operation}: "
                f"{relative.as_posix() or '.'}"
            ),
            attributes=ActionAttributes(private_read=True),
            execution_payload={
                "root": str(root),
                "target": str(target),
                "relative": relative.as_posix(),
            },
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        operation = prepared.request.operation
        root = pathlib.Path(str(prepared.execution_payload["root"]))
        target = pathlib.Path(str(prepared.execution_payload["target"]))
        relative = str(prepared.execution_payload["relative"])
        try:
            if operation == "file_info":
                data, truncated, provenance = self._file_info(target, relative)
            elif operation == "list_directory":
                data, truncated, provenance = self._list_directory(
                    target, int(prepared.parameters["max_results"])
                )
            elif operation == "list_project_files":
                data, truncated, provenance = self._list_project_files(
                    root,
                    target,
                    int(prepared.parameters["max_results"]),
                )
            elif operation == "search_project":
                data, truncated, provenance = self._search_project(
                    root,
                    target,
                    str(prepared.parameters["query"]),
                    int(prepared.parameters["max_results"]),
                )
            elif operation == "read_file":
                data, truncated, provenance = self._read_text(target, relative)
            elif operation == "read_document":
                data, truncated, provenance = self._read_document(target, relative)
            else:
                raise CapabilityExecutionError("unsupported prepared operation")
        except (LocalReadValidationError, OSError, UnicodeError) as exc:
            return self._result(
                prepared,
                CapabilityStatus.INVALID,
                started,
                reason=str(exc),
            )
        except CapabilityExecutionError as exc:
            return self._result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
            )
        return self._result(
            prepared,
            CapabilityStatus.PARTIAL if truncated else CapabilityStatus.SUCCEEDED,
            started,
            data=data,
            truncated=truncated,
            provenance=provenance,
        )

    def _result(
        self,
        prepared: PreparedCapability,
        status: CapabilityStatus,
        started: float,
        *,
        data: dict[str, Any] | None = None,
        reason: str | None = None,
        truncated: bool = False,
        provenance: tuple[str, ...] = (),
    ) -> CapabilityResult:
        return CapabilityResult(
            status=status,
            capability_key=self.capability_key,
            operation=prepared.request.operation,
            data=data or {},
            reason=reason,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
            truncated=truncated,
            provenance=provenance,
        )

    @staticmethod
    def _assert_regular_file(
        target: pathlib.Path,
        max_bytes: int,
    ) -> os.stat_result:
        if not target.is_file():
            raise LocalReadValidationError("target is not a regular file")
        stat = target.stat()
        if stat.st_size > max_bytes:
            raise LocalReadValidationError("file exceeds Step-7 read size limit")
        return stat

    @staticmethod
    def _file_info(
        target: pathlib.Path,
        relative: str,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        if not target.exists():
            raise LocalReadValidationError("target does not exist")
        stat = target.stat()
        return (
            {
                "path": relative,
                "is_file": target.is_file(),
                "is_directory": target.is_dir(),
                "size_bytes": stat.st_size,
                "modified_epoch": stat.st_mtime,
                "suffix": target.suffix.casefold(),
            },
            False,
            ("pathlib",),
        )

    @staticmethod
    def _list_directory(
        target: pathlib.Path,
        max_results: int,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        if not target.is_dir():
            raise LocalReadValidationError("target is not a directory")
        entries: list[dict[str, str]] = []
        truncated = False
        for child in sorted(target.iterdir(), key=lambda item: item.name.casefold()):
            if child.name.startswith(".") or _is_sensitive(pathlib.Path(child.name)):
                continue
            if len(entries) >= max_results:
                truncated = True
                break
            entries.append(
                {
                    "name": child.name,
                    "kind": "directory" if child.is_dir() else "file",
                }
            )
        return {"entries": entries}, truncated, ("pathlib",)

    @staticmethod
    def _list_project_files(
        root: pathlib.Path,
        target: pathlib.Path,
        max_results: int,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        if not target.is_dir():
            raise LocalReadValidationError("target is not a directory")
        git = shutil.which("git")
        if git and (root / ".git").exists():
            completed = subprocess.run(
                [
                    git,
                    "-C",
                    str(root),
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                capture_output=True,
                timeout=8.0,
                check=False,
                shell=False,
            )
            if completed.returncode == 0:
                prefix = target.relative_to(root).as_posix().rstrip("/")
                names: list[str] = []
                for raw in completed.stdout.split(b"\0"):
                    if not raw:
                        continue
                    name = raw.decode("utf-8", errors="replace")
                    if prefix and not name.startswith(prefix + "/"):
                        continue
                    path = pathlib.PurePosixPath(name)
                    if any(
                        part.startswith(".") for part in path.parts
                    ) or _is_sensitive(pathlib.Path(path.name)):
                        continue
                    names.append(name)
                    if len(names) > max_results:
                        break
                return (
                    {"files": names[:max_results]},
                    len(names) > max_results,
                    ("git ls-files",),
                )
        names = []
        truncated = False
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts) or _is_sensitive(
                relative
            ):
                continue
            names.append(relative.as_posix())
            if len(names) >= max_results:
                truncated = True
                break
        return {"files": sorted(names)}, truncated, ("pathlib fallback",)

    @staticmethod
    def _search_project(
        root: pathlib.Path,
        target: pathlib.Path,
        query: str,
        max_results: int,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        if not target.is_dir():
            raise LocalReadValidationError("search target is not a directory")
        rg = shutil.which("rg")
        if rg:
            result = LocalProjectReadExecutor._search_with_ripgrep(
                rg,
                root,
                target,
                query,
                max_results,
            )
            if result is not None:
                return result
        return LocalProjectReadExecutor._search_with_python(
            root,
            target,
            query,
            max_results,
        )

    @staticmethod
    def _search_with_ripgrep(
        rg: str,
        root: pathlib.Path,
        target: pathlib.Path,
        query: str,
        max_results: int,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]] | None:
        completed = subprocess.run(
            [
                rg,
                "--json",
                "--fixed-strings",
                "--no-messages",
                "--max-filesize",
                "2M",
                query,
                str(target),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
            check=False,
            shell=False,
        )
        if completed.returncode not in {0, 1}:
            return None
        matches: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") != "match":
                continue
            data = item.get("data", {})
            path_text = str(data.get("path", {}).get("text", ""))
            try:
                relative = pathlib.Path(path_text).resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            if _is_sensitive(relative) or any(
                part.startswith(".") for part in relative.parts
            ):
                continue
            line_text = str(data.get("lines", {}).get("text", "")).strip()
            if _contains_secret(line_text):
                line_text = "[redacted: secret-like content]"
            matches.append(
                {
                    "path": relative.as_posix(),
                    "line": data.get("line_number"),
                    "text": line_text[:500],
                }
            )
            if len(matches) >= max_results:
                break
        return (
            {"query": query, "matches": matches},
            len(matches) >= max_results,
            ("ripgrep",),
        )

    @staticmethod
    def _search_with_python(
        root: pathlib.Path,
        target: pathlib.Path,
        query: str,
        max_results: int,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        matches: list[dict[str, Any]] = []
        for path in target.rglob("*"):
            if len(matches) >= max_results:
                break
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts) or _is_sensitive(
                relative
            ):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query.casefold() not in line.casefold():
                    continue
                snippet = (
                    "[redacted: secret-like content]"
                    if _contains_secret(line)
                    else line[:500]
                )
                matches.append(
                    {
                        "path": relative.as_posix(),
                        "line": line_number,
                        "text": snippet,
                    }
                )
                if len(matches) >= max_results:
                    break
        return (
            {"query": query, "matches": matches},
            len(matches) >= max_results,
            ("bounded Python search fallback",),
        )

    def _read_text(
        self,
        target: pathlib.Path,
        relative: str,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        self._assert_regular_file(target, _MAX_TEXT_BYTES)
        raw = target.read_bytes()
        if b"\x00" in raw[:8192]:
            raise LocalReadValidationError(
                "binary file requires a supported document reader"
            )
        text = raw.decode("utf-8")
        if _contains_secret(text):
            raise LocalReadValidationError(
                "secret-like content detected; release blocked"
            )
        text, truncated = _bounded_text(text)
        return {"path": relative, "text": text}, truncated, ("direct utf-8 read",)

    def _read_document(
        self,
        target: pathlib.Path,
        relative: str,
    ) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
        self._assert_regular_file(target, _MAX_DOCUMENT_BYTES)
        if target.suffix.casefold() not in _DOCUMENT_SUFFIXES:
            raise LocalReadValidationError(
                "read_document supports PDF, DOCX, PPTX, XLS and XLSX"
            )
        try:
            text, sidecar_truncated = self._document_reader.convert_local(target)
        except DocumentReaderError as exc:
            raise CapabilityExecutionError(str(exc)) from exc
        if _contains_secret(text):
            raise LocalReadValidationError(
                "secret-like content detected; release blocked"
            )
        text, local_truncated = _bounded_text(text)
        return (
            {"path": relative, "text": text},
            sidecar_truncated or local_truncated,
            ("Microsoft MarkItDown isolated sidecar",),
        )
