from __future__ import annotations

from pathlib import Path

from jarvis.self_model.defaults import build_default_self_model


def test_default_self_model_is_hierarchical_and_covers_jarvis_namespaces() -> None:
    model = build_default_self_model()

    assert len(model.components) >= 35
    assert model.root_components[0].component_id == "jarvis"
    assert len(model.root_components) == 1
    assert model.component("runtime.voice") is not None
    assert model.component("voice.wake") is not None
    assert model.component("memory.durable") is not None
    assert model.component("identity.owner") is not None
    assert model.component("hands.browser") is not None
    assert model.component("observability.logs") is not None

    assert model.component("voice.wake").parent_component_id == "runtime.voice"
    assert "voice.wake" in {
        item.component_id for item in model.descendants_of("runtime.voice")
    }
    assert model.ancestors_of("voice.wake")[0].component_id == "runtime.voice"

    source_root = Path("src/jarvis")
    immediate = {
        path.name for path in source_root.iterdir() if path.name != "__pycache__"
    }
    mapped = set()
    for descriptor in model.components:
        if descriptor.component_id == "jarvis":
            continue
        for source_path in descriptor.source_paths:
            path = Path(source_path)
            try:
                relative = path.relative_to(source_root)
            except ValueError:
                continue
            if relative.parts:
                mapped.add(relative.parts[0])

    missing = sorted(immediate - mapped)
    assert missing == []


def test_health_surface_remains_bounded_despite_deep_self_model() -> None:
    model = build_default_self_model()

    health_ids = {item.component_id for item in model.health_components}

    assert 5 <= len(health_ids) < len(model.components)
    assert "runtime.voice" in health_ids
    assert "runtime.provider" in health_ids
    assert "vision.pocket3" in health_ids
    assert "hands" in health_ids
