from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .types import ActionAttributes, ActionOrigin


class ProposalValidationError(ValueError):
    pass


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProposalValidationError("proposal floats must be finite")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProposalValidationError(
                    "proposal mapping keys must be strings"
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ProposalValidationError(
                    "proposal mapping keys collide after Unicode normalization"
                )
            normalized[normalized_key] = _normalize_json(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, bytes | bytearray | str
    ):
        return [_normalize_json(item) for item in value]
    raise ProposalValidationError(
        f"unsupported proposal value type: {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ActionProposal:
    proposal_id: str
    nonce: str
    schema_version: int
    session_id: str
    capability: str
    operation: str
    target_json: str
    parameters_json: str
    material_summary: str
    attributes: ActionAttributes
    origin: ActionOrigin
    created_at_monotonic: float
    expires_at_monotonic: float
    fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        capability: str,
        operation: str,
        target: Any,
        parameters: Any,
        material_summary: str,
        attributes: ActionAttributes,
        origin: ActionOrigin,
        ttl_seconds: float = 120.0,
        proposal_id: str | None = None,
        nonce: str | None = None,
        now_monotonic: float | None = None,
    ) -> ActionProposal:
        normalized_session = session_id.strip()
        normalized_capability = unicodedata.normalize("NFC", capability).strip()
        normalized_operation = unicodedata.normalize("NFC", operation).strip()
        normalized_summary = unicodedata.normalize("NFC", material_summary).strip()
        if not normalized_session:
            raise ProposalValidationError("session_id must not be empty")
        if not normalized_capability:
            raise ProposalValidationError("capability must not be empty")
        if not normalized_operation:
            raise ProposalValidationError("operation must not be empty")
        if not normalized_summary:
            raise ProposalValidationError("material_summary must not be empty")
        if ttl_seconds <= 0:
            raise ProposalValidationError("proposal ttl must be positive")

        normalized_proposal_id = (proposal_id or str(uuid.uuid4())).strip()
        normalized_nonce = (nonce or str(uuid.uuid4())).strip()
        if not normalized_proposal_id:
            raise ProposalValidationError("proposal_id must not be empty")
        if not normalized_nonce:
            raise ProposalValidationError("nonce must not be empty")

        target_json = canonical_json(target)
        parameters_json = canonical_json(parameters)
        schema_version = 1
        now = time.monotonic() if now_monotonic is None else now_monotonic
        material = {
            "schema_version": schema_version,
            "session_id": normalized_session,
            "nonce": normalized_nonce,
            "capability": normalized_capability,
            "operation": normalized_operation,
            "target": json.loads(target_json),
            "parameters": json.loads(parameters_json),
            "attributes": attributes.as_policy_dict(),
            "origin": origin.value,
        }
        fingerprint = hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest()
        return cls(
            proposal_id=normalized_proposal_id,
            nonce=normalized_nonce,
            schema_version=schema_version,
            session_id=normalized_session,
            capability=normalized_capability,
            operation=normalized_operation,
            target_json=target_json,
            parameters_json=parameters_json,
            material_summary=normalized_summary,
            attributes=attributes,
            origin=origin,
            created_at_monotonic=now,
            expires_at_monotonic=now + ttl_seconds,
            fingerprint=fingerprint,
        )

    def recompute_fingerprint(self) -> str:
        material = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "nonce": self.nonce,
            "capability": self.capability,
            "operation": self.operation,
            "target": self.target(),
            "parameters": self.parameters(),
            "attributes": self.attributes.as_policy_dict(),
            "origin": self.origin.value,
        }
        return hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest()

    def has_valid_fingerprint(self) -> bool:
        try:
            return self.recompute_fingerprint() == self.fingerprint
        except (ProposalValidationError, json.JSONDecodeError):
            return False

    def is_expired(self, now_monotonic: float | None = None) -> bool:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        return now >= self.expires_at_monotonic

    def target(self) -> Any:
        return json.loads(self.target_json)

    def parameters(self) -> Any:
        return json.loads(self.parameters_json)

    def policy_view(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "capability": self.capability,
            "operation": self.operation,
            "fingerprint": self.fingerprint,
            "target": self.target(),
            "parameters": self.parameters(),
            "attributes": self.attributes.as_policy_dict(),
            "origin": self.origin.value,
        }
