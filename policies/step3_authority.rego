package jarvis.authority

import rego.v1

default decision := {
    "allow": false,
    "required_trust": 3,
    "approval_requirement": "strong",
    "require_owner_attentive": true,
    "require_actor_unambiguous": true,
    "audit_required": true,
    "reason_codes": ["default_deny"],
    "policy_version": "step3-v1",
}

decision := {
    "allow": true,
    "required_trust": 0,
    "approval_requirement": "none",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": false,
    "reason_codes": [],
    "policy_version": "step3-v1",
} if input.risk_class == "ROUTINE"

decision := {
    "allow": true,
    "required_trust": 2,
    "approval_requirement": "direct_intent",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": true,
    "reason_codes": [],
    "policy_version": "step3-v1",
} if {
    input.risk_class == "PRIVATE_READ"
    input.proposal.origin == "direct_user"
}

decision := {
    "allow": true,
    "required_trust": 2,
    "approval_requirement": "explicit",
    "require_owner_attentive": true,
    "require_actor_unambiguous": true,
    "audit_required": true,
    "reason_codes": ["private_disclosure_not_directly_requested"],
    "policy_version": "step3-v1",
} if {
    input.risk_class == "PRIVATE_READ"
    input.proposal.origin != "direct_user"
}

decision := {
    "allow": true,
    "required_trust": 2,
    "approval_requirement": "direct_intent",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": true,
    "reason_codes": [],
    "policy_version": "step3-v1",
} if {
    input.risk_class == "REVERSIBLE_LOCAL_CHANGE"
    input.proposal.origin == "direct_user"
}

decision := {
    "allow": true,
    "required_trust": 2,
    "approval_requirement": "explicit",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": true,
    "reason_codes": ["reversible_change_not_directly_requested"],
    "policy_version": "step3-v1",
} if {
    input.risk_class == "REVERSIBLE_LOCAL_CHANGE"
    input.proposal.origin != "direct_user"
}

decision := {
    "allow": true,
    "required_trust": 2,
    "approval_requirement": "explicit",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": true,
    "reason_codes": [],
    "policy_version": "step3-v1",
} if input.risk_class == "PERSISTENT_OR_EXTERNAL"

decision := {
    "allow": true,
    "required_trust": 3,
    "approval_requirement": "strong",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": true,
    "reason_codes": [],
    "policy_version": "step3-v1",
} if input.risk_class == "CRITICAL"
