from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c5_semantic_admission.py"


def _load_module():
    name = "jarvis_c5_semantic_admission_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_profiles_use_production_like_tier_a_modes() -> None:
    module = _load_module()

    assert [
        (profile.name, profile.model, profile.ollama_think)
        for profile in module.PROFILES
    ] == [
        ("phi4-mini-default", "phi4-mini", "default"),
        ("qwen3.5-4b-think-off", "qwen3.5:4b", "off"),
    ]


def test_clean_task_classes_require_full_exact_safe_coverage() -> None:
    module = _load_module()

    summaries = {
        "classification_extraction": {
            "coverage": 1.0,
            "accuracy_over_covered": 1.0,
            "structured_output_failures": 0,
            "unsafe_downgrades": 0,
        },
        "debugging": {
            "coverage": 1.0,
            "accuracy_over_covered": 0.9,
            "structured_output_failures": 0,
            "unsafe_downgrades": 0,
        },
        "summarization": {
            "coverage": 0.8,
            "accuracy_over_covered": 1.0,
            "structured_output_failures": 1,
            "unsafe_downgrades": 0,
        },
    }

    assert module._clean_task_classes(summaries) == ["classification_extraction"]


def test_task_class_for_case_uses_expected_task_class() -> None:
    module = _load_module()

    class Question:
        def __init__(self, name, expected):
            self.name = name
            self.expected = expected

    class Case:
        questions = (
            Question("reasoning_tier", "local_sufficient"),
            Question("task_class", "bounded_planning"),
        )

    assert module._task_class_for_case(Case()) == "bounded_planning"
