from __future__ import annotations

import pathlib
import subprocess

from jarvis.incident_repair.code_index import (
    AST_GREP_VERSION,
    GRIMP_VERSION,
    DiagnosticCodeIndex,
    DiagnosticSymbol,
    ImportEdge,
    StructuralMatch,
    diagnostic_analyzer_requirements,
)
from jarvis.incident_repair.workspace import DiagnosticWorkspaceManager


class StaticRevisionResolver:
    def __init__(self, revision: str) -> None:
        self.revision = revision

    def revision_for(self, work_id: str) -> str:
        assert work_id
        return self.revision


class RecordingStructuralAnalyzer:
    version = "ast-test-1"

    def symbols(self, workspace, files, *, max_symbols):
        del max_symbols
        output = []
        for relative in files:
            if relative != "src/jarvis/demo.py":
                continue
            text = (workspace / relative).read_text(encoding="utf-8")
            if "old_symbol" in text:
                output.append(
                    DiagnosticSymbol(
                        path=relative,
                        name="old_symbol",
                        kind="function_definition",
                        line=1,
                        column=1,
                    )
                )
            if "new_symbol" in text:
                output.append(
                    DiagnosticSymbol(
                        path=relative,
                        name="new_symbol",
                        kind="function_definition",
                        line=1,
                        column=1,
                    )
                )
        return tuple(output)

    def search(self, workspace, files, *, pattern, max_results):
        output = []
        for relative in files:
            if relative != "src/jarvis/demo.py":
                continue
            text = (workspace / relative).read_text(encoding="utf-8")
            if pattern in text:
                output.append(
                    StructuralMatch(
                        path=relative,
                        kind="function_definition",
                        text=text.strip(),
                        start_line=1,
                        start_column=1,
                        end_line=2,
                        end_column=1,
                    )
                )
        return tuple(output[:max_results])


class StaticImportGraphAnalyzer:
    version = "grimp-test-1"

    def edges(self, workspace, *, max_edges):
        del workspace
        return (
            ImportEdge(
                importer="jarvis.demo",
                imported="jarvis.helper",
            ),
            ImportEdge(
                importer="jarvis.consumer",
                imported="jarvis.demo",
            ),
        )[:max_edges]


def _git(repo: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        shell=False,
    )
    return completed.stdout.strip()


def _repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "JARVIS Test")
    _git(repo, "config", "user.email", "jarvis-test@example.invalid")
    source = repo / "src" / "jarvis"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "helper.py").write_text(
        "def helper():\n    return 1\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "from .demo import old_symbol\n",
        encoding="utf-8",
    )
    (source / "demo.py").write_text(
        "def old_symbol():\n    return 'old'\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "old")
    old = _git(repo, "rev-parse", "HEAD").lower()

    (source / "demo.py").write_text(
        "def new_symbol():\n    return 'new'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "src/jarvis/demo.py")
    _git(repo, "commit", "-m", "new")
    new = _git(repo, "rev-parse", "HEAD").lower()
    return repo, old, new


def _index(tmp_path):
    repo, old, new = _repo(tmp_path)
    manager = DiagnosticWorkspaceManager(
        StaticRevisionResolver(old),
        repository_root=repo,
        workspace_root=tmp_path / "diagnostics",
    )
    manager.ensure("work-1")
    index = DiagnosticCodeIndex(
        manager,
        structural=RecordingStructuralAnalyzer(),
        import_graph=StaticImportGraphAnalyzer(),
    )
    return index, manager, old, new


def test_code_index_digest_is_deterministic_and_bound_to_pinned_revision(tmp_path) -> None:
    index, _, old, _ = _index(tmp_path)

    first = index.build("work-1")
    second = index.build("work-1")

    assert first == second
    assert first.revision == old
    assert first.digest == second.digest
    assert len(first.digest) == 64
    assert {item.name for item in first.symbols} == {"old_symbol"}
    assert {item.importer for item in first.import_edges} == {
        "jarvis.consumer",
        "jarvis.demo",
    }


def test_structural_search_reads_only_pinned_revision(tmp_path) -> None:
    index, _, _, _ = _index(tmp_path)

    old_matches = index.structural_search(
        "work-1",
        pattern="old_symbol",
    )
    new_matches = index.structural_search(
        "work-1",
        pattern="new_symbol",
    )

    assert len(old_matches) == 1
    assert old_matches[0].path == "src/jarvis/demo.py"
    assert new_matches == ()


def test_repository_map_ranks_incident_paths_and_obeys_bounds(tmp_path) -> None:
    index, _, _, _ = _index(tmp_path)
    snapshot = index.build("work-1")

    repo_map = index.repository_map(
        snapshot,
        terms=("old_symbol", "demo"),
        affected_paths=("src/jarvis/demo.py",),
        max_entries=2,
        max_chars=4000,
    )

    assert repo_map["revision"] == snapshot.revision
    assert repo_map["index_digest"] == snapshot.digest
    assert repo_map["entry_count"] <= 2
    assert repo_map["bounded_chars"] <= 4000
    assert repo_map["entries"][0]["path"] == "src/jarvis/demo.py"
    assert repo_map["entries"][0]["score"] > 0


def test_analyzer_requirements_are_exact_and_phase5_broker_compatible() -> None:
    requirements = diagnostic_analyzer_requirements(
        change_id="change-1",
        work_id="work-1",
    )

    assert [item.package_name for item in requirements] == [
        "ast-grep-py",
        "grimp",
    ]
    assert requirements[0].version_constraint == f"=={AST_GREP_VERSION}"
    assert requirements[1].version_constraint == f"=={GRIMP_VERSION}"
    assert all(
        item.registered_source_ids == ("pypi.public.v1",)
        for item in requirements
    )
    assert all(item.change_id == "change-1" for item in requirements)
    assert all(item.work_id == "work-1" for item in requirements)
