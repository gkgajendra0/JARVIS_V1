from __future__ import annotations

from importlib import util
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "research"
    / "step4_phase45d_gliclass_runtime_sanity_v1.py"
)
SPEC = util.spec_from_file_location("phase45d_gliclass_runtime_sanity_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_candidate_contract_is_frozen() -> None:
    assert MODULE.GLICLASS_PACKAGE_VERSION == "0.1.20"
    assert MODULE.CANDIDATES == (
        {
            "key": "gliclass_multilang_mini",
            "model_id": "knowledgator/gliclass-multilang-mini",
            "revision": "0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b",
        },
        {
            "key": "gliclass_multilang_ultra",
            "model_id": "knowledgator/gliclass-multilang-ultra",
            "revision": "9d6ca10258a3bddcf05b88c89cb8a8390e87e90c",
        },
    )


def test_public_examples_are_not_jarvis_question_role_cases() -> None:
    assert len(MODULE.PUBLIC_CASES) == 5
    assert {row["case_id"] for row in MODULE.PUBLIC_CASES} == {
        "model_card_topic_en",
        "model_card_intent_en",
        "model_card_topic_de",
        "model_card_topic_ar_crosslingual",
        "model_card_government_fr_crosslingual",
    }
    text = "\n".join(str(row["text"]) for row in MODULE.PUBLIC_CASES).casefold()
    for forbidden in (
        "indigo dock",
        "juniper lamp",
        "kestrel router",
        "lotus panel",
        "marble speaker",
        "nimbus lock",
        "opal tablet",
        "pine camera",
    ):
        assert forbidden not in text


def test_shared_batch_can_detect_single_label_collapse() -> None:
    assert len(MODULE.SHARED_BATCH_CASES) == 3
    assert set(MODULE.SHARED_BATCH_LABELS) == {
        "space",
        "politics",
        "sports",
        "technology",
        "economy",
        "health",
    }
    expected_sets = [set(row["expected_any"]) for row in MODULE.SHARED_BATCH_CASES]
    assert expected_sets[0] == {"space"}
    assert expected_sets[1] == {"economy", "politics"}
    assert expected_sets[2] == {"space"}


def test_one_prediction_rejects_invalid_shapes() -> None:
    assert MODULE._one_prediction([{"label": "space", "score": 0.8}]) == {
        "label": "space",
        "score": 0.8,
    }

    for invalid in ([], [{"label": "a", "score": 0.1}, {"label": "b", "score": 0.2}]):
        try:
            MODULE._one_prediction(invalid)
        except TypeError:
            pass
        else:
            raise AssertionError("invalid single-label output shape must fail")


def test_output_contract_is_diagnostic_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"diagnostic_only": True' in source
    assert '"jarvis_question_role_v1_queries_used": False' in source
    assert '"question_role_v1_rerun_authorized": False' in source
    assert '"production_change_authorized": False' in source
    assert '"phase45e_authorized": False' in source
    assert "refusing to overwrite GLiClass runtime sanity evidence" in source
