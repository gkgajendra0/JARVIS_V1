from pathlib import Path

from jarvis.memory.candidates import MemoryExtractionProposal
from jarvis.memory.extractors import MEMORY_EXTRACTION_SYSTEM_PROMPT
from tools.research import step4_memory_extraction_bakeoff as bakeoff


CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "research"
    / "step4_memory_extraction_cases.json"
)


def test_research_bakeoff_reuses_production_schema_and_prompt() -> None:
    assert bakeoff.MemoryExtractionProposal is MemoryExtractionProposal
    assert bakeoff.MEMORY_EXTRACTION_SYSTEM_PROMPT == MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "rationale" not in MemoryExtractionProposal.model_fields


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
        "correction",
        "forget_explicit",
        "secret_request",
    } <= explicit_ids
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
