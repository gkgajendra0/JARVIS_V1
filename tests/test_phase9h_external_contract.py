from __future__ import annotations

import pytest

from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionArchitecturePlan,
)
from jarvis.capability_acquisition.external_contract import (
    ACCEPTANCE_OBSERVATION_KEY,
    OWNER_INPUT_REQUEST_KEY,
    PHASE9_EXTERNAL_RESULT_CONTRACT,
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
    ExternalAcceptanceObservationV1,
    ExternalOwnerInputRequestV1,
    acceptance_readback,
    external_interaction_contract_descriptor,
    owner_confirmation_request,
    pairing_pin_request,
)


def _architecture(*, external: bool) -> CapabilityAcquisitionArchitecturePlan:
    owner_contracts = (
        (PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,) if external else ("unit-test.v1",)
    )
    return CapabilityAcquisitionArchitecturePlan(
        goal_artifact_id="artifact-goal",
        goal_artifact_digest="a" * 64,
        goal_id="goal-demo",
        goal_digest="b" * 64,
        plan_artifact_id="artifact-plan",
        plan_artifact_digest="c" * 64,
        plan_id="plan-demo",
        plan_digest="d" * 64,
        selected_candidate_id="candidate-demo",
        selected_candidate_digest="e" * 64,
        selected_evaluation_digest="f" * 64,
        source_revision="1" * 40,
        strategy="adapt_sdk",
        requested_operations=("device.control",),
        allowed_paths=("src/jarvis/capabilities/acquired_demo.py",),
        allowed_components=(),
        dependency_refs=(),
        secret_scopes=("device.pair",),
        sandbox_profile_ids=("test.offline.v1",),
        discovery_scopes=("ssdp_upnp.v1",),
        network_scopes=("local-network",),
        device_scopes=("owner-selected-device",),
        verification_contract_ids=("capability-contract-test.v1",),
        verification_targets=("tests/test_acquired_demo.py",),
        owner_acceptance_contract_ids=owner_contracts,
        proposed_capability_id="acquired.demo",
        proposed_package_id="package.demo",
        proposed_package_version="1.0.0",
        rollback_strategy="disable package",
    )


def test_pairing_and_confirmation_helpers_round_trip() -> None:
    pin_payload = pairing_pin_request("Enter the code shown by the device.")
    pin = ExternalOwnerInputRequestV1.from_payload(pin_payload)

    assert pin.kind == "pin"
    assert pin.parameter == "pin"
    assert pin_payload["contract_id"] == PHASE9_EXTERNAL_RESULT_CONTRACT

    confirmation_payload = owner_confirmation_request(
        "Approve the pairing request shown by the device."
    )
    confirmation = ExternalOwnerInputRequestV1.from_payload(confirmation_payload)

    assert confirmation.kind == "confirmation"
    assert confirmation.parameter is None


def test_external_contract_rejects_unbounded_or_unknown_owner_input() -> None:
    with pytest.raises(ValueError, match="unsupported external owner-input kind"):
        ExternalOwnerInputRequestV1.from_payload(
            {"kind": "password", "prompt": "Give me a password."}
        )

    with pytest.raises(ValueError, match="parameter is invalid"):
        pairing_pin_request("Enter PIN.", parameter="../pin")


def test_acceptance_readback_round_trip() -> None:
    payload = acceptance_readback(
        method="device_state_readback",
        summary="Device reports the requested state.",
        evidence_refs=("device-state:demo",),
    )
    observation = ExternalAcceptanceObservationV1.from_payload(payload)

    assert observation.observed is True
    assert observation.method == "device_state_readback"
    assert observation.evidence_refs == ("device-state:demo",)
    assert payload["contract_id"] == PHASE9_EXTERNAL_RESULT_CONTRACT


def test_external_architecture_exposes_runtime_interaction_contract() -> None:
    payload = _architecture(external=True).to_payload()
    descriptor = payload["external_runtime_contract"]

    assert descriptor == external_interaction_contract_descriptor()
    assert descriptor["contract_id"] == PHASE9_EXTERNAL_RESULT_CONTRACT
    assert descriptor["helper_module"] == (
        "jarvis.capability_acquisition.external_contract"
    )
    assert descriptor["result_data_keys"] == {
        "owner_input": OWNER_INPUT_REQUEST_KEY,
        "acceptance_observation": ACCEPTANCE_OBSERVATION_KEY,
    }


def test_non_external_architecture_does_not_add_interaction_contract() -> None:
    payload = _architecture(external=False).to_payload()

    assert "external_runtime_contract" not in payload
