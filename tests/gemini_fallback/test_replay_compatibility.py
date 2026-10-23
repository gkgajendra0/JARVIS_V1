from copy import deepcopy

import pytest

from jarvis.model_routing.registry import ModelTargetRegistry
from jarvis.model_routing.router import RoutingProvenanceError

from .helpers import make_router, scoped_request


def test_v2_replay_uses_original_registry_after_model_change(tmp_path):
    router, store = make_router(tmp_path, model="gemini-original")
    first = router.route(scoped_request())
    changed, _ = make_router(tmp_path, model="gemini-new")
    replay = changed.route(scoped_request())
    assert replay.reused_decision
    assert replay.decision == first.decision
    assert replay.target.model_id == "gemini-original"
    assert replay.registry.digest() == first.registry.digest()
    assert store.get_registry_snapshot(first.registry.digest()) is not None


def test_registry_snapshot_roundtrip_and_tamper_rejection(tmp_path):
    router, _ = make_router(tmp_path)
    snapshot = router.target_registry.to_snapshot()
    restored = ModelTargetRegistry.from_snapshot(
        snapshot, adapter_registry=router.adapter_registry
    )
    assert restored.digest() == router.target_registry.digest()
    bad = deepcopy(snapshot)
    bad["targets"][0]["credential_ref"] = "PATH"
    with pytest.raises((ValueError, TypeError)):
        ModelTargetRegistry.from_snapshot(bad, adapter_registry=router.adapter_registry)
    bad = deepcopy(snapshot)
    bad["targets"][0]["model_id"] = "tampered"
    with pytest.raises((ValueError, TypeError)):
        ModelTargetRegistry.from_snapshot(bad, adapter_registry=router.adapter_registry)


def test_unrecoverable_registry_fails_closed(tmp_path):
    router, store = make_router(tmp_path, model="gemini-original")
    router.route(scoped_request())
    with store.work_store.extension_transaction() as connection:
        connection.execute("DELETE FROM model_routing_registry_snapshots")
    changed, _ = make_router(tmp_path, model="gemini-new")
    with pytest.raises(RoutingProvenanceError):
        changed.route(scoped_request())


def test_snapshot_immutable_for_existing_digest(tmp_path):
    router, store = make_router(tmp_path)
    snapshot = router.target_registry.to_snapshot()
    store.save_registry_snapshot(snapshot)
    store.save_registry_snapshot(snapshot)
    bad = deepcopy(snapshot)
    bad["targets"][0]["model_id"] = "tampered"
    with pytest.raises((ValueError, TypeError)):
        store.save_registry_snapshot(bad)
