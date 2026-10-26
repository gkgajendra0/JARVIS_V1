"""Explicit local experiments: exact financial Authority plus durable attempt bounds."""

import json
from dataclasses import dataclass
from pathlib import Path

from jarvis.authority.types import ActionAttributes, ActionOrigin
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.model_routing.live_policy import (
    LiveExperimentAuthorization,
    Payload,
    count,
    digest,
    hash_ref,
    identity,
    seconds,
)
from jarvis.model_routing.operational_budget import _journal, _load, _save


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveDiagnosticPlan(Payload):
    target_id: str
    model_id: str
    policy_ref: str
    price_ref: str
    profile_ref: str | None
    fixture_ref: str
    nonce: str
    faults: tuple[str, ...] = ()
    max_connections: int = 1
    max_generations: int = 1
    max_seconds: float = 15
    scope: str = "qualification_capture"

    def __post_init__(self):
        identity(self.target_id)
        identity(self.nonce)
        for value in (self.policy_ref, self.price_ref, self.fixture_ref):
            hash_ref(value)
        if self.profile_ref is not None:
            hash_ref(self.profile_ref)
        count(self.max_connections, positive=True)
        count(self.max_generations, positive=True)
        seconds(self.max_seconds)
        if (
            self.model_id != "gemini-3.8-live"
            or self.max_connections != 1
            or self.max_generations > 3
            or self.max_seconds > 45
            or self.scope not in {"qualification_capture", "whole_app_diagnostic"}
            or (
                self.scope == "qualification_capture"
                and (self.max_generations != 1 or self.max_seconds > 15)
            )
            or not isinstance(self.faults, (tuple, list))
            or len(self.faults) > 8
            or any(
                f
                not in {
                    "free_quota",
                    "free_recovery",
                    "paid_402",
                    "paid_auth",
                    "free_503",
                }
                for f in self.faults
            )
        ):
            raise ValueError("Unsupported or unbounded Live diagnostic plan")
        object.__setattr__(self, "faults", tuple(self.faults))


def load_live_diagnostic_plan(path: Path):
    if path.stat().st_size > 16384:
        raise ValueError("Bounded diagnostic plan required")
    return LiveDiagnosticPlan(**json.loads(path.read_text(encoding="utf-8")))


def authorize_live_experiment(runtime, plan, *, broker, session_id):
    if not isinstance(plan, LiveDiagnosticPlan):
        raise PaidBudgetDenied("Typed diagnostic plan required")
    prepared = PreparedCapability(
        request=CapabilityRequest(
            session_id=session_id,
            capability_key="system:paid_budget",
            operation="authorize_live_experiment",
            parameters=plan.to_payload(),
            origin=ActionOrigin.DIRECT_USER,
        ),
        target={"plan_ref": plan.fingerprint},
        parameters=plan.to_payload(),
        material_summary="Authorize one bounded Paid Live experiment; INR10 allowance, INR8 soft stop; incomplete usage retains the hold; invoice overrun remains possible",
        attributes=ActionAttributes(financial_or_legal=True, persistent_write=True),
        execution_payload={},
    )
    approved = broker.authorize_fresh_owner(prepared)
    broker.consume(approved)
    broker.audit_result(
        session_id=session_id,
        authorized=approved,
        result=CapabilityResult(
            CapabilityStatus.PARTIAL,
            "system:paid_budget",
            "authorize_live_experiment",
            {},
            reason="experiment_pre_reservation",
        ),
    )
    broker.validate_binding(approved)
    auth = LiveExperimentAuthorization(
        approved.proposal.proposal_id,
        plan.fingerprint,
        session_id,
        float(runtime.clock()) + 120,
        plan.max_connections,
        plan.max_generations,
        plan.max_seconds,
        plan.price_ref,
        plan.policy_ref,
        plan.profile_ref,
        plan.fixture_ref,
        plan.scope,
        plan.nonce,
    )
    runtime.live_diagnostics = LiveDiagnostics(runtime, plan, auth, broker, approved)
    return auth


def install_live_diagnostics(runtime, plan, *, authorization):
    control = getattr(runtime, "live_diagnostics", None)
    if (
        not isinstance(control, LiveDiagnostics)
        or plan.fingerprint != control.plan.fingerprint
        or not control.validate(authorization)
    ):
        raise PaidBudgetDenied(
            "Exact current audited experiment authorization required"
        )
    return control


def configure_handoff_diagnostics(handoff, plan):
    from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
    from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission

    admission = handoff.paid_admission
    if (
        type(admission) is not OperationalLiveAdmission
        or plan.scope != "whole_app_diagnostic"
        or admission.policy.fingerprint != plan.policy_ref
        or admission.profile.fingerprint != plan.profile_ref
        or plan.target_id != "voice.live.gemini.paid." + admission.model_id
    ):
        raise PaidBudgetDenied(
            "Normal diagnostic needs a production-qualified exact operational admission"
        )
    broker = CapabilityAuthorityBroker()
    try:
        auth = authorize_live_experiment(
            handoff.runtime,
            plan,
            broker=broker,
            session_id=handoff.bridge.conversation.session_id,
        )
        install_live_diagnostics(handoff.runtime, plan, authorization=auth)
        admission.experiment_authorization = auth
        handoff.bridge.add_close_observer(broker.close)
    except BaseException:
        broker.close()
        raise


class LiveDiagnostics:
    def __init__(self, runtime, plan, auth, broker, approved):
        self.runtime, self.plan, self.auth = runtime, plan, auth
        self.broker, self.approved = broker, approved
        self.bound = False
        self.fault_index = 0

    def validate(self, auth):
        if auth != self.auth or float(self.runtime.clock()) >= auth.expires_at_epoch:
            return False
        self.broker.validate_binding(self.approved)
        return True

    def bind_parent(self, auth, reservation, price):
        if (
            not self.validate(auth)
            or self.bound
            or digest(price.to_payload()) != self.plan.price_ref
        ):
            raise PaidBudgetDenied("Experiment expired, rebound, or changed price")
        g = self.runtime.paid_budget
        with g.store.work_store.extension_transaction() as c:
            c.execute("BEGIN IMMEDIATE")
            row, data = _load(g, c, reservation.reservation_id)
            if (
                row["target_id"] != self.plan.target_id
                or row["state"] != "reserved"
                or digest(data["policy"]) != self.plan.policy_ref
                or (digest(data["profile"]) if data["profile"] else None)
                != self.plan.profile_ref
                or data.get("experiment") is not None
            ):
                raise PaidBudgetDenied("Experiment differs from the reserved parent")
            # Stable nonce is consumed across processes/restarts, attached to a real parent FK.
            _journal(
                g,
                c,
                reservation.reservation_id,
                "live-experiment-" + digest([g.config.budget_id, auth.nonce]),
                {"kind": "live_experiment_authorization", **auth.to_payload()},
            )
            data["experiment"] = auth.to_payload()
            data["experiment_generations"] = 0
            _save(g, c, reservation.reservation_id, data)
            if not self.validate(auth):
                raise PaidBudgetDenied("Experiment authority expired before commit")
        self.bound = True
        self.reservation_id = reservation.reservation_id

    async def inject_next(self, handoff):
        """Explicit transitions use the real router and its unchanged continuity guard."""
        if not self.validate(self.auth) or self.fault_index >= len(self.plan.faults):
            return False
        fault = self.plan.faults[self.fault_index]
        paid = handoff.current_target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        if fault.startswith("paid_") != paid and fault != "free_recovery":
            return False
        self.fault_index += 1
        from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind

        if fault == "free_recovery":
            # Never clear real health or reset clocks: use the existing safe demand boundary.
            return await handoff.maybe_recover_free()
        kind = {
            "free_quota": ProviderFailureKind.QUOTA_EXHAUSTED,
            "free_503": ProviderFailureKind.SERVICE_UNAVAILABLE,
            "paid_402": ProviderFailureKind.BALANCE_EXHAUSTED,
            "paid_auth": ProviderFailureKind.AUTHENTICATION_FAILED,
        }[fault]
        failure = ProviderFailure("gemini", kind)
        if paid:
            handoff.runtime.store.disable_paid_credential(
                failure=failure, now_epoch=float(self.runtime.clock())
            )
            handoff.current_model.retire()
            return False
        return await handoff.handle_failure(failure)
