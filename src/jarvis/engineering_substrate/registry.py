"""Fail-closed exact schema/version registry for Phase-5 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from jarvis.engineering_substrate.contracts import SCHEMA_VERSION_V1


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


class SubstrateRegistryError(RuntimeError):
    """Base error for Phase-5 registry admission and exact lookup."""


class DuplicateSchemaRegistrationError(SubstrateRegistryError):
    """An exact schema ID/version is already registered."""


class UnknownSchemaVersionError(SubstrateRegistryError):
    """An exact schema ID/version is not registered and therefore fails closed."""


@dataclass(frozen=True, order=True, slots=True)
class ContractSchemaRegistration:
    schema_id: str
    schema_version: int
    contract_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_id", _token(self.schema_id, field="schema_id"))
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, field="schema_version"),
        )
        object.__setattr__(
            self,
            "contract_name",
            _token(self.contract_name, field="contract_name"),
        )


class ContractSchemaRegistry:
    """Exact schema/version registry; no implicit latest-version fallback exists."""

    def __init__(
        self,
        registrations: Iterable[ContractSchemaRegistration] = (),
    ) -> None:
        self._registrations: dict[
            tuple[str, int],
            ContractSchemaRegistration,
        ] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: ContractSchemaRegistration) -> None:
        if not isinstance(registration, ContractSchemaRegistration):
            raise TypeError("registration must be a ContractSchemaRegistration")
        key = (registration.schema_id, registration.schema_version)
        if key in self._registrations:
            raise DuplicateSchemaRegistrationError(
                "schema already registered: "
                f"{registration.schema_id}.v{registration.schema_version}"
            )
        self._registrations[key] = registration

    def require(
        self,
        schema_id: str,
        schema_version: int,
    ) -> ContractSchemaRegistration:
        key = (
            _token(schema_id, field="schema_id"),
            _positive_int(schema_version, field="schema_version"),
        )
        try:
            return self._registrations[key]
        except KeyError as exc:
            raise UnknownSchemaVersionError(
                f"unknown schema/version: {key[0]}.v{key[1]}"
            ) from exc

    def all(self) -> tuple[ContractSchemaRegistration, ...]:
        return tuple(self._registrations[key] for key in sorted(self._registrations))


PHASE5_V1_SCHEMA_REGISTRATIONS = (
    ContractSchemaRegistration(
        "dependency_requirement", SCHEMA_VERSION_V1, "DependencyRequirement"
    ),
    ContractSchemaRegistration(
        "dependency_resolution", SCHEMA_VERSION_V1, "DependencyResolution"
    ),
    ContractSchemaRegistration(
        "dependency_artifact", SCHEMA_VERSION_V1, "DependencyArtifact"
    ),
    ContractSchemaRegistration(
        "artifact_provenance", SCHEMA_VERSION_V1, "ArtifactProvenance"
    ),
    ContractSchemaRegistration(
        "secret_descriptor", SCHEMA_VERSION_V1, "SecretDescriptor"
    ),
    ContractSchemaRegistration("secret_lease", SCHEMA_VERSION_V1, "SecretLease"),
    ContractSchemaRegistration(
        "capability_manifest", SCHEMA_VERSION_V1, "CapabilityManifest"
    ),
    ContractSchemaRegistration(
        "discovery_scope", SCHEMA_VERSION_V1, "DiscoveryScope"
    ),
    ContractSchemaRegistration(
        "discovery_observation", SCHEMA_VERSION_V1, "DiscoveryObservation"
    ),
    ContractSchemaRegistration(
        "sandbox_profile", SCHEMA_VERSION_V1, "SandboxProfile"
    ),
    ContractSchemaRegistration(
        "hardware_acceptance_request",
        SCHEMA_VERSION_V1,
        "HardwareAcceptanceRequest",
    ),
    ContractSchemaRegistration(
        "hardware_acceptance_evidence",
        SCHEMA_VERSION_V1,
        "HardwareAcceptanceEvidence",
    ),
)


def default_contract_schema_registry() -> ContractSchemaRegistry:
    return ContractSchemaRegistry(PHASE5_V1_SCHEMA_REGISTRATIONS)
