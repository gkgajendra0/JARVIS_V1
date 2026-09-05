from pathlib import Path

from tools.research import step4_memory_extraction_bakeoff as bakeoff

from jarvis.memory.candidates import MemoryExtractionProposal
from jarvis.memory.extractors import MEMORY_EXTRACTION_SYSTEM_PROMPT

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "tools" / "research" / "step4_memory_extraction_cases.json"
RESEARCH_REQUIREMENTS_PATH = (
    REPO_ROOT / "tools" / "research" / "requirements-step4-extraction.txt"
)
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def test_research_bakeoff_reuses_production_schema_and_prompt() -> None:
    assert bakeoff.MemoryExtractionProposal is MemoryExtractionProposal
    assert bakeoff.MEMORY_EXTRACTION_SYSTEM_PROMPT == MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "rationale" not in MemoryExtractionProposal.model_fields


def test_research_sdk_pins_match_direct_production_dependencies() -> None:
    production_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    research_requirements = {
        line.strip()
        for line in RESEARCH_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    for pinned_dependency in (
        "openai==2.54.0",
        "google-genai==2.22.0",
        "pydantic==2.13.5",
    ):
        assert f'"{pinned_dependency}"' in production_text
        assert pinned_dependency in research_requirements


def test_research_corpus_taxonomy_and_pre_provider_partition_match_runtime() -> None:
    cases = bakeoff._load_cases(CASES_PATH)

    bakeoff._validate_corpus_taxonomy(cases)
    partition = bakeoff._partition_cases(cases)

    provider_ids = {case["id"] for case in partition.provider_cases}
    non_user_ids = set(partition.non_user_case_ids)
    explicit_ids = set(partition.explicit_control_case_ids)

    assert {
        "assistant_claim",
        "web_poison",
        "email_poison",
        "old_document_current_conflict",
    } <= non_user_ids
    assert {
        "explicit_remember_en",
        "explicit_remember_hi",
        "explicit_remember_hinglish",
        "forget_explicit",
        "secret_request",
    } <= explicit_ids
    assert "correction" in provider_ids
    assert provider_ids.isdisjoint(non_user_ids)
    assert provider_ids.isdisjoint(explicit_ids)
    assert provider_ids


def test_local_secret_prefilter_blocks_non_explicit_secret_before_provider() -> None:
    synthetic = {
        "id": "implicit_secret",
        "language": "en",
        "input": "My password is hunter2.",
        "source_class": "direct_user",
        "expected": {
            "intent": "sensitive_reject_or_secret_store",
            "candidate_type": "secret",
            "durable_candidate": False,
        },
    }

    bakeoff._validate_corpus_taxonomy([synthetic])
    partition = bakeoff._partition_cases([synthetic])

    assert partition.provider_cases == ()
    assert partition.explicit_control_case_ids == ()
    assert partition.local_secret_case_ids == ("implicit_secret",)
