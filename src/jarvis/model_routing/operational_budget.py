"""Private operational transactions; PaidBudgetGovernor owns all entry points."""

from dataclasses import asdict

from jarvis.model_routing.budget import (
    PaidBudgetDenied,
    PaidOutcomeUnknown,
    _reservation,
)
from jarvis.model_routing.live_policy import (
    DIMENSIONS,
    LiveTriggerPermit,
    LiveUsageProfile,
    LiveUsageReport,
    OperationalBudgetObservation,
    OperationalLivePolicy,
    digest,
    identity,
)
from jarvis.model_routing.pricing import PricingSnapshot
from jarvis.model_routing.process_identity import (
    RoutingProcessIdentity,
    current_process_identity,
    process_identity_alive,
)


def _load(g, c, rid, *, owned=True):
    row = c.execute(
        "SELECT * FROM paid_fallback_reservations WHERE reservation_id=? AND budget_id=?",
        (rid, g.config.budget_id),
    ).fetchone()
    if row is None or row["admission_kind"] != "operational_live_v1":
        raise PaidBudgetDenied("Operational reservation required")
    data = g.store.work_store.decode_extension_json(row["operational_json"])
    if owned and data["owner"] != asdict(current_process_identity()):
        raise PaidOutcomeUnknown(
            "Operational connection belongs to another process incarnation"
        )
    return row, data


def _save(g, c, rid, data):
    c.execute(
        "UPDATE paid_fallback_reservations SET operational_json=? WHERE reservation_id=?",
        (g.store.work_store.encode_extension_json(data), rid),
    )


def _journal(g, c, rid, event_id, payload):
    identity(event_id)
    hashed = digest(payload)
    old = c.execute(
        "SELECT * FROM paid_fallback_usage_events WHERE event_id=?", (event_id,)
    ).fetchone()
    if old:
        if old["reservation_id"] != rid or old["event_digest"] != hashed:
            raise PaidBudgetDenied("Operational event collision")
        return False
    c.execute(
        "INSERT INTO paid_fallback_usage_events VALUES (?,?,?,?)",
        (event_id, rid, hashed, g.store.work_store.encode_extension_json(payload)),
    )
    return True


def _unknown(g, c, rid, data, reason):
    data["unknown_reason"] = reason
    c.execute(
        "UPDATE paid_fallback_reservations SET state='uncertain' WHERE reservation_id=?",
        (rid,),
    )
    c.execute(
        "UPDATE paid_fallback_budgets SET blocked_reason=COALESCE(blocked_reason,'unknown_usage') WHERE budget_id=?",
        (g.config.budget_id,),
    )
    _save(g, c, rid, data)


def recover(g):
    found = []
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT reservation_id,operational_json FROM paid_fallback_reservations WHERE budget_id=? AND admission_kind='operational_live_v1' AND state IN ('reserved','dispatched')",
            (g.config.budget_id,),
        ).fetchall()
        for row in rows:
            data = g.store.work_store.decode_extension_json(row["operational_json"])
            alive = process_identity_alive(RoutingProcessIdentity(**data["owner"]))
            if alive is not True:
                _unknown(g, c, row["reservation_id"], data, "orphan_or_uncertain_owner")
                found.append(row["reservation_id"])
    return tuple(found)


def reserve(
    g, *, invocation_id, target, pricing, policy, profile, scope_id, capture_only
):
    identity(invocation_id)
    identity(scope_id)
    if not isinstance(policy, OperationalLivePolicy) or not isinstance(
        pricing, PricingSnapshot
    ):
        raise PaidBudgetDenied("Typed policy and pricing required")
    if type(capture_only) is not bool or (profile is None and not capture_only):
        raise PaidBudgetDenied("Qualified usage interpretation required")
    if profile is not None and (
        not isinstance(profile, LiveUsageProfile)
        or profile.config_ref != policy.fingerprint
        or profile.model_id != policy.model_id
    ):
        raise PaidBudgetDenied("Reporting policy/model binding changed")
    if (
        not g.config.enabled
        or not target.enabled
        or target.provider_id != "gemini"
        or target.credential_ref != "JARVIS_GEMINI_PAID_API_KEY"
        or target.model_id != policy.model_id
        or "realtime_voice" not in target.capabilities
        or pricing.service_key != "live"
        or set(pricing.rates()) != set(DIMENSIONS)
    ):
        raise PaidBudgetDenied(
            "Eligible exact Paid Live target and full rates required"
        )
    now = float(g.clock())
    pricing.quote({k: 0 for k in DIMENSIONS}, now_epoch=now, target=target)
    binding = digest(
        {
            "budget": g.config.budget_id,
            "target": target.target_id,
            "credential": target.credential_ref,
            "scope": scope_id,
            "pricing": pricing.to_payload(),
            "policy": policy.to_payload(),
            "profile": profile.to_payload() if profile else None,
            "capture_only": capture_only,
        }
    )
    recover(g)
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        old = c.execute(
            "SELECT * FROM paid_fallback_reservations WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if old:
            if old["binding_digest"] != binding:
                raise PaidBudgetDenied("Operational identity already bound")
            return _reservation(old)
        b = c.execute(
            "SELECT * FROM paid_fallback_budgets WHERE budget_id=?",
            (g.config.budget_id,),
        ).fetchone()
        pending = c.execute(
            "SELECT COALESCE(SUM(MAX(0,reserved_minor-accounted_minor)),0) FROM paid_fallback_reservations WHERE budget_id=? AND state NOT IN ('settled','cancelled')",
            (g.config.budget_id,),
        ).fetchone()[0]
        active = c.execute(
            "SELECT 1 FROM paid_fallback_reservations WHERE budget_id=? AND admission_kind='operational_live_v1' AND state IN ('reserved','dispatched','uncertain')",
            (g.config.budget_id,),
        ).fetchone()
        if (
            b["blocked_reason"]
            or active
            or b["spent_minor"] + pending + policy.allowance_minor > b["ceiling_minor"]
        ):
            raise PaidBudgetDenied(
                "Operational allowance blocked/exhausted or already active"
            )
        rid = "paid-reservation-" + digest([g.config.budget_id, invocation_id])
        data = {
            "policy": policy.to_payload(),
            "profile": profile.to_payload() if profile else None,
            "owner": asdict(current_process_identity()),
            "capture_only": capture_only,
            "triggers": {},
            "rounds": {},
            "current_round": None,
            "continuations": 0,
            "used_tools": [],
            "unknown_reason": None,
        }
        c.execute(
            """INSERT INTO paid_fallback_reservations (
            reservation_id,invocation_id,budget_id,target_id,scope_kind,scope_id,binding_digest,
            price_profile_id,price_version,price_json,reserved_at,reserved_minor,state,admission_kind,operational_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                invocation_id,
                g.config.budget_id,
                target.target_id,
                "voice",
                scope_id,
                binding,
                pricing.profile.profile_id,
                pricing.profile.version,
                g.store.work_store.encode_extension_json(pricing.to_payload()),
                now,
                policy.allowance_minor,
                "reserved",
                "operational_live_v1",
                g.store.work_store.encode_extension_json(data),
            ),
        )
        return _reservation(
            c.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (rid,),
            ).fetchone()
        )


def checkpoint(g, *, reservation_id, trigger_id, kind, round_id, tool_call_ids):
    identity(trigger_id)
    identity(round_id)
    if kind not in {"setup", "history", "initial", "tool"}:
        raise PaidBudgetDenied("Unknown Live charging trigger")
    if (
        not isinstance(tool_call_ids, tuple)
        or len(tool_call_ids) > 32
        or len(set(tool_call_ids)) != len(tool_call_ids)
    ):
        raise PaidBudgetDenied("Bounded unique tool identities required")
    for call in tool_call_ids:
        identity(call)
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        row, data = _load(g, c, reservation_id)
        p = OperationalLivePolicy(**data["policy"])
        experiment = data.get("experiment")
        if experiment:
            now = float(g.clock())
            if now >= min(
                experiment["expires_at_epoch"],
                row["reserved_at"] + experiment["max_seconds"] - 3,
            ):
                raise PaidBudgetDenied("Experiment deadline expired")
            if kind in {"initial", "tool"}:
                if data["experiment_generations"] >= experiment["max_generations"]:
                    raise PaidBudgetDenied("Experiment generation limit exhausted")
                data["experiment_generations"] += 1
        if (
            row["state"] not in {"reserved", "dispatched"}
            or trigger_id in data["triggers"]
        ):
            raise PaidOutcomeUnknown(
                "Trigger already used or connection uncertain/closed"
            )
        b = c.execute(
            "SELECT blocked_reason FROM paid_fallback_budgets WHERE budget_id=?",
            (g.config.budget_id,),
        ).fetchone()
        price = PricingSnapshot.from_payload(
            g.store.work_store.decode_extension_json(row["price_json"])
        )
        price.validate_at(float(g.clock()))
        elapsed = float(g.clock()) - row["reserved_at"]
        if (
            b[0]
            or row["accounted_minor"] >= p.soft_stop_minor
            or not 0 <= elapsed < p.max_physical_seconds - 3
        ):
            raise PaidBudgetDenied("Live trigger budget/deadline exhausted")
        current = data["current_round"]
        if kind in {"setup", "history"}:
            if current is not None or any(
                t["kind"] == kind for t in data["triggers"].values()
            ):
                raise PaidBudgetDenied(
                    "Setup/history cannot replay or follow a generation"
                )
        else:
            if kind == "initial" and current is not None:
                raise PaidBudgetDenied("Initial generation cannot repeat")
            if kind == "tool":
                if (
                    data["capture_only"]
                    or current is None
                    or not data["rounds"][current]["complete"]
                    or data["continuations"] >= p.max_tool_continuations
                    or not tool_call_ids
                    or set(tool_call_ids) & set(data["used_tools"])
                ):
                    raise PaidBudgetDenied(
                        "Tool continuation lacks complete prior usage or fresh identity"
                    )
                data["continuations"] += 1
                data["used_tools"].extend(tool_call_ids)
            if round_id in data["rounds"]:
                raise PaidBudgetDenied("Round identity cannot reset")
            data["rounds"][round_id] = {"usage": {}, "complete": False, "sequence": -1}
            data["current_round"] = round_id
        payload = {
            "kind": kind,
            "round_id": round_id,
            "tool_call_ids": list(tool_call_ids),
        }
        data["triggers"][trigger_id] = payload
        _journal(
            g,
            c,
            reservation_id,
            "live-trigger-" + digest([reservation_id, trigger_id]),
            payload,
        )
        c.execute(
            "UPDATE paid_fallback_reservations SET state='dispatched' WHERE reservation_id=?",
            (reservation_id,),
        )
        _save(g, c, reservation_id, data)
        return LiveTriggerPermit(
            reservation_id,
            trigger_id,
            kind,
            round_id,
            p.fingerprint,
            LiveUsageProfile.from_payload(data["profile"]).fingerprint
            if data["profile"]
            else None,
        )


def _observation(row, data):
    return OperationalBudgetObservation(
        row["accounted_minor"],
        max(0, row["reserved_minor"] - row["accounted_minor"]),
        bool(
            data["unknown_reason"]
            or row["accounted_minor"] >= data["policy"]["soft_stop_minor"]
        ),
        data["unknown_reason"],
    )


def observe(g, *, reservation_id, report, event_id, diagnostics=None):
    if not isinstance(report, LiveUsageReport):
        raise TypeError("Typed usage report required")
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        row, data = _load(g, c, reservation_id)
        payload = {"kind": "operational_usage", "report": report.to_payload()}
        if diagnostics is not None:
            from jarvis.model_routing.live_usage_evidence import (
                validate_usage_diagnostics,
            )

            payload["diagnostics"] = validate_usage_diagnostics(diagnostics)
        if not _journal(g, c, reservation_id, event_id, payload):
            return _observation(row, data)
        if row["state"] not in {"dispatched", "uncertain"}:
            raise PaidOutcomeUnknown("No active operational generation")
        prior = data["rounds"].get(report.round_id)
        profile = (
            LiveUsageProfile.from_payload(data["profile"]) if data["profile"] else None
        )
        invalid = (
            report.unknown_reason
            or prior is None
            or report.round_id != data["current_round"]
            or profile is None
            or report.profile_ref != profile.fingerprint
        )
        if not invalid:
            invalid = report.sequence <= prior["sequence"] or any(
                v < prior["usage"].get(k, 0) for k, v in report.usage.items()
            )
        if invalid:
            _unknown(g, c, reservation_id, data, "unattributable_or_regressing_usage")
            return _observation(row, data)
        merged = prior["usage"] | dict(report.usage)
        candidate = {
            "usage": merged,
            "complete": report.complete,
            "sequence": report.sequence,
        }
        total = {k: 0 for k in DIMENSIONS}
        if profile.counter_scope == "generation":
            for key, round_data in data["rounds"].items():
                for k, v in (candidate if key == report.round_id else round_data)[
                    "usage"
                ].items():
                    total[k] += v
        else:
            # Omission is not zero. Retain the established connection lower
            # bound across rounds, checking decreases only when reported.
            for key, round_data in data["rounds"].items():
                if key != report.round_id:
                    for k, v in round_data["usage"].items():
                        if k in merged and merged[k] < v:
                            _unknown(
                                g,
                                c,
                                reservation_id,
                                data,
                                "regressing_connection_usage",
                            )
                            return _observation(row, data)
                        total[k] = max(total[k], v)
            total.update(merged)
            candidate["usage"] = dict(total)
        price = PricingSnapshot.from_payload(
            g.store.work_store.decode_extension_json(row["price_json"])
        )
        amount = price.quote_usage(total, now_epoch=row["reserved_at"])
        if amount < row["accounted_minor"]:
            _unknown(g, c, reservation_id, data, "regressing_cost")
            return _observation(row, data)
        data["rounds"][report.round_id] = candidate
        c.execute(
            "UPDATE paid_fallback_budgets SET spent_minor=spent_minor+? WHERE budget_id=?",
            (amount - row["accounted_minor"], g.config.budget_id),
        )
        c.execute(
            "UPDATE paid_fallback_reservations SET accounted_minor=? WHERE reservation_id=?",
            (amount, reservation_id),
        )
        if amount > row["reserved_minor"]:
            c.execute(
                "UPDATE paid_fallback_budgets SET blocked_reason='observed_overrun' WHERE budget_id=?",
                (g.config.budget_id,),
            )
        _save(g, c, reservation_id, data)
        fresh = c.execute(
            "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        return _observation(fresh, data)


def finish(g, *, reservation_id, complete, teardown_confirmed, event_id):
    if type(complete) is not bool or type(teardown_confirmed) is not bool:
        raise TypeError("Explicit completion/teardown required")
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        row, data = _load(g, c, reservation_id)
        if not _journal(
            g,
            c,
            reservation_id,
            event_id,
            {
                "kind": "operational_close",
                "complete": complete,
                "teardown_confirmed": teardown_confirmed,
            },
        ):
            return _reservation(row)
        if row["state"] not in {"dispatched", "uncertain"}:
            raise PaidOutcomeUnknown("No dispatched operational connection to close")
        if (
            complete
            and teardown_confirmed
            and not data["unknown_reason"]
            and data["rounds"]
            and all(r["complete"] for r in data["rounds"].values())
            and not data["capture_only"]
        ):
            c.execute(
                "UPDATE paid_fallback_reservations SET state='settled' WHERE reservation_id=?",
                (reservation_id,),
            )
        else:
            _unknown(g, c, reservation_id, data, "incomplete_terminal_usage_or_close")
        return _reservation(
            c.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
        )


def _evidence_binding(g, c, evidence):
    from jarvis.model_routing.live_policy import LiveReconciliationEvidence

    if not isinstance(evidence, LiveReconciliationEvidence):
        raise PaidBudgetDenied("Typed attributable reconciliation evidence required")
    row, data = _load(g, c, evidence.reservation_id, owned=False)
    if row["state"] not in {"uncertain", "acknowledged_unknown", "settled"}:
        raise PaidBudgetDenied("Active connection cannot be administratively settled")
    profile = (
        LiveUsageProfile.from_payload(data["profile"]) if data["profile"] else None
    )
    price = PricingSnapshot.from_payload(
        g.store.work_store.decode_extension_json(row["price_json"])
    )
    if (
        evidence.target_id != row["target_id"]
        or evidence.policy_ref != digest(data["policy"])
        or profile is None
        or evidence.profile_ref != profile.fingerprint
        or evidence.price_ref != digest(price.to_payload())
    ):
        raise PaidBudgetDenied(
            "Reconciliation binding does not match original reservation"
        )
    events = c.execute(
        "SELECT * FROM paid_fallback_usage_events WHERE reservation_id=? ORDER BY event_id",
        (evidence.reservation_id,),
    ).fetchall()
    values = [g.store.work_store.decode_extension_json(e["event_json"]) for e in events]
    attributable = [
        (e, v)
        for e, v in zip(events, values, strict=True)
        if v.get("kind") in {"operational_usage", "operational_close"}
    ]
    reports = [v["report"] for _, v in attributable if v["kind"] == "operational_usage"]
    if (
        digest([e["event_digest"] for e, _ in attributable]) != evidence.source_digest
        or reports != [r.to_payload() for r in evidence.reports]
        or not any(
            v.get("teardown_confirmed") is True
            for _, v in attributable
            if v["kind"] == "operational_close"
        )
    ):
        raise PaidBudgetDenied(
            "Exact per-connection usage and confirmed close evidence required"
        )
    latest = {}
    for r in evidence.reports:
        if r.profile_ref != profile.fingerprint or r.unknown_reason:
            raise PaidBudgetDenied("Unqualified usage evidence")
        if r.round_id not in latest or r.sequence > latest[r.round_id].sequence:
            latest[r.round_id] = r
    if set(latest) != set(data["rounds"]) or not all(
        r.complete for r in latest.values()
    ):
        raise PaidBudgetDenied("Every billed round needs terminal evidence")
    totals = {k: 0 for k in DIMENSIONS}
    if profile.counter_scope == "generation":
        for r in latest.values():
            for k, v in r.usage.items():
                totals[k] += v
    else:
        totals.update(max(latest.values(), key=lambda r: r.sequence).usage)
    if not any(totals.values()):
        raise PaidBudgetDenied("Zero guess cannot clear an unknown billed connection")
    return row, data, profile, price, totals


def _refresh_admin_block(g, c):
    budget = c.execute(
        "SELECT blocked_reason FROM paid_fallback_budgets WHERE budget_id=?",
        (g.config.budget_id,),
    ).fetchone()
    if budget[0] == "observed_overrun":
        return
    unknown = c.execute(
        "SELECT 1 FROM paid_fallback_reservations WHERE budget_id=? AND state='uncertain'",
        (g.config.budget_id,),
    ).fetchone()
    events = c.execute(
        "SELECT u.* FROM paid_fallback_usage_events u JOIN paid_fallback_reservations r ON r.reservation_id=u.reservation_id WHERE r.budget_id=?",
        (g.config.budget_id,),
    ).fetchall()
    commits = {}
    acked = set()
    for e in events:
        v = g.store.work_store.decode_extension_json(e["event_json"])
        if v.get("kind") == "operational_admin_commit":
            commits[e["event_id"]] = v
        if v.get("kind") == "operational_admin_audited":
            acked.update(v["commit_ids"])
    reason = (
        "admin_audit_unresolved"
        if set(commits) - acked
        else ("unknown_usage" if unknown else None)
    )
    c.execute(
        "UPDATE paid_fallback_budgets SET blocked_reason=? WHERE budget_id=?",
        (reason, g.config.budget_id),
    )


def reconcile(g, *, evidence, validate_owner, administrative_action_id):
    if not callable(validate_owner):
        raise TypeError("Exact fresh financial owner validation required")
    identity(administrative_action_id)
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        validate_owner()
        row, data, _profile, price, totals = _evidence_binding(g, c, evidence)
        amount = price.quote_usage(totals, now_epoch=row["reserved_at"])
        if amount < row["accounted_minor"]:
            raise PaidBudgetDenied(
                "Administrative evidence cannot reduce accounted spend"
            )
        commit_id = "paid-admin-" + administrative_action_id
        _journal(
            g,
            c,
            row["reservation_id"],
            commit_id,
            {
                "kind": "operational_admin_commit",
                "operation": "reconcile",
                "evidence_ref": evidence.fingerprint,
                "source_ref": evidence.source_digest,
            },
        )
        c.execute(
            "UPDATE paid_fallback_budgets SET spent_minor=spent_minor+? WHERE budget_id=?",
            (amount - row["accounted_minor"], g.config.budget_id),
        )
        c.execute(
            "UPDATE paid_fallback_reservations SET accounted_minor=?,state='settled' WHERE reservation_id=?",
            (amount, row["reservation_id"]),
        )
        data["unknown_reason"] = None
        _save(g, c, row["reservation_id"], data)
        if amount > row["reserved_minor"]:
            c.execute(
                "UPDATE paid_fallback_budgets SET blocked_reason='observed_overrun' WHERE budget_id=?",
                (g.config.budget_id,),
            )
        _refresh_admin_block(g, c)
        validate_owner()
        return _reservation(
            c.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (row["reservation_id"],),
            ).fetchone()
        )


def complete_admin_audit(
    g, *, reservation_id, evidence_ref, action_id, operation, validate_owner
):
    with g.store.work_store.extension_transaction() as c:
        c.execute("BEGIN IMMEDIATE")
        validate_owner()
        row, _ = _load(g, c, reservation_id, owned=False)
        commits = []
        for e in c.execute(
            "SELECT * FROM paid_fallback_usage_events WHERE reservation_id=?",
            (reservation_id,),
        ):
            v = g.store.work_store.decode_extension_json(e["event_json"])
            if (
                v.get("kind") == "operational_admin_commit"
                and v.get("evidence_ref") == evidence_ref
                and v.get("operation") == operation
            ):
                commits.append(e["event_id"])
        if not commits:
            raise PaidBudgetDenied("No exact administrative commit to acknowledge")
        _journal(
            g,
            c,
            row["reservation_id"],
            "paid-admin-audit-" + action_id,
            {
                "kind": "operational_admin_audited",
                "commit_ids": sorted(commits),
                "evidence_ref": evidence_ref,
            },
        )
        _refresh_admin_block(g, c)
        validate_owner()
