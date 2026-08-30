from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class TrustTier(IntEnum):
    UNVERIFIED = 0
    PRESENT_CONTEXT = 1
    CORROBORATED_OWNER = 2
    VERIFIED_OWNER = 3


class RiskClass(IntEnum):
    ROUTINE = 0
    PRIVATE_READ = 1
    REVERSIBLE_LOCAL_CHANGE = 2
    PERSISTENT_OR_EXTERNAL = 3
    CRITICAL = 4
    RESTRICTED_DEV_ONLY = 5


class ApprovalRequirement(IntEnum):
    NONE = 0
    DIRECT_INTENT = 1
    EXPLICIT = 2
    STRONG = 3


class ApprovalMethod(str, Enum):
    DIRECT_INTENT = "direct_intent"
    SPOKEN = "spoken"
    STRONG_VERIFIER = "strong_verifier"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    CANCELED = "canceled"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class AuthorityEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class AttentionState(str, Enum):
    ATTENTIVE = "attentive"
    NOT_ATTENTIVE = "not_attentive"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class EvidenceModality(str, Enum):
    WINDOWS_SESSION = "windows_session"
    PERSON_PRESENCE = "person_presence"
    FACE_MATCH = "face_match"
    FACE_LIVENESS = "face_liveness"
    ATTENTION = "attention"
    SPEAKER_MATCH = "speaker_match"
    VOICE_SPOOF = "voice_spoof"
    ACTIVE_SPEAKER = "active_speaker"
    STRONG_VERIFICATION = "strong_verification"


class ActionScope(str, Enum):
    SINGLE = "single"
    LIMITED = "limited"
    BULK = "bulk"


class ActionOrigin(str, Enum):
    DIRECT_USER = "direct_user"
    MODEL_SUGGESTED = "model_suggested"
    PROACTIVE = "proactive"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class ActionAttributes:
    private_read: bool = False
    reversible_local_change: bool = False
    persistent_write: bool = False
    external_side_effect: bool = False
    destructive: bool = False
    irreversible: bool = False
    financial_or_legal: bool = False
    secret_or_credential_access: bool = False
    security_or_permission_change: bool = False
    executable_or_system_change: bool = False
    identity_profile_change: bool = False
    authority_policy_change: bool = False
    audit_control_change: bool = False
    self_modification: bool = False
    background_or_proactive: bool = False
    scope: ActionScope = ActionScope.SINGLE

    def as_policy_dict(self) -> dict[str, object]:
        return {
            "private_read": self.private_read,
            "reversible_local_change": self.reversible_local_change,
            "persistent_write": self.persistent_write,
            "external_side_effect": self.external_side_effect,
            "destructive": self.destructive,
            "irreversible": self.irreversible,
            "financial_or_legal": self.financial_or_legal,
            "secret_or_credential_access": self.secret_or_credential_access,
            "security_or_permission_change": self.security_or_permission_change,
            "executable_or_system_change": self.executable_or_system_change,
            "identity_profile_change": self.identity_profile_change,
            "authority_policy_change": self.authority_policy_change,
            "audit_control_change": self.audit_control_change,
            "self_modification": self.self_modification,
            "background_or_proactive": self.background_or_proactive,
            "scope": self.scope.value,
        }


@dataclass(frozen=True, slots=True)
class InteractionContext:
    session_id: str
    trust_tier: TrustTier
    attention_state: AttentionState = AttentionState.UNAVAILABLE
    actor_unambiguous: bool = False
    windows_session_valid: bool = True

    @property
    def owner_attentive(self) -> bool:
        return (
            self.trust_tier >= TrustTier.CORROBORATED_OWNER
            and self.attention_state is AttentionState.ATTENTIVE
            and self.actor_unambiguous
        )
