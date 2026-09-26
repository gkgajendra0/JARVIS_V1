from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.authority import RiskClass
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate import (
    CapabilityManifest,
    HardwareAcceptanceConflict,
    HardwareAcceptanceExpired,
    HardwareAcceptanceService,
    HardwareAcceptanceVerdict,
    RegisteredCapabilityManifest,
    canonical_digest,
)
from jarvis.engineering_substrate.hardware_acceptance import (
    main as hardware_acceptance_cli_main,
)
from jarvis.work.store import SQLiteWorkStore


class MutableClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _store(tmp_path: Path) -> ChangeStore:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = ChangeStore(work)
    store.create(
        request="phase5h hardware acceptance test",
        process_key=ChangeStore.DEFAULT_PROCESS.key,
        process_version=ChangeStore.DEFAULT_PROCESS.version,
        source_session_id="phase5h-session",
        source_turn_id="phase5h-turn",
    )
    return store


def _change_id(store: ChangeStore) -> str:
    return store.find_by_source(
        "phase5h-session",
        "phase5h-turn",
        ChangeStore.DEFAULT_PROCESS.key,
    ).change_id


def _manifest() -> RegisteredCapabilityManifest:
    manifest = CapabilityManifest(
        manifest_id="manifest.phase5h.demo",
        manifest_version=1,
        capability_id="capability.phase5h.demo",
        capability_version="1.0.0",
        purpose="harmless representative physical-effect acceptance",
        adapter_id="adapter.phase5h.demo",
        executor_id="executor.phase5h.demo",
        operations=("move",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=(),
        sandbox_profile_ids=(),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=("verification.software-security.v1",),
        hardware_acceptance_contract_ids=("hardware.physical-observation.v1",),
        provenance_ids=(),
        disable_rollback_contract_id="rollback.phase5h.demo",
        dependency_resolution_digests=(),
        sandbox_profile_digests=(),
        discovery_scope_digests=(),
        provenance_digests=(),
    )
    return RegisteredCapabilityManifest(
        manifest=manifest,
        manifest_digest=canonical_digest(manifest),
        authority_risk_floor=RiskClass.ROUTINE,
    )


def _request(
    service: HardwareAcceptanceService,
    store: ChangeStore,
    *,
    request_id: str | None = None,
    automated: tuple[str, ...] = ("software-security",),
    ttl_seconds: float = 30.0,
):
    return service.create_request(
        change_id=_change_id(store),
        manifest=_manifest(),
        device_identity="device:test-actuator:1",
        operation="move",
        expected_observation="indicator changes from idle to active",
        required_automated_evidence_ids=automated,
        ttl_seconds=ttl_seconds,
        request_id=request_id,
    )


def _resolve(
    service: HardwareAcceptanceService,
    request,
    *,
    verdict: HardwareAcceptanceVerdict = HardwareAcceptanceVerdict.PASS,
    resolution_key: str = "phase5h-resolution-1",
):
    return service.resolve(
        request_id=request.request_id,
        request_digest=canonical_digest(request),
        manifest_digest=request.manifest_digest,
        device_identity=request.device_identity,
        operation=request.operation,
        verdict=verdict,
        resolution_key=resolution_key,
        owner_observation_ref="owner-observation:phase5h:test",
    )


def test_request_is_durable_digest_bound_and_pending_across_restart(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    clock = MutableClock()
    service = HardwareAcceptanceService(store, clock=clock)
    request = _request(service, store, request_id="hwreq-phase5h-durable")

    restarted = HardwareAcceptanceService(store, clock=clock)

    assert restarted.get_request(request.request_id) == request
    assert restarted.request_digest(request.request_id) == canonical_digest(request)
    assert restarted.pending_request_ids(change_id=_change_id(store)) == (
        request.request_id,
    )


def test_request_rejects_untrusted_manifest_digest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    manifest = replace(_manifest(), manifest_digest="f" * 64)

    with pytest.raises(HardwareAcceptanceConflict, match="digest does not match"):
        service.create_request(
            change_id=_change_id(store),
            manifest=manifest,
            device_identity="device:test-actuator:1",
            operation="move",
            expected_observation="indicator changes",
        )


def test_stale_request_cannot_be_newly_resolved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    clock = MutableClock()
    service = HardwareAcceptanceService(store, clock=clock)
    request = _request(service, store, ttl_seconds=5.0)

    clock.value = request.expires_at_epoch

    with pytest.raises(HardwareAcceptanceExpired, match="expired"):
        _resolve(service, request)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("request_digest", "f" * 64, "request digest mismatch"),
        ("manifest_digest", "e" * 64, "manifest digest mismatch"),
        ("device_identity", "device:other:9", "device identity mismatch"),
        ("operation", "rotate", "operation mismatch"),
    ),
)
def test_resolution_requires_exact_request_bindings(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    request = _request(service, store)
    values = {
        "request_id": request.request_id,
        "request_digest": canonical_digest(request),
        "manifest_digest": request.manifest_digest,
        "device_identity": request.device_identity,
        "operation": request.operation,
        "verdict": HardwareAcceptanceVerdict.PASS,
        "resolution_key": "phase5h-exact-binding",
        "owner_observation_ref": "owner-observation:phase5h:test",
    }
    values[field] = value

    with pytest.raises(HardwareAcceptanceConflict, match=message):
        service.resolve(**values)


def test_unrelated_free_form_yes_cannot_resolve_request() -> None:
    with pytest.raises(SystemExit):
        hardware_acceptance_cli_main(["resolve", "yes"])


@pytest.mark.parametrize(
    ("verdict", "satisfied"),
    (
        (HardwareAcceptanceVerdict.PASS, True),
        (HardwareAcceptanceVerdict.FAIL, False),
        (HardwareAcceptanceVerdict.INCONCLUSIVE, False),
    ),
)
def test_only_pass_can_satisfy_hardware_contract(
    tmp_path: Path,
    verdict: HardwareAcceptanceVerdict,
    satisfied: bool,
) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    request = _request(
        service,
        store,
        request_id=f"hwreq-{verdict.value}",
    )
    _resolve(
        service,
        request,
        verdict=verdict,
        resolution_key=f"resolution-{verdict.value}",
    )

    assessment = service.assess(
        request.request_id,
        automated_evidence={"software-security": True},
    )

    assert assessment.verdict is verdict
    assert assessment.satisfied is satisfied


def test_hardware_pass_cannot_override_failed_or_missing_automated_evidence(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    request = _request(service, store)
    evidence = _resolve(service, request)

    failed = service.assess(
        request.request_id,
        automated_evidence={"software-security": False},
    )
    missing = service.assess(
        request.request_id,
        automated_evidence={},
    )
    passed = service.assess(
        request.request_id,
        automated_evidence={"software-security": True},
    )

    assert evidence.verdict is HardwareAcceptanceVerdict.PASS
    assert failed.satisfied is False
    assert failed.failed_automated_evidence_ids == ("software-security",)
    assert missing.satisfied is False
    assert missing.missing_automated_evidence_ids == ("software-security",)
    assert passed.satisfied is True


def test_resolution_requires_observation_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    request = _request(service, store)

    with pytest.raises(HardwareAcceptanceConflict, match="observation evidence"):
        service.resolve(
            request_id=request.request_id,
            request_digest=canonical_digest(request),
            manifest_digest=request.manifest_digest,
            device_identity=request.device_identity,
            operation=request.operation,
            verdict=HardwareAcceptanceVerdict.PASS,
            resolution_key="no-observation",
        )


def test_exact_duplicate_resolution_is_idempotent_even_after_expiry(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    clock = MutableClock()
    service = HardwareAcceptanceService(store, clock=clock)
    request = _request(service, store, ttl_seconds=5.0)

    first = _resolve(service, request)
    clock.value = request.expires_at_epoch + 100
    restarted = HardwareAcceptanceService(store, clock=clock)
    second = _resolve(restarted, request)

    assert second == first
    assert restarted.pending_request_ids() == ()


def test_duplicate_request_cannot_be_resolved_differently(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    request = _request(service, store)
    _resolve(service, request)

    with pytest.raises(HardwareAcceptanceConflict, match="resolved differently"):
        _resolve(
            service,
            request,
            verdict=HardwareAcceptanceVerdict.FAIL,
        )


def test_resolution_key_cannot_be_reused_for_another_request(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    first_request = _request(service, store, request_id="hwreq-first")
    second_request = _request(service, store, request_id="hwreq-second")
    _resolve(
        service,
        first_request,
        resolution_key="same-resolution-key",
    )

    with pytest.raises(HardwareAcceptanceConflict, match="compare-and-set race"):
        _resolve(
            service,
            second_request,
            resolution_key="same-resolution-key",
        )


def test_verification_projection_contains_only_bounded_linkage_metadata(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    service = HardwareAcceptanceService(store, clock=MutableClock())
    request = _request(service, store)
    _resolve(service, request)

    projection = service.verification_projection(
        request.request_id,
        automated_evidence={"software-security": True},
    )

    assert projection["satisfied"] is True
    assert projection["request_id"] == request.request_id
    assert projection["request_digest"] == canonical_digest(request)
    assert "expected_observation" not in projection
    assert "device_identity" not in projection
