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
    not personal_learning_child
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
    not personal_learning_child
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
} if {
    input.risk_class == "PERSISTENT_OR_EXTERNAL"
    not personal_learning_child
}

personal_learning_child if {
    input.proposal.capability == "memory:personal_learning"
    input.proposal.operation in {"read", "admit"}
}

decision := {
    "allow": true,
    "required_trust": 2,
    "approval_requirement": "explicit",
    "require_owner_attentive": false,
    "require_actor_unambiguous": false,
    "audit_required": true,
    "reason_codes": ["registered_personal_learning_delegation"],
    "policy_version": "step3-personal-learning-v1",
} if {
    personal_learning_child
    input.risk_class in {"PRIVATE_READ", "PERSISTENT_OR_EXTERNAL"}
    input.proposal.origin == "system"
    input.approval.method == "delegated_policy"
    input.approval.parent_delegation_id != null
}

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
