"""Owner acknowledgment of a closed capture; uncertainty and exposure survive."""

from dataclasses import asdict, dataclass

from jarvis.authority.types import ActionAttributes, ActionOrigin
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import CapabilityRequest
from jarvis.model_routing.budget import PaidBudgetDenied, _reservation
from jarvis.model_routing.live_budget_admin import LiveBudgetAdministration
from jarvis.model_routing.live_policy import digest, hash_ref, identity
from jarvis.model_routing.operational_budget import (
    _journal,
    _load,
    _refresh_admin_block,
)


@dataclass(frozen=True, slots=True)
class UnknownCaptureSnapshot:
    reservation_id: str
    target_id: str
    held_minor: int
    accounted_minor: int
    source_ref: str

    @property
    def fingerprint(self):
        return digest(asdict(self))


def _snapshot(g, c, rid):
    row, data = _load(g, c, identity(rid), owned=False)
    if (
        row["state"] not in {"uncertain", "acknowledged_unknown"}
        or data.get("capture_only") is not True
    ):
        raise PaidBudgetDenied(
            "Only a closed unknown qualification capture can be acknowledged"
        )
    block = c.execute(
        "SELECT blocked_reason FROM paid_fallback_budgets WHERE budget_id=?",
        (g.config.budget_id,),
    ).fetchone()[0]
    if block not in {None, "unknown_usage", "admin_audit_unresolved"}:
        raise PaidBudgetDenied("An unrelated budget block requires separate review")
    events = c.execute(
        "SELECT * FROM paid_fallback_usage_events WHERE reservation_id=? ORDER BY event_id",
        (rid,),
    ).fetchall()
    source = []
    closed = False
    for event in events:
        value = g.store.work_store.decode_extension_json(event["event_json"])
        if value.get("kind") in {
            "operational_admin_commit",
            "operational_admin_audited",
        }:
            continue
        if digest(value) != event["event_digest"]:
            raise PaidBudgetDenied("Capture journal digest mismatch")
        source.append(event["event_digest"])
        if (
            value.get("kind") == "operational_close"
            and value.get("teardown_confirmed") is True
        ):
            closed = True
    if not closed or row["accounted_minor"] > row["reserved_minor"]:
        raise PaidBudgetDenied("Confirmed close without an observed overrun required")
    return UnknownCaptureSnapshot(
        rid,
        row["target_id"],
        max(0, row["reserved_minor"] - row["accounted_minor"]),
        row["accounted_minor"],
        digest(
            {
                "journal": source,
                "policy": data["policy"],
                "profile": data["profile"],
                "price": g.store.work_store.decode_extension_json(row["price_json"]),
                "unknown_reason": data.get("unknown_reason"),
            }
        ),
    )


class UnknownUsageAdministration(LiveBudgetAdministration):
    def preview_unknown(self, reservation_id):
        with self.runtime.store.work_store.extension_transaction() as c:
            return _snapshot(self.runtime.paid_budget, c, reservation_id)

    def acknowledge_unknown(self, reservation_id, *, snapshot_ref, session_id):
        hash_ref(snapshot_ref)
        snapshot = self.preview_unknown(reservation_id)
        if snapshot.fingerprint != snapshot_ref:
            raise PaidBudgetDenied("Unknown capture snapshot changed; review again")
        refs = {
            "reservation_id": snapshot.reservation_id,
            "snapshot_ref": snapshot_ref,
            "held_minor": snapshot.held_minor,
            "accounted_minor": snapshot.accounted_minor,
            "target_id": snapshot.target_id,
        }
        prepared = PreparedCapability(
            request=CapabilityRequest(
                session_id=session_id,
                capability_key="system:paid_budget",
                operation="acknowledge_unknown",
                parameters=refs,
                origin=ActionOrigin.DIRECT_USER,
            ),
            target=refs,
            parameters=refs,
            material_summary=(
                "Acknowledge CLOSED qualification capture with UNKNOWN actual cost; "
                f"retain {snapshot.held_minor} INR minor units held, preserve all evidence; "
                "permit future separately approved Paid requests under the remaining budget. "
                "No usage reconciliation, profile qualification or invoice cap."
            ),
            attributes=ActionAttributes(financial_or_legal=True, persistent_write=True),
            execution_payload={},
        )
        b, authorization = self._authorize(prepared)
        g = self.runtime.paid_budget
        with g.store.work_store.extension_transaction() as c:
            c.execute("BEGIN IMMEDIATE")
            b.validate_binding(authorization)
            current = _snapshot(g, c, reservation_id)
            if current != snapshot:
                raise PaidBudgetDenied("Capture changed after owner approval")
            _journal(
                g,
                c,
                reservation_id,
                "paid-admin-" + authorization.proposal.proposal_id,
                {
                    "kind": "operational_admin_commit",
                    "operation": "acknowledge_unknown",
                    "evidence_ref": snapshot_ref,
                    "source_ref": snapshot.source_ref,
                    "held_minor": snapshot.held_minor,
                    "usage_remains_unknown": True,
                },
            )
            c.execute(
                "UPDATE paid_fallback_reservations SET state='acknowledged_unknown' WHERE reservation_id=?",
                (reservation_id,),
            )
            _refresh_admin_block(g, c)
            b.validate_binding(authorization)
            result = _reservation(
                c.execute(
                    "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
            )
        return self._finish(b, authorization, prepared, snapshot, result)
