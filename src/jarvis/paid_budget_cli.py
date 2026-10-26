"""Owner-local paid ledger inspection and exact-evidence administration."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from jarvis.model_routing.live_policy import (
    LiveReconciliationEvidence,
    LiveUsageProfile,
    LiveUsageReport,
)


def build_parser():
    p = argparse.ArgumentParser(
        description="Paid usage estimate, not provider invoice or cash balance"
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("reconcile", "qualify-profile"):
        command = sub.add_parser(name)
        command.add_argument("--evidence-file", type=Path, required=True)
        if name == "qualify-profile":
            command.add_argument("--profile-file", type=Path, required=True)
    recovery = sub.add_parser("acknowledge-unknown")
    recovery.add_argument("--reservation-id", required=True)
    recovery.add_argument("--snapshot-ref")
    recovery.add_argument("--execute", action="store_true")
    return p


def _read(path):
    if path.stat().st_size > 262144:
        raise ValueError("Evidence file too large")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None, *, administration=None):
    args = build_parser().parse_args(argv)
    owned = administration is None
    if owned:
        from jarvis.ai_provider import configured_ai_provider, resolve_ai_role_model
        from jarvis.machine_config import (
            default_machine_config_path,
            load_machine_settings,
        )
        from jarvis.model_routing.gemini import GeminiFallbackConfig
        from jarvis.model_routing.live_unknown_recovery import (
            UnknownUsageAdministration,
        )
        from jarvis.model_routing.runtime import build_routing_runtime
        from jarvis.work.privacy import build_default_work_payload_codec
        from jarvis.work.store import SQLiteWorkStore, default_work_store_path

        settings = load_machine_settings(default_machine_config_path())
        provider = configured_ai_provider(settings)
        store_path = default_work_store_path()
        runtime = build_routing_runtime(
            work_store=SQLiteWorkStore(
                store_path, payload_codec=build_default_work_payload_codec(store_path)
            ),
            provider=provider,
            model=resolve_ai_role_model(provider, "work_orchestration"),
            config=GeminiFallbackConfig.from_settings(settings),
        )
        administration = UnknownUsageAdministration(runtime, broker=None)
    try:
        if args.command == "status":
            from jarvis.model_routing.status import paid_live_ledger_status

            print(
                json.dumps(
                    dict(
                        label="Internal usage estimate; not provider invoice or cash balance",
                        **asdict(administration.runtime.paid_budget.status()),
                        operational_live=paid_live_ledger_status(
                            administration.runtime
                        ),
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "acknowledge-unknown":
            snapshot = administration.preview_unknown(args.reservation_id)
            if not args.execute:
                print(
                    json.dumps(
                        {
                            **asdict(snapshot),
                            "snapshot_ref": snapshot.fingerprint,
                            "status": "preview_only",
                            "actual_charge": "unknown",
                            "requires": "exact snapshot and fresh financial Windows Hello approval",
                        },
                        sort_keys=True,
                    )
                )
                return 0
            if not args.snapshot_ref:
                raise ValueError("--execute requires a reviewed --snapshot-ref")
            result = administration.acknowledge_unknown(
                args.reservation_id,
                snapshot_ref=args.snapshot_ref,
                session_id="paid-unknown-admin-" + uuid4().hex,
            )
            print(
                json.dumps(
                    {**asdict(result), "actual_charge": "unknown"}, sort_keys=True
                )
            )
            return 0
        values = _read(args.evidence_file)
        values["reports"] = tuple(LiveUsageReport(**r) for r in values["reports"])
        evidence = LiveReconciliationEvidence(**values)
        session_id = "paid-budget-admin-" + uuid4().hex
        if args.command == "reconcile":
            result = administration.reconcile(evidence, session_id=session_id)
        else:
            result = administration.qualify_profile(
                LiveUsageProfile.from_payload(_read(args.profile_file)),
                evidence=evidence,
                session_id=session_id,
            )
        print(
            json.dumps(
                asdict(result) if not isinstance(result, str) else {"receipt": result},
                sort_keys=True,
            )
        )
        return 0
    finally:
        if owned:
            if administration.broker is not None:
                administration.broker.close()
            import asyncio

            asyncio.run(administration.runtime.aclose())


if __name__ == "__main__":
    raise SystemExit(main())
