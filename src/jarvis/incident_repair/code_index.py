"""Mature structural/code-graph adapters and deterministic Phase-6 repository map."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import (
    DependencyEcosystem,
    DependencyRequirement,
)
from jarvis.work.brain import BrainAction
from jarvis.work.development import _contains_secret, _is_sensitive
from jarvis.work.models import WorkItem, WorkType

from .workspace import (
    DiagnosticWorkspaceError,
    DiagnosticWorkspaceManager,
)

AST_GREP_PACKAGE = "ast-grep-py"
AST_GREP_VERSION = "0.44.1"
GRIMP_PACKAGE = "grimp"
GRIMP_VERSION = "3.17"
_MAX_SOURCE_BYTES = 1_000_000
_MAX_INDEX_FILES = 1000
_MAX_SYMBOLS = 3000
_MAX_IMPORT_EDGES = 5000
_MAX_STRUCTURAL_RESULTS = 100
_MAX_REPO_MAP_ENTRIES = 50
_MAX_REPO_MAP_CHARS = 24_000

_SYMBOL_LINE = re.compile(
    r"^\s*(?:(?:async\s+)?def\s+(?P<function>[A-Za-z_][A-Za-z0-9_]*)"
    r"|class\s+(?P<class>[A-Za-z_][A-Za-z0-9_]*))"
)
_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}")


def diagnostic_analyzer_requirements(
    *,
    change_id: str | None = None,
    work_id: str | None = None,
) -> tuple[DependencyRequirement, ...]:
    """Exact analyzer requirements for Phase-5 DependencyBroker provisioning."""

    return (
        DependencyRequirement(
            requirement_id="phase6.ast-grep-py.v1",
            ecosystem=DependencyEcosystem.PYTHON,
            package_name=AST_GREP_PACKAGE,
            version_constraint=f"=={AST_GREP_VERSION}",
            purpose="Phase-6 syntax-aware read-only structural source search",
            registered_source_ids=("pypi.public.v1",),
            change_id=change_id,
            work_id=work_id,
        ),
        DependencyRequirement(
            requirement_id="phase6.grimp.v1",
            ecosystem=DependencyEcosystem.PYTHON,
            package_name=GRIMP_PACKAGE,
            version_constraint=f"=={GRIMP_VERSION}",
            purpose="Phase-6 read-only Python import/dependency graph",
            registered_source_ids=("pypi.public.v1",),
            change_id=change_id,
            work_id=work_id,
        ),
    )


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _safe_source_file(path: pathlib.Path, workspace: pathlib.Path) -> bool:
    try:
        relative = path.relative_to(workspace)
    except ValueError:
        return False
    return (
        path.is_file()
        and not path.is_symlink()
        and not _is_sensitive(pathlib.PurePosixPath(relative.as_posix()))
        and path.stat().st_size <= _MAX_SOURCE_BYTES
    )


@dataclass(frozen=True, slots=True)
class DiagnosticSymbol:
    path: str
    name: str
    kind: str
    line: int
    column: int

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True, slots=True)
class StructuralMatch:
    path: str
    kind: str
    text: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "text": self.text,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass(frozen=True, slots=True)
class ImportEdge:
    importer: str
    imported: str

    def to_payload(self) -> dict[str, str]:
        return {
            "importer": self.importer,
            "imported": self.imported,
        }


@dataclass(frozen=True, slots=True)
class IndexedSourceFile:
    path: str
    size_bytes: int
    sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCodeIndexSnapshot:
    revision: str
    files: tuple[IndexedSourceFile, ...]
    symbols: tuple[DiagnosticSymbol, ...]
    import_edges: tuple[ImportEdge, ...]
    ast_grep_version: str | None
    grimp_version: str | None
    digest: str

    def to_payload(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "files": [item.to_payload() for item in self.files],
            "symbols": [item.to_payload() for item in self.symbols],
            "import_edges": [item.to_payload() for item in self.import_edges],
            "ast_grep_version": self.ast_grep_version,
            "grimp_version": self.grimp_version,
            "digest": self.digest,
        }


class StructuralAnalyzer(Protocol):
    @property
    def version(self) -> str | None: ...

    def symbols(
        self,
        workspace: pathlib.Path,
        files: tuple[str, ...],
        *,
        max_symbols: int,
    ) -> tuple[DiagnosticSymbol, ...]: ...

    def search(
        self,
        workspace: pathlib.Path,
        files: tuple[str, ...],
        *,
        pattern: str,
        max_results: int,
    ) -> tuple[StructuralMatch, ...]: ...


class ImportGraphAnalyzer(Protocol):
    @property
    def version(self) -> str | None: ...

    def edges(
        self,
        workspace: pathlib.Path,
        *,
        max_edges: int,
    ) -> tuple[ImportEdge, ...]: ...


class AstGrepStructuralAnalyzer:
    """Thin adapter over ast-grep-py; no custom parser fallback is implemented."""

    @property
    def version(self) -> str | None:
        return _package_version(AST_GREP_PACKAGE)

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("ast_grep_py") is not None

    @staticmethod
    def _root(text: str):
        module = importlib.import_module("ast_grep_py")
        return module.SgRoot(text, "python").root()

    def symbols(
        self,
        workspace: pathlib.Path,
        files: tuple[str, ...],
        *,
        max_symbols: int,
    ) -> tuple[DiagnosticSymbol, ...]:
        if not self.available():
            return ()
        limit = max(1, min(int(max_symbols), _MAX_SYMBOLS))
        output: list[DiagnosticSymbol] = []
        for relative in files:
            if len(output) >= limit:
                break
            if pathlib.PurePosixPath(relative).suffix.casefold() != ".py":
                continue
            path = (workspace / relative).resolve(strict=False)
            if not _safe_source_file(path, workspace):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if _contains_secret(text):
                continue
            try:
                root = self._root(text)
                nodes = [
                    *root.find_all(kind="class_definition"),
                    *root.find_all(kind="function_definition"),
                ]
            except Exception:  # noqa: BLE001 - analyzer must not break diagnostics
                continue
            for node in nodes:
                first_line = node.text().splitlines()[0] if node.text() else ""
                match = _SYMBOL_LINE.match(first_line)
                if match is None:
                    continue
                name = match.group("function") or match.group("class")
                if not name:
                    continue
                rng = node.range()
                output.append(
                    DiagnosticSymbol(
                        path=relative,
                        name=name,
                        kind=node.kind(),
                        line=int(rng.start.line) + 1,
                        column=int(rng.start.column) + 1,
                    )
                )
                if len(output) >= limit:
                    break
        return tuple(
            sorted(
                output,
                key=lambda item: (
                    item.path,
                    item.line,
                    item.column,
                    item.kind,
                    item.name,
                ),
            )
        )

    def search(
        self,
        workspace: pathlib.Path,
        files: tuple[str, ...],
        *,
        pattern: str,
        max_results: int,
    ) -> tuple[StructuralMatch, ...]:
        if not self.available():
            return ()
        query = str(pattern or "").strip()
        if not query:
            raise DiagnosticWorkspaceError("structural search pattern is empty")
        limit = max(1, min(int(max_results), _MAX_STRUCTURAL_RESULTS))
        output: list[StructuralMatch] = []
        for relative in files:
            if len(output) >= limit:
                break
            if pathlib.PurePosixPath(relative).suffix.casefold() != ".py":
                continue
            path = (workspace / relative).resolve(strict=False)
            if not _safe_source_file(path, workspace):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if _contains_secret(text):
                continue
            try:
                root = self._root(text)
                nodes = root.find_all(pattern=query)
            except Exception:  # noqa: BLE001 - invalid/nonmatching pattern is bounded
                continue
            for node in nodes:
                snippet = node.text()
                if _contains_secret(snippet):
                    continue
                rng = node.range()
                output.append(
                    StructuralMatch(
                        path=relative,
                        kind=node.kind(),
                        text=snippet[:800],
                        start_line=int(rng.start.line) + 1,
                        start_column=int(rng.start.column) + 1,
                        end_line=int(rng.end.line) + 1,
                        end_column=int(rng.end.column) + 1,
                    )
                )
                if len(output) >= limit:
                    break
        return tuple(output)


_GRIMP_SCRIPT = r"""
import json
import pathlib
import sys

workspace_src = pathlib.Path(sys.argv[1]).resolve()
package_name = sys.argv[2]
limit = int(sys.argv[3])
sys.path.insert(0, str(workspace_src))

import grimp

graph = grimp.build_graph(
    package_name,
    include_external_packages=False,
    cache_dir=None,
)
rows = []
for importer in sorted(graph.modules):
    try:
        imported_modules = sorted(graph.find_modules_directly_imported_by(importer))
    except Exception:
        continue
    for imported in imported_modules:
        rows.append({"importer": importer, "imported": imported})
        if len(rows) >= limit:
            break
    if len(rows) >= limit:
        break
print(json.dumps(rows, sort_keys=True, separators=(",", ":")))
"""


class GrimpImportGraphAnalyzer:
    """Isolated subprocess adapter over Grimp's read-only ImportGraph API."""

    @property
    def version(self) -> str | None:
        return _package_version(GRIMP_PACKAGE)

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("grimp") is not None

    def edges(
        self,
        workspace: pathlib.Path,
        *,
        max_edges: int,
    ) -> tuple[ImportEdge, ...]:
        if not self.available():
            return ()
        source_root = (workspace / "src").resolve()
        package_root = source_root / "jarvis"
        if not package_root.is_dir() or package_root.is_symlink():
            return ()
        limit = max(1, min(int(max_edges), _MAX_IMPORT_EDGES))
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    _GRIMP_SCRIPT,
                    str(source_root),
                    "jarvis",
                    str(limit),
                ],
                cwd=workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60.0,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ()
        if completed.returncode != 0 or not completed.stdout.strip():
            return ()
        try:
            rows = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return ()
        output: list[ImportEdge] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            importer = str(row.get("importer") or "").strip()
            imported = str(row.get("imported") or "").strip()
            if not importer or not imported:
                continue
            output.append(ImportEdge(importer=importer, imported=imported))
            if len(output) >= limit:
                break
        return tuple(sorted(set(output), key=lambda item: (item.importer, item.imported)))


class DiagnosticCodeIndex:
    """Revision-bound code inventory backed by ast-grep-py and Grimp when provisioned."""

    def __init__(
        self,
        manager: DiagnosticWorkspaceManager,
        *,
        structural: StructuralAnalyzer | None = None,
        import_graph: ImportGraphAnalyzer | None = None,
    ) -> None:
        if not isinstance(manager, DiagnosticWorkspaceManager):
            raise TypeError("manager must be DiagnosticWorkspaceManager")
        self._manager = manager
        self._structural = structural or AstGrepStructuralAnalyzer()
        self._import_graph = import_graph or GrimpImportGraphAnalyzer()

    @property
    def analyzer_status(self) -> dict[str, object]:
        return {
            "ast_grep": {
                "package": AST_GREP_PACKAGE,
                "required_version": AST_GREP_VERSION,
                "active_version": self._structural.version,
                "available": self._structural.version is not None,
            },
            "grimp": {
                "package": GRIMP_PACKAGE,
                "required_version": GRIMP_VERSION,
                "active_version": self._import_graph.version,
                "available": self._import_graph.version is not None,
            },
        }

    def _files(
        self,
        work_id: str,
        *,
        max_files: int = _MAX_INDEX_FILES,
    ) -> tuple[str, ...]:
        return self._manager.tracked_files(
            work_id,
            max_results=max(1, min(int(max_files), _MAX_INDEX_FILES)),
        )

    def build(
        self,
        work_id: str,
        *,
        max_files: int = _MAX_INDEX_FILES,
        max_symbols: int = _MAX_SYMBOLS,
        max_edges: int = _MAX_IMPORT_EDGES,
    ) -> DiagnosticCodeIndexSnapshot:
        workspace = self._manager.assert_pristine(work_id)
        files = self._files(work_id, max_files=max_files)
        indexed_files: list[IndexedSourceFile] = []
        for relative in files:
            target = (workspace.path / relative).resolve(strict=False)
            if not _safe_source_file(target, workspace.path):
                continue
            try:
                data = target.read_bytes()
            except OSError:
                continue
            indexed_files.append(
                IndexedSourceFile(
                    path=relative,
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            )

        symbols = self._structural.symbols(
            workspace.path,
            tuple(item.path for item in indexed_files),
            max_symbols=max_symbols,
        )
        edges = self._import_graph.edges(
            workspace.path,
            max_edges=max_edges,
        )
        payload = {
            "revision": workspace.revision,
            "files": [item.to_payload() for item in indexed_files],
            "symbols": [item.to_payload() for item in symbols],
            "import_edges": [item.to_payload() for item in edges],
            "ast_grep_version": self._structural.version,
            "grimp_version": self._import_graph.version,
        }
        digest = canonical_digest(payload)
        self._manager.assert_pristine(work_id)
        return DiagnosticCodeIndexSnapshot(
            revision=workspace.revision,
            files=tuple(indexed_files),
            symbols=symbols,
            import_edges=edges,
            ast_grep_version=self._structural.version,
            grimp_version=self._import_graph.version,
            digest=digest,
        )

    def structural_search(
        self,
        work_id: str,
        *,
        pattern: str,
        max_results: int = 20,
    ) -> tuple[StructuralMatch, ...]:
        workspace = self._manager.assert_pristine(work_id)
        files = self._files(work_id)
        output = self._structural.search(
            workspace.path,
            files,
            pattern=pattern,
            max_results=max_results,
        )
        self._manager.assert_pristine(work_id)
        return output

    def repository_map(
        self,
        snapshot: DiagnosticCodeIndexSnapshot,
        *,
        terms: tuple[str, ...] = (),
        affected_paths: tuple[str, ...] = (),
        max_entries: int = 30,
        max_chars: int = _MAX_REPO_MAP_CHARS,
    ) -> dict[str, object]:
        normalized_terms = tuple(
            sorted(
                {
                    token.casefold()
                    for value in terms[:20]
                    for token in _TOKEN.findall(str(value))
                }
            )
        )
        path_hints = {
            pathlib.PurePosixPath(str(path)).as_posix().casefold()
            for path in affected_paths[:20]
            if str(path).strip()
        }
        symbols_by_path: dict[str, list[DiagnosticSymbol]] = {}
        for symbol in snapshot.symbols:
            symbols_by_path.setdefault(symbol.path, []).append(symbol)

        degree: dict[str, int] = {}
        for edge in snapshot.import_edges:
            degree[edge.importer] = degree.get(edge.importer, 0) + 1
            degree[edge.imported] = degree.get(edge.imported, 0) + 1

        rows: list[tuple[float, str, dict[str, object]]] = []
        for file in snapshot.files:
            path_folded = file.path.casefold()
            path_tokens = set(_TOKEN.findall(path_folded))
            score = 0.0
            if path_folded in path_hints:
                score += 20.0
            for hint in path_hints:
                if hint and (hint in path_folded or path_folded in hint):
                    score += 8.0
            score += 3.0 * sum(
                1 for term in normalized_terms if term in path_tokens or term in path_folded
            )
            file_symbols = symbols_by_path.get(file.path, [])
            symbol_names = {item.name.casefold() for item in file_symbols}
            score += 5.0 * sum(
                1
                for term in normalized_terms
                if any(term in name for name in symbol_names)
            )

            module = None
            pure = pathlib.PurePosixPath(file.path)
            if (
                len(pure.parts) >= 3
                and pure.parts[0] == "src"
                and pure.parts[1] == "jarvis"
                and pure.suffix == ".py"
            ):
                module_parts = list(pure.with_suffix("").parts[1:])
                if module_parts[-1] == "__init__":
                    module_parts = module_parts[:-1]
                module = ".".join(module_parts)
                score += min(float(degree.get(module, 0)), 8.0) * 0.5

            payload = {
                "path": file.path,
                "score": round(score, 3),
                "symbols": [
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "line": item.line,
                    }
                    for item in file_symbols[:12]
                ],
                "module": module,
                "import_degree": 0 if module is None else degree.get(module, 0),
            }
            rows.append((score, file.path, payload))

        rows.sort(key=lambda item: (-item[0], item[1]))
        limit = max(1, min(int(max_entries), _MAX_REPO_MAP_ENTRIES))
        selected: list[dict[str, object]] = []
        used_chars = 0
        char_limit = max(1000, min(int(max_chars), _MAX_REPO_MAP_CHARS))
        for _, _, payload in rows[:limit]:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if selected and used_chars + len(encoded) > char_limit:
                break
            selected.append(payload)
            used_chars += len(encoded)

        return {
            "revision": snapshot.revision,
            "index_digest": snapshot.digest,
            "entries": selected,
            "entry_count": len(selected),
            "bounded_chars": used_chars,
            "analyzers": {
                "ast_grep_version": snapshot.ast_grep_version,
                "grimp_version": snapshot.grimp_version,
            },
        }


class DiagnosticCodeIndexExecutor:
    descriptor = BrainAction(
        name="diag_code_index",
        description=(
            "Build a deterministic revision-bound source inventory using the approved "
            "ast-grep/Grimp analyzers when provisioned."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, index: DiagnosticCodeIndex) -> None:
        self._index = index

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        snapshot = await asyncio.to_thread(self._index.build, work.work_id)
        return {
            "revision": snapshot.revision,
            "index_digest": snapshot.digest,
            "file_count": len(snapshot.files),
            "symbol_count": len(snapshot.symbols),
            "import_edge_count": len(snapshot.import_edges),
            "analyzers": self._index.analyzer_status,
        }


class DiagnosticStructuralSearchExecutor:
    descriptor = BrainAction(
        name="diag_structural_search",
        description=(
            "Run bounded ast-grep-py syntax-aware search inside the pinned revision. "
            "No text-parser fallback is used when ast-grep is unavailable."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1, "maxLength": 500},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, index: DiagnosticCodeIndex) -> None:
        self._index = index

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        pattern = str(parameters.get("pattern") or "").strip()
        limit = int(parameters.get("max_results", 20))
        if self._index.analyzer_status["ast_grep"]["available"] is not True:
            return {
                "available": False,
                "reason": "ast_grep_not_provisioned",
                "requirement": diagnostic_analyzer_requirements(work_id=work.work_id)[
                    0
                ].requirement_id,
                "matches": [],
            }
        matches = await asyncio.to_thread(
            self._index.structural_search,
            work.work_id,
            pattern=pattern,
            max_results=limit,
        )
        return {
            "available": True,
            "pattern": pattern,
            "matches": [item.to_payload() for item in matches],
            "max_results": max(1, min(limit, _MAX_STRUCTURAL_RESULTS)),
        }


class DiagnosticRepositoryMapExecutor:
    descriptor = BrainAction(
        name="diag_repo_map",
        description=(
            "Build an incident-ranked bounded repository map from revision-bound "
            "file/symbol/import evidence."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "terms": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    "maxItems": 20,
                },
                "affected_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 20,
                },
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, index: DiagnosticCodeIndex) -> None:
        self._index = index

    def resource_keys(self, work: WorkItem, parameters: dict[str, Any]) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        raw_terms = parameters.get("terms") or []
        raw_paths = parameters.get("affected_paths") or []
        if not isinstance(raw_terms, list) or not isinstance(raw_paths, list):
            raise DiagnosticWorkspaceError(
                "repository-map terms and paths must be arrays"
            )
        snapshot = await asyncio.to_thread(self._index.build, work.work_id)
        return self._index.repository_map(
            snapshot,
            terms=tuple(str(item) for item in raw_terms),
            affected_paths=tuple(str(item) for item in raw_paths),
            max_entries=int(parameters.get("max_entries", 30)),
        )


def build_diagnostic_code_intelligence_executors(
    index: DiagnosticCodeIndex,
) -> tuple[object, ...]:
    return (
        DiagnosticCodeIndexExecutor(index),
        DiagnosticStructuralSearchExecutor(index),
        DiagnosticRepositoryMapExecutor(index),
    )
