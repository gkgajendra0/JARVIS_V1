"""Phase-5E DPAPI SecretStore and authority-bound SecretBroker."""

from jarvis.engineering_substrate.secrets.broker import (
    PRIVATE_INDEX_TOKEN_CONSUMER,
    CanonicalAuthoritySecretGate,
    SecretAuthorityEvidence,
    SecretAuthorityGate,
    SecretAuthorizationError,
    SecretBroker,
    SecretBrokerError,
    SecretConsumerPolicy,
    SecretConsumerRegistry,
    SecretLeaseError,
    SecretLeaseRequest,
    build_secret_lease_proposal,
    default_secret_consumer_registry,
)
from jarvis.engineering_substrate.secrets.redaction import SecretRedactor
from jarvis.engineering_substrate.secrets.store import (
    SecretAlreadyExistsError,
    SecretIntegrityError,
    SecretMaterial,
    SecretNotFoundError,
    SecretStateError,
    SecretStore,
    SecretStoreError,
    default_secret_store_path,
)

__all__ = [
    "PRIVATE_INDEX_TOKEN_CONSUMER",
    "CanonicalAuthoritySecretGate",
    "SecretAlreadyExistsError",
    "SecretAuthorityEvidence",
    "SecretAuthorityGate",
    "SecretAuthorizationError",
    "SecretBroker",
    "SecretBrokerError",
    "SecretConsumerPolicy",
    "SecretConsumerRegistry",
    "SecretIntegrityError",
    "SecretLeaseError",
    "SecretLeaseRequest",
    "SecretMaterial",
    "SecretNotFoundError",
    "SecretRedactor",
    "SecretStateError",
    "SecretStore",
    "SecretStoreError",
    "build_secret_lease_proposal",
    "default_secret_consumer_registry",
    "default_secret_store_path",
]
