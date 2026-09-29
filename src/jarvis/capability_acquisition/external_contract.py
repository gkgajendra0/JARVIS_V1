"""Public Phase-9 contract for interactive external capability results.

Acquired capabilities may use these typed helpers instead of constructing magic
CapabilityResult.data dictionaries. The contract is capability/vendor agnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT = "phase9.real-external-effect.v1"
PHASE9_EXTERNAL_RESULT_CONTRACT = "phase9.external-capability-result.v1"

OWNER_INPUT_REQUEST_KEY = "owner_input_request"
ACCEPTANCE_OBSERVATION_KEY = "acceptance_observation"

_OWNER_INPUT_KINDS = frozenset({"pin", "confirmation"})
_OBSERVATION_METHODS = frozenset({"device_state_readback", "external_system_readback"})
_PARAMETER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def normalize_owner_input_parameter(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    parameter = str(value).strip().casefold()
    if _PARAMETER.fullmatch(parameter) is None:
        raise ValueError("owner-input parameter is invalid")
    return parameter


def _text(value: object, *, field: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized or len(normalized) > limit:
        raise ValueError(f"{field} must be between 1 and {limit} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class ExternalOwnerInputRequestV1:
    kind: str
    prompt: str
    parameter: str | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind).strip().casefold()
        if kind not in _OWNER_INPUT_KINDS:
            raise ValueError("unsupported external owner-input kind")
        prompt = _text(self.prompt, field="prompt", limit=500)
        parameter = normalize_owner_input_parameter(self.parameter)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "parameter", parameter)

    @classmethod
    def from_payload(cls, payload: object) -> ExternalOwnerInputRequestV1:
        if not isinstance(payload, dict):
            raise TypeError("owner-input request must be an object")
        return cls(
            kind=payload.get("kind"),
            prompt=payload.get("prompt"),
            parameter=payload.get("parameter"),
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_id": PHASE9_EXTERNAL_RESULT_CONTRACT,
            "kind": self.kind,
            "prompt": self.prompt,
        }
        if self.parameter is not None:
            payload["parameter"] = self.parameter
        return payload


@dataclass(frozen=True, slots=True)
class ExternalAcceptanceObservationV1:
    method: str
    summary: str
    evidence_refs: tuple[str, ...]
    observed: bool = True

    def __post_init__(self) -> None:
        method = str(self.method).strip().casefold()
        if method not in _OBSERVATION_METHODS:
            raise ValueError("unsupported external acceptance observation method")
        summary = _text(self.summary, field="summary", limit=1000)
        refs = tuple(
            dict.fromkeys(
                _text(item, field="evidence_ref", limit=1000)
                for item in self.evidence_refs
                if str(item).strip()
            )
        )
        if len(refs) > 20:
            raise ValueError("external acceptance evidence exceeds 20 references")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "observed", bool(self.observed))

    @classmethod
    def from_payload(cls, payload: object) -> ExternalAcceptanceObservationV1:
        if not isinstance(payload, dict):
            raise TypeError("acceptance observation must be an object")
        refs = payload.get("evidence_refs") or ()
        if not isinstance(refs, (list, tuple)):
            raise TypeError("acceptance observation evidence_refs must be an array")
        return cls(
            method=payload.get("method"),
            summary=payload.get("summary"),
            evidence_refs=tuple(str(item) for item in refs),
            observed=payload.get("observed") is True,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "contract_id": PHASE9_EXTERNAL_RESULT_CONTRACT,
            "observed": self.observed,
            "method": self.method,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
        }


def pairing_pin_request(
    prompt: str,
    *,
    parameter: str = "pin",
) -> dict[str, object]:
    return ExternalOwnerInputRequestV1(
        kind="pin",
        prompt=prompt,
        parameter=parameter,
    ).to_payload()


def owner_confirmation_request(
    prompt: str,
    *,
    parameter: str | None = None,
) -> dict[str, object]:
    return ExternalOwnerInputRequestV1(
        kind="confirmation",
        prompt=prompt,
        parameter=parameter,
    ).to_payload()


def acceptance_readback(
    *,
    method: str,
    summary: str,
    evidence_refs: tuple[str, ...] | list[str] = (),
) -> dict[str, object]:
    return ExternalAcceptanceObservationV1(
        method=method,
        summary=summary,
        evidence_refs=tuple(evidence_refs),
        observed=True,
    ).to_payload()


def external_interaction_contract_descriptor() -> dict[str, object]:
    """Stable architecture payload shown directly to Phase-9 DEVELOPMENT."""

    return {
        "contract_id": PHASE9_EXTERNAL_RESULT_CONTRACT,
        "helper_module": "jarvis.capability_acquisition.external_contract",
        "result_data_keys": {
            "owner_input": OWNER_INPUT_REQUEST_KEY,
            "acceptance_observation": ACCEPTANCE_OBSERVATION_KEY,
        },
        "owner_input_kinds": sorted(_OWNER_INPUT_KINDS),
        "observation_methods": sorted(_OBSERVATION_METHODS),
        "semantics": (
            "Return CapabilityStatus.PARTIAL with owner_input_request when execution "
            "needs owner PIN/confirmation. Return acceptance_observation with a "
            "successful result when trusted device/system readback is available."
        ),
    }
