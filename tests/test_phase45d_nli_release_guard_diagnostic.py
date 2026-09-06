from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

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
        "step4_phase45d_nli_release_guard_diagnostic",
        RESEARCH / "step4_phase45d_nli_release_guard_diagnostic.py",
    )


def _source_artifact(module: ModuleType) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    correct_languages = ["en"] * 4 + ["hi"] * 3 + ["hinglish"] * 3
    for index, language in enumerate(correct_languages, start=1):
        memory_id = f"memory-{index}"
        cases.append(
            {
                "case_id": f"v2_val_p{index:04d}",
                "target_label": "release",
                "expected_memory_id": memory_id,
                "released_memory_id": memory_id,
                "final_disposition": "release",
                "language": language,
                "category": "direct" if language == "en" else "cross_lingual",
                "proposed_subject": "Aster",
                "proposed_predicate": "v2_project_region",
            }
        )
    false_languages = ["hi", "hinglish", "hinglish", "hi", "hinglish", "hinglish"]
    false_categories = [
        "near_miss",
        "near_miss",
        "adversarial_lexical",
        "negation",
        "negation",
        "unsupported_source",
    ]
    for offset, (language, category) in enumerate(
        zip(false_languages, false_categories, strict=True),
        start=1,
    ):
        cases.append(
            {
                "case_id": f"v2_val_a{offset:04d}",
                "target_label": "abstain",
                "expected_memory_id": None,
                "released_memory_id": f"false-memory-{offset}",
                "final_disposition": "release",
                "language": language,
                "category": category,
                "proposed_subject": "Aster",
                "proposed_predicate": "v2_project_region",
            }
        )
    for offset in range(29):
        cases.append(
            {
                "case_id": f"v2_val_z{offset:04d}",
                "target_label": "abstain",
                "expected_memory_id": None,
                "released_memory_id": None,
                "final_disposition": "abstain",
                "language": "en",
                "category": "absent",
                "proposed_subject": None,
                "proposed_predicate": None,
            }
        )
    assert len(cases) == 45
    return {
        "status": module.SOURCE_STATUS,
        "development_only": True,
        "acceptance_evidence": False,
        "phase45e_authorized": False,
        "summary": {
            "cases": 45,
            "released_cases": 16,
            "tp_exact_release": 10,
            "fp_or_wrong_release": 6,
            "target_release_cases": 12,
            "target_abstain_cases": 33,
        },
        "cases": cases,
    }


def _guard_case(
    module: ModuleType,
    *,
    case_id: str,
    language: str,
    category: str,
    correct: bool,
    allow: bool,
    entailment: float = 0.8,
) -> object:
    top_label = "entailment" if allow else "neutral"
    return module.NliGuardCase(
        case_id=case_id,
        language=language,
        category=category,
        source_correct_release=correct,
        proposed_subject="Aster",
        proposed_predicate="v2_project_region",
        top_label=top_label,
        entailment=entailment,
        neutral=0.15 if allow else 0.8,
        contradiction=0.05,
        guard_allow=allow,
    )


def test_contract_is_small_local_veto_only_diagnostic() -> None:
    module = _module()

    assert module.MODEL_ID == (
        "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
    )
    assert module.MODEL_REVISION == "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
    assert module.EXPECTED_SOURCE_RELEASES == 16
    assert module.EXPECTED_SOURCE_CORRECT_RELEASES == 10
    assert module.EXPECTED_SOURCE_FALSE_RELEASES == 6
    assert module.BATCH_SIZE == 16
    assert module.MAX_LENGTH == 256
    assert module.LABELS == ("entailment", "neutral", "contradiction")
    assert module.OUTPUT_DEFAULT.name == (
        ".step4-phase45d-v2-nli-release-guard-diagnostic-v1.json"
    )


def test_source_selection_requires_frozen_16_release_shape() -> None:
    module = _module()
    source = _source_artifact(module)

    releases = module.select_source_releases(source)

    assert len(releases) == 16
    assert sum(module._source_release_is_correct(item) for item in releases) == 10
    assert sum(not module._source_release_is_correct(item) for item in releases) == 6

    source["summary"]["released_cases"] = 15
    with pytest.raises(RuntimeError, match="released_cases changed"):
        module.select_source_releases(source)


def test_policy_hypothesis_uses_selected_facet_without_memory_value() -> None:
    module = _module()

    hypothesis = module.policy_hypothesis(
        subject="Aster",
        predicate="v2_project_region",
    )

    assert hypothesis == (
        "The user's question can be answered solely by the current recorded "
        "deployment region for Aster."
    )
    assert "asia-south" not in hypothesis


def test_inference_pair_reconstructs_query_transiently() -> None:
    module = _module()
    payload = module.v2_cases.build_payload()
    real_case = next(
        item for item in payload["queries"] if item["case_id"] == "v2_val_p0001"
    )
    fact = next(
        fact
        for fact in module.v2_cases.CURRENT_FACTS
        if fact.memory_id == real_case["expected_memory_id"]
    )
    release = {
        "case_id": real_case["case_id"],
        "target_label": "release",
        "expected_memory_id": fact.memory_id,
        "released_memory_id": fact.memory_id,
        "final_disposition": "release",
        "language": real_case["language"],
        "category": real_case["category"],
        "proposed_subject": fact.profile,
        "proposed_predicate": fact.predicate,
    }

    pairs = module.build_inference_pairs([release])

    assert len(pairs) == 1
    query, hypothesis, source = pairs[0]
    assert query == real_case["query"]
    assert fact.profile in hypothesis
    assert fact.value not in hypothesis
    assert source is release


def test_clean_guard_summary_passes_frozen_continuation_gates() -> None:
    module = _module()
    results = []
    counter = 0
    for language, allowed, total in (
        ("en", 3, 4),
        ("hi", 2, 3),
        ("hinglish", 3, 3),
    ):
        for index in range(total):
            counter += 1
            results.append(
                _guard_case(
                    module,
                    case_id=f"correct-{counter}",
                    language=language,
                    category="direct",
                    correct=True,
                    allow=index < allowed,
                )
            )
    for index, (language, category) in enumerate(
        (
            ("hi", "near_miss"),
            ("hinglish", "near_miss"),
            ("hinglish", "adversarial_lexical"),
            ("hi", "negation"),
            ("hinglish", "negation"),
            ("hinglish", "unsupported_source"),
        ),
        start=1,
    ):
        results.append(
            _guard_case(
                module,
                case_id=f"false-{index}",
                language=language,
                category=category,
                correct=False,
                allow=False,
                entailment=0.1,
            )
        )

    summary = module.summarize(results)

    assert summary["source_release_rows"] == 16
    assert summary["retained_correct_releases"] == 8
    assert summary["surviving_false_releases"] == 0
    assert summary["guarded_precision"] == 1.0
    assert summary["correct_release_retention"] == 0.8
    assert all(summary["continuation_checks"].values())
    assert summary["promising_for_architecture_review"] is True


def test_surviving_false_release_fails_guard_summary() -> None:
    module = _module()
    results = []
    for index, language in enumerate(["en"] * 4 + ["hi"] * 3 + ["hinglish"] * 3):
        results.append(
            _guard_case(
                module,
                case_id=f"correct-{index}",
                language=language,
                category="direct",
                correct=True,
                allow=True,
            )
        )
    for index in range(6):
        results.append(
            _guard_case(
                module,
                case_id=f"false-{index}",
                language="hinglish",
                category="near_miss",
                correct=False,
                allow=index == 0,
                entailment=0.8 if index == 0 else 0.1,
            )
        )

    summary = module.summarize(results)

    assert summary["surviving_false_releases"] == 1
    assert summary["continuation_checks"]["zero_surviving_false_releases"] is False
    assert summary["promising_for_architecture_review"] is False


def test_public_case_does_not_persist_query_hypothesis_or_value() -> None:
    module = _module()
    result = _guard_case(
        module,
        case_id="case-1",
        language="hinglish",
        category="near_miss",
        correct=False,
        allow=False,
    )

    public = module._public_case(result)

    assert "query" not in public
    assert "hypothesis" not in public
    assert "value" not in public
    assert "memory_text" not in public


def test_torch_and_transformers_are_lazy_runtime_imports() -> None:
    source = (RESEARCH / "step4_phase45d_nli_release_guard_diagnostic.py").read_text(
        encoding="utf-8"
    )
    prefix = source.split("def _score_pairs", maxsplit=1)[0]

    assert "import torch" not in prefix
    assert "from transformers" not in prefix
