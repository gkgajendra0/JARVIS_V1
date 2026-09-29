"""Owner-machine C6 shadow acceptance with zero model/API calls.

The harness reads canonical Work history, builds the bounded ContextPack, and emits
only aggregate size/provenance metrics.  It never prints raw Work payloads.
"""

from __future__ import annotations

import json

from jarvis.work.context import WorkContextAssembler
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


def _chars(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    )


def _legacy_steps(steps):
    return [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "summary": step.summary,
            "state": step.state.value,
            "input": step.input_data,
            "observation": step.observation,
            "error": step.error,
        }
        for step in steps[-12:]
    ]


def main() -> int:
    path = default_work_store_path()
    store = SQLiteWorkStore(
        path,
        payload_codec=build_default_work_payload_codec(path),
    )
    assembler = WorkContextAssembler()
    rows: list[dict[str, object]] = []

    for work in store.list(limit=500):
        steps = store.list_steps(work.work_id)
        if len(steps) < 4:
            continue
        pack = assembler.build(work=work, steps=steps)
        legacy = {"recent_steps": _legacy_steps(steps), "evidence": []}
        optimized = {
            "recent_steps": pack.recent_steps_payload(),
            "evidence": list(pack.evidence),
            "history_manifest": pack.history_manifest_payload(),
        }
        legacy_chars = _chars(legacy)
        optimized_chars = _chars(optimized)
        selected_ids = {step.step_id for step in pack.selected_steps}
        latest_retained = steps[-1].step_id in selected_ids
        reduction = (
            (legacy_chars - optimized_chars) * 100.0 / legacy_chars
            if legacy_chars
            else 0.0
        )
        rows.append(
            {
                "work_id": work.work_id,
                "work_type": work.work_type.value,
                "history_steps": len(steps),
                "legacy_chars": legacy_chars,
                "optimized_chars": optimized_chars,
                "reduction_percent": round(reduction, 2),
                "selected_steps": len(pack.selected_steps),
                "omitted_steps": pack.omitted_step_count,
                "latest_step_retained": latest_retained,
            }
        )

    rows.sort(
        key=lambda item: (
            -int(item["history_steps"]),
            str(item["work_id"]),
        )
    )
    evaluated = rows[:50]
    failures = [row for row in evaluated if not bool(row["latest_step_retained"])]
    reductions = [
        float(row["reduction_percent"])
        for row in evaluated
        if int(row["history_steps"]) > 12
    ]
    result = {
        "status": "PASS" if evaluated and not failures else "INCOMPLETE",
        "model_api_called": False,
        "production_routing_mutated": False,
        "work_store": str(path),
        "evaluated_work_items": len(evaluated),
        "long_history_items": len(reductions),
        "long_history_mean_reduction_percent": (
            round(sum(reductions) / len(reductions), 2) if reductions else None
        ),
        "latest_step_retention_failures": len(failures),
        "items": evaluated,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
