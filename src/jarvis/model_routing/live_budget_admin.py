"""Local exact-action administration through the canonical financial Authority."""

from importlib.metadata import version
from urllib.parse import urlsplit

from jarvis.authority.types import ActionAttributes, ActionOrigin
from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.model_routing.live_policy import LiveUsageProfile, digest
from jarvis.model_routing.operational_budget import (
    _evidence_binding,
    _journal,
    _refresh_admin_block,
    complete_admin_audit,
)


def _profile_sources(profile, price):
    if (
        not isinstance(profile, LiveUsageProfile)
        or "synthetic" in price.source.casefold()
        or not profile.sdk_versions
        or "google-genai" not in profile.sdk_versions
        or any(
            urlsplit(r).hostname not in {"ai.google.dev", "docs.cloud.google.com"}
            for r in profile.source_refs
        )
    ):
        raise PaidBudgetDenied("Actual reviewed provider reporting sources required")
    for package, pinned in profile.sdk_versions.items():
        try:
            installed = version(package)
        except Exception as exc:
            raise PaidBudgetDenied("Reporting SDK is unavailable") from exc
        if installed != pinned:
            raise PaidBudgetDenied("Reporting SDK version changed")


def _validated_capture(runtime, c, evidence, profile):
    row, data, bound, price, _ = _evidence_binding(runtime.paid_budget, c, evidence)
    _profile_sources(profile, price)
    if not data["capture_only"] or bound.fingerprint != profile.fingerprint:
        raise PaidBudgetDenied(
            "Attributable real capture for this exact profile required"
        )
    authorizations = []
    for e in c.execute(
        "SELECT event_json FROM paid_fallback_usage_events WHERE reservation_id=?",
        (evidence.reservation_id,),
    ):
        v = runtime.store.work_store.decode_extension_json(e[0])
        if v.get("kind") == "live_experiment_authorization":
            authorizations.append(v)
    if not any(
        a.get("scope") == "qualification_capture"
        and a.get("profile_ref") == profile.fingerprint
        and a.get("policy_ref") == evidence.policy_ref
        for a in authorizations
    ):
        raise PaidBudgetDenied(
            "Captured experiment lacks its exact audited financial authorization"
        )
    return row, data, price


class LiveBudgetAdministration:
    def __init__(self, runtime, *, broker=None):
        self.runtime = runtime
        self.broker = broker

    def _broker(self):
        if self.broker is None:
            self.broker = CapabilityAuthorityBroker()
        return self.broker

    def _prepare(self, evidence, *, session_id, operation, profile=None):
        from jarvis.model_routing.live_policy import LiveReconciliationEvidence

        if not isinstance(evidence, LiveReconciliationEvidence):
            raise TypeError("Typed exact evidence required")
        refs = {
            "reservation_id": evidence.reservation_id,
            "evidence_ref": evidence.fingerprint,
            "policy_ref": evidence.policy_ref,
            "price_ref": evidence.price_ref,
            "profile_ref": evidence.profile_ref,
        }
        if profile is not None:
            refs["qualified_profile_ref"] = profile.fingerprint
        return PreparedCapability(
            request=CapabilityRequest(
                session_id=session_id,
                capability_key="system:paid_budget",
                operation=operation,
                parameters=refs,
                origin=ActionOrigin.DIRECT_USER,
            ),
            target=refs,
            parameters=refs,
            material_summary="Review exact Paid Live usage evidence and "
            + operation
            + "; no budget reset or activation",
            attributes=ActionAttributes(financial_or_legal=True, persistent_write=True),
            execution_payload={},
        )

    def prepare_reconciliation(self, evidence, *, session_id):
        return self._prepare(evidence, session_id=session_id, operation="reconcile")

    def _authorize(self, prepared):
        b = self._broker()
        a = b.authorize_fresh_owner(prepared)
        b.consume(a)
        b.audit_result(
            session_id=prepared.request.session_id,
            authorized=a,
            result=CapabilityResult(
                CapabilityStatus.PARTIAL,
                "system:paid_budget",
                prepared.request.operation,
                {},
                reason="paid_admin_pre_mutation",
            ),
        )
        b.validate_binding(a)
        return b, a

    def _finish(self, b, a, prepared, evidence, result):
        b.audit_result(
            session_id=prepared.request.session_id,
            authorized=a,
            result=CapabilityResult(
                CapabilityStatus.SUCCEEDED,
                "system:paid_budget",
                prepared.request.operation,
                {},
                reason="paid_admin_committed",
            ),
        )
        complete_admin_audit(
            self.runtime.paid_budget,
            reservation_id=evidence.reservation_id,
            evidence_ref=evidence.fingerprint,
            action_id=a.proposal.proposal_id,
            operation=prepared.request.operation,
            validate_owner=lambda: b.validate_binding(a),
        )
        return result

    def reconcile(self, evidence, *, session_id):
        prepared = self.prepare_reconciliation(evidence, session_id=session_id)
        b, a = self._authorize(prepared)
        r = self.runtime.paid_budget.reconcile_operational_live(
            evidence=evidence,
            validate_owner=lambda: b.validate_binding(a),
            administrative_action_id=a.proposal.proposal_id,
        )
        return self._finish(b, a, prepared, evidence, r)

    def qualify_profile(self, profile, *, evidence, session_id):
        # Source qualification is independent of whether the owner consents.
        with self.runtime.store.work_store.extension_transaction() as c:
            _validated_capture(self.runtime, c, evidence, profile)
        prepared = self._prepare(
            evidence,
            session_id=session_id,
            operation="qualify_profile",
            profile=profile,
        )
        b, a = self._authorize(prepared)
        receipt = "live-profile-" + a.proposal.proposal_id
        g = self.runtime.paid_budget
        with g.store.work_store.extension_transaction() as c:
            c.execute("BEGIN IMMEDIATE")
            b.validate_binding(a)
            _row, _, price = _validated_capture(self.runtime, c, evidence, profile)
            _journal(
                g,
                c,
                evidence.reservation_id,
                "paid-admin-" + a.proposal.proposal_id,
                {
                    "kind": "operational_admin_commit",
                    "operation": "qualify_profile",
                    "evidence_ref": evidence.fingerprint,
                },
            )
            _journal(
                g,
                c,
                evidence.reservation_id,
                receipt,
                {
                    "kind": "live_profile_qualified",
                    "profile": profile.to_payload(),
                    "evidence_ref": evidence.fingerprint,
                    "policy_ref": evidence.policy_ref,
                    "price_ref": evidence.price_ref,
                    "target_id": evidence.target_id,
                    "expires_at": min(
                        price.profile.effective_to_epoch, price.fx_effective_to_epoch
                    ),
                    "admin_commit_id": "paid-admin-" + a.proposal.proposal_id,
                },
            )
            _refresh_admin_block(g, c)
            b.validate_binding(a)
        return self._finish(b, a, prepared, evidence, receipt)


def resolve_qualified_live_profile(runtime, *, policy):
    g = runtime.paid_budget
    with runtime.store.work_store.extension_transaction() as c:
        rows = c.execute(
            "SELECT u.* FROM paid_fallback_usage_events u JOIN paid_fallback_reservations r ON r.reservation_id=u.reservation_id WHERE r.budget_id=?",
            (g.config.budget_id,),
        ).fetchall()
        values = [
            runtime.store.work_store.decode_extension_json(e["event_json"])
            for e in rows
        ]
        acked = set()
        for v in values:
            if v.get("kind") == "operational_admin_audited":
                acked.update(v["commit_ids"])
        for v in reversed(values):
            if (
                v.get("kind") != "live_profile_qualified"
                or v.get("policy_ref") != policy.fingerprint
                or v.get("admin_commit_id") not in acked
                or float(runtime.clock()) >= v.get("expires_at", 0)
            ):
                continue
            try:
                p = LiveUsageProfile.from_payload(v["profile"])
                row = c.execute(
                    "SELECT price_json,admission_kind FROM paid_fallback_reservations WHERE reservation_id=?",
                    (
                        next(
                            e["reservation_id"]
                            for e, val in zip(rows, values, strict=True)
                            if val is v
                        ),
                    ),
                ).fetchone()
                from jarvis.model_routing.pricing import PricingSnapshot

                price = PricingSnapshot.from_payload(
                    runtime.store.work_store.decode_extension_json(row["price_json"])
                )
                _profile_sources(p, price)
                price.validate_at(float(runtime.clock()))
                if (
                    p.config_ref != policy.fingerprint
                    or digest(price.to_payload()) != v["price_ref"]
                ):
                    continue
                return p
            except (ValueError, TypeError, KeyError, PaidBudgetDenied):
                continue
    return None


def export_capture_diagnostics(runtime, *, reservation_id):
    """Read existing capture facts without guessing old or incomplete metadata."""
    g = runtime.paid_budget
    with g.store.work_store.extension_transaction() as c:
        row = c.execute(
            "SELECT * FROM paid_fallback_reservations WHERE reservation_id=? AND budget_id=?",
            (reservation_id, g.config.budget_id),
        ).fetchone()
        if row is None or row["admission_kind"] != "operational_live_v1":
            raise PaidBudgetDenied("Original operational parent required")
        data = g.store.work_store.decode_extension_json(row["operational_json"])
        events = [
            g.store.work_store.decode_extension_json(e[0])
            for e in c.execute(
                "SELECT event_json FROM paid_fallback_usage_events WHERE reservation_id=? ORDER BY event_id",
                (reservation_id,),
            )
        ]
        reports = [v["report"] for v in events if v.get("kind") == "operational_usage"]
        diagnostics = [
            v["diagnostics"]
            for v in events
            if v.get("kind") == "operational_usage" and v.get("diagnostics") is not None
        ]
        return {
            "reservation_id": reservation_id,
            "target_id": row["target_id"],
            "state": row["state"],
            "unknown_reason": data.get("unknown_reason"),
            "teardown_confirmed": any(
                v.get("kind") == "operational_close"
                and v.get("teardown_confirmed") is True
                for v in events
            ),
            "usage_reports": reports,
            "numeric_metadata": diagnostics,
            "raw_numeric_metadata_available": bool(diagnostics),
        }


def export_reconciliation_evidence(runtime, *, reservation_id):
    """Export numeric, exactly journal-bound complete evidence; never invent missing usage."""
    from jarvis.model_routing.live_policy import (
        LiveReconciliationEvidence,
        LiveUsageReport,
    )

    g = runtime.paid_budget
    with g.store.work_store.extension_transaction() as c:
        row = c.execute(
            "SELECT * FROM paid_fallback_reservations WHERE reservation_id=? AND budget_id=?",
            (reservation_id, g.config.budget_id),
        ).fetchone()
        if row is None or row["admission_kind"] != "operational_live_v1":
            raise PaidBudgetDenied("Original operational parent required")
        data = g.store.work_store.decode_extension_json(row["operational_json"])
        events = c.execute(
            "SELECT * FROM paid_fallback_usage_events WHERE reservation_id=? ORDER BY event_id",
            (reservation_id,),
        ).fetchall()
        bound = [
            (e, g.store.work_store.decode_extension_json(e["event_json"]))
            for e in events
        ]
        attributable = [
            (e, v)
            for e, v in bound
            if v.get("kind") in {"operational_usage", "operational_close"}
        ]
        evidence = LiveReconciliationEvidence(
            reservation_id,
            row["target_id"],
            digest(data["policy"]),
            digest(data["profile"]),
            digest(g.store.work_store.decode_extension_json(row["price_json"])),
            tuple(
                LiveUsageReport(**v["report"])
                for _, v in attributable
                if v["kind"] == "operational_usage"
            ),
            digest([e["event_digest"] for e, _ in attributable]),
        )
        _evidence_binding(g, c, evidence)
        return evidence
