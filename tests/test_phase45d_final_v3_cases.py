from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "tools" / "research"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module() -> ModuleType:
    inserted = str(RESEARCH)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)
    _load(
        "step4_phase45d_final_v2_cases",
        RESEARCH / "step4_phase45d_final_v2_cases.py",
    )
    return _load(
        "step4_phase45d_final_v3_cases",
        RESEARCH / "step4_phase45d_final_v3_cases.py",
    )


def test_v3_counts_are_exact_and_balanced() -> None:
    module = _module()
    payload = module.build_payload()

    assert module.V3_CORPUS_SCHEMA_VERSION == 3
    assert len(payload["documents"]) == 510
    assert len(payload["queries"]) == 720

    for split in ("calibration", "validation"):
        rows = [item for item in payload["queries"] if item["split"] == split]
        releases = [item for item in rows if item["label"] == "release"]
        abstains = [item for item in rows if item["label"] == "abstain"]
        assert len(releases) == 180
        assert len(abstains) == 180
        assert Counter(item["language"] for item in releases) == {
            "en": 60,
            "hi": 60,
            "hinglish": 60,
        }
        assert Counter(item["language"] for item in abstains) == {
            "en": 60,
            "hi": 60,
            "hinglish": 60,
        }
        for category in module.ABSTAIN_CATEGORIES:
            category_rows = [
                item for item in abstains if item["category"] == category
            ]
            assert len(category_rows) == 15
            assert Counter(item["language"] for item in category_rows) == {
                "en": 5,
                "hi": 5,
                "hinglish": 5,
            }


def test_v3_is_fresh_against_v2_and_has_unique_ids() -> None:
    module = _module()
    payload = module.build_payload()
    old_payload = module.v2_cases.build_payload()

    case_ids = [item["case_id"] for item in payload["queries"]]
    query_texts = [item["query"] for item in payload["queries"]]
    old_queries = {item["query"] for item in old_payload["queries"]}
    memory_ids = [item["memory_id"] for item in payload["documents"]]
    replacement_ids = [
        item["replacement_memory_id"]
        for item in payload["documents"]
        if item.get("mode") == "historical_transition"
    ]

    assert len(case_ids) == len(set(case_ids))
    assert len(query_texts) == len(set(query_texts))
    assert not old_queries.intersection(query_texts)
    assert len(memory_ids + replacement_ids) == len(set(memory_ids + replacement_ids))
    assert all(value.startswith("v3_") for value in case_ids)
    assert all(value.startswith("v3_") for value in memory_ids)


def test_v3_release_targets_are_current_and_split_profiles_are_disjoint() -> None:
    module = _module()
    payload = module.build_payload()
    document_by_id = {item["memory_id"]: item for item in payload["documents"]}

    release_rows = [item for item in payload["queries"] if item["label"] == "release"]
    for item in release_rows:
        expected = item["expected_memory_id"]
        assert expected in document_by_id
        assert document_by_id[expected]["mode"] == "current"

    calibration_profiles = {
        fact.profile for fact in module.CURRENT_FACTS if fact.split == "calibration"
    }
    validation_profiles = {
        fact.profile for fact in module.CURRENT_FACTS if fact.split == "validation"
    }
    assert len(calibration_profiles) == 15
    assert len(validation_profiles) == 15
    assert calibration_profiles.isdisjoint(validation_profiles)


def test_v3_security_boundaries_are_synthetic_and_never_positive_targets() -> None:
    module = _module()
    payload = module.build_payload()

    release_targets = {
        item["expected_memory_id"]
        for item in payload["queries"]
        if item["label"] == "release"
    }
    secret_docs = [item for item in payload["documents"] if item["mode"] == "secret"]
    assert len(secret_docs) == 30
    assert all(item["memory_id"] not in release_targets for item in secret_docs)
    assert all("Synthetic V3" in item["text"] for item in secret_docs)
    assert payload["metadata"]["real_secrets"] is False


def test_v3_payload_hash_is_deterministic() -> None:
    module = _module()
    first = module.payload_sha256()
    second = module.payload_sha256(module.build_payload())

    assert first == second
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)
