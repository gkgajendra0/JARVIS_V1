from __future__ import annotations

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import PERSISTABLE_SETTINGS


def test_semantic_recall_is_opt_in_by_model_setting() -> None:
    disabled = JarvisConfig(memory_enabled=True)
    assert not disabled.memory_semantic_recall_enabled

    enabled = JarvisConfig(
        memory_enabled=True,
        memory_semantic_recall_model="gemini-3.8-flash",
    )
    assert enabled.memory_semantic_recall_enabled
    assert enabled.memory_semantic_recall_model == "gemini-3.8-flash"


def test_semantic_recall_model_requires_memory_enabled() -> None:
    with pytest.raises(ValueError, match="JARVIS_MEMORY_SEMANTIC_RECALL_MODEL"):
        JarvisConfig(
            memory_enabled=False,
            memory_semantic_recall_model="gemini-3.8-flash",
        )


def test_semantic_recall_model_is_persistable_non_secret_config() -> None:
    assert "JARVIS_MEMORY_SEMANTIC_RECALL_MODEL" in PERSISTABLE_SETTINGS
