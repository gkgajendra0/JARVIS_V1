from __future__ import annotations

from dataclasses import dataclass

from .types import ActionAttributes, ActionScope, RiskClass


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    risk_class: RiskClass
    reason_codes: tuple[str, ...]


class RiskClassifier:
    """Deterministic hard-floor classifier. LLM output is never an input."""

    def classify(self, attributes: ActionAttributes) -> RiskAssessment:
        reasons: list[str] = []

        if attributes.authority_policy_change:
            reasons.append("authority_policy_change")
        if attributes.audit_control_change:
            reasons.append("audit_control_change")
        if attributes.self_modification:
            reasons.append("self_modification")
        if reasons:
            return RiskAssessment(RiskClass.RESTRICTED_DEV_ONLY, tuple(reasons))

        if attributes.financial_or_legal:
            reasons.append("financial_or_legal")
        if attributes.secret_or_credential_access:
            reasons.append("secret_or_credential_access")
        if attributes.security_or_permission_change:
            reasons.append("security_or_permission_change")
        if attributes.executable_or_system_change:
            reasons.append("executable_or_system_change")
        if attributes.identity_profile_change:
            reasons.append("identity_profile_change")
        if attributes.destructive:
            reasons.append("destructive")
        if attributes.irreversible:
            reasons.append("irreversible")
        if attributes.scope is ActionScope.BULK and (
            attributes.persistent_write or attributes.external_side_effect
        ):
            reasons.append("bulk_side_effect")
        if reasons:
            return RiskAssessment(RiskClass.CRITICAL, tuple(reasons))

        if attributes.persistent_write or attributes.external_side_effect:
            if attributes.persistent_write:
                reasons.append("persistent_write")
            if attributes.external_side_effect:
                reasons.append("external_side_effect")
            if attributes.background_or_proactive:
                reasons.append("background_or_proactive")
            return RiskAssessment(
                RiskClass.PERSISTENT_OR_EXTERNAL,
                tuple(reasons),
            )

        if attributes.reversible_local_change:
            return RiskAssessment(
                RiskClass.REVERSIBLE_LOCAL_CHANGE,
                ("reversible_local_change",),
            )

        if attributes.private_read:
            return RiskAssessment(RiskClass.PRIVATE_READ, ("private_read",))

        return RiskAssessment(RiskClass.ROUTINE, ("routine",))
