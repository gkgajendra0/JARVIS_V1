from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.authority.risk import RiskClassifier
from jarvis.authority.types import RiskClass
from jarvis.capabilities.document_edits import DocumentEditExecutor
from jarvis.capabilities.local_writes import (
    ApprovedWriteRootPolicy,
    LocalFileWriteExecutor,
    LocalWriteValidationError,
)
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus


def request(executor, operation: str, parameters: dict) -> CapabilityRequest:
    return CapabilityRequest(
        session_id="h2-test",
        capability_key=executor.capability_key,
        operation=operation,
        parameters=parameters,
    )


def roots(tmp_path: Path) -> ApprovedWriteRootPolicy:
    writable = tmp_path / "user-files"
    writable.mkdir()
    jarvis = tmp_path / "jarvis-source"
    jarvis.mkdir()
    return ApprovedWriteRootPolicy(
        roots={"test": writable},
        jarvis_root=jarvis,
        include_user_defaults=False,
    )


def test_write_policy_rejects_project_tree(tmp_path: Path) -> None:
    jarvis = tmp_path / "jarvis-source"
    jarvis.mkdir()

    with pytest.raises(LocalWriteValidationError, match="cannot be an ordinary"):
        ApprovedWriteRootPolicy(
            roots={"project": jarvis},
            jarvis_root=jarvis,
            include_user_defaults=False,
        )


def test_write_policy_blocks_traversal_and_secret_paths(tmp_path: Path) -> None:
    policy = roots(tmp_path)

    with pytest.raises(LocalWriteValidationError, match="traversal"):
        policy.resolve("test", "../escape.txt")
    with pytest.raises(LocalWriteValidationError, match="credential"):
        policy.resolve("test", ".env")


def test_create_replace_append_text_are_verified(tmp_path: Path) -> None:
    policy = roots(tmp_path)
    executor = LocalFileWriteExecutor(policy)

    created = executor.execute(
        executor.prepare(
            request(
                executor,
                "create_text_file",
                {"root": "test", "path": "note.txt", "text": "first"},
            )
        )
    )
    assert created.status is CapabilityStatus.SUCCEEDED
    assert created.data["verification_passed"] is True

    replaced = executor.execute(
        executor.prepare(
            request(
                executor,
                "replace_text_file",
                {"root": "test", "path": "note.txt", "text": "second"},
            )
        )
    )
    assert replaced.status is CapabilityStatus.SUCCEEDED

    appended = executor.execute(
        executor.prepare(
            request(
                executor,
                "append_text_file",
                {"root": "test", "path": "note.txt", "text": " + third"},
            )
        )
    )
    assert appended.status is CapabilityStatus.SUCCEEDED
    assert (policy.root("test") / "note.txt").read_text() == "second + third"


def test_persistent_file_write_has_canonical_persistent_risk(tmp_path: Path) -> None:
    executor = LocalFileWriteExecutor(roots(tmp_path))
    prepared = executor.prepare(
        request(
            executor,
            "create_text_file",
            {"root": "test", "path": "note.txt", "text": "hello"},
        )
    )

    assert prepared.attributes.persistent_write is True
    assert (
        RiskClassifier().classify(prepared.attributes).risk_class
        is RiskClass.PERSISTENT_OR_EXTERNAL
    )


def test_copy_and_rename_require_explicit_non_overwrite_by_default(
    tmp_path: Path,
) -> None:
    policy = roots(tmp_path)
    source = policy.root("test") / "a.txt"
    source.write_text("payload")
    executor = LocalFileWriteExecutor(policy)

    copied = executor.execute(
        executor.prepare(
            request(
                executor,
                "copy_path",
                {
                    "source_root": "test",
                    "source_path": "a.txt",
                    "dest_root": "test",
                    "dest_path": "b.txt",
                },
            )
        )
    )
    assert copied.status is CapabilityStatus.SUCCEEDED

    renamed = executor.execute(
        executor.prepare(
            request(
                executor,
                "rename_path",
                {"root": "test", "path": "b.txt", "new_path": "c.txt"},
            )
        )
    )
    assert renamed.status is CapabilityStatus.SUCCEEDED
    assert not (policy.root("test") / "b.txt").exists()
    assert (policy.root("test") / "c.txt").read_text() == "payload"


def test_create_and_edit_docx_with_real_semantic_library(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    policy = roots(tmp_path)
    executor = DocumentEditExecutor(policy)

    created = executor.execute(
        executor.prepare(
            request(
                executor,
                "create_docx",
                {"root": "test", "path": "notes.docx", "text": "First paragraph"},
            )
        )
    )
    assert created.status is CapabilityStatus.SUCCEEDED

    appended = executor.execute(
        executor.prepare(
            request(
                executor,
                "append_docx_paragraph",
                {"root": "test", "path": "notes.docx", "text": "Second paragraph"},
            )
        )
    )
    assert appended.status is CapabilityStatus.SUCCEEDED
    assert appended.data["verification_passed"] is True


def test_create_and_edit_xlsx_with_real_semantic_library(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    policy = roots(tmp_path)
    executor = DocumentEditExecutor(policy)

    created = executor.execute(
        executor.prepare(
            request(
                executor,
                "create_xlsx",
                {"root": "test", "path": "data.xlsx", "sheet": "Data"},
            )
        )
    )
    assert created.status is CapabilityStatus.SUCCEEDED

    edited = executor.execute(
        executor.prepare(
            request(
                executor,
                "set_xlsx_cell",
                {
                    "root": "test",
                    "path": "data.xlsx",
                    "sheet": "Data",
                    "cell": "B2",
                    "value": 42,
                },
            )
        )
    )
    assert edited.status is CapabilityStatus.SUCCEEDED
    assert edited.data["verification_passed"] is True
