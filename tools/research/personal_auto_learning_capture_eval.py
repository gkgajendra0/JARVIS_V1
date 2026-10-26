"""Fresh capture-only subset. Default is zero-network; never release acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from tools.research import personal_auto_learning_eval as base

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "benchmarks/personal_auto_learning_capture_v2.json"
GOLD = ROOT / "benchmarks/personal_auto_learning_capture_v2_gold.json"
INPUT_HASH = "882441e59595d46b5f817cceb4940b691063cddd47414dff4ff6ba2508c2313b"
GOLD_HASH = "e59859a492803e582ba05339df2441adbd3dec86a722dda120f76a95a8f43488"
PRIOR_SEND_RESERVE = 205
MAX_NEW_SENDS = 65


def load_frozen_capture(*, inputs_path=INPUT, gold_path=GOLD):
    raw = Path(inputs_path).read_bytes()
    goldraw = Path(gold_path).read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != INPUT_HASH
        or hashlib.sha256(goldraw).hexdigest() != GOLD_HASH
    ):
        raise ValueError("frozen capture hash mismatch")
    inputs = json.loads(raw)
    gold = json.loads(goldraw)
    if inputs.get("fictional") is not True or len(inputs["episodes"]) != 45:
        raise ValueError("45 fictional episodes required")
    if len({e["id"] for e in inputs["episodes"]}) != 45:
        raise ValueError("unique cases required")
    required = {
        "id",
        "language",
        "turns",
        "seed",
        "question",
        "answer_subset",
        "control",
    }
    if any(set(e) != required or e["answer_subset"] for e in inputs["episodes"]):
        raise ValueError("gold leakage or answering enabled")
    if {
        lang: sum(e["language"] == lang for e in inputs["episodes"])
        for lang in ["en", "hi", "hinglish"]
    } != {"en": 15, "hi": 15, "hinglish": 15}:
        raise ValueError("language balance changed")
    return inputs, gold


def capture_scores(rows, gold):
    scores = base.score_rows(rows, gold)
    scores["preliminary_semantic_floor"] = bool(
        scores["completed"] == 45
        and not scores["unavailable"]
        and scores["precision"] is not None
        and scores["precision"] >= 0.95
        and scores["recall"] is not None
        and scores["recall"] >= 0.80
        and len(scores["languages"]) == 3
        and all(
            m["expected"] and m["captured"] / m["expected"] >= 0.70
            for m in scores["languages"].values()
        )
    )
    # This smaller subset cannot satisfy the approved full90/answer/owner gate.
    scores["quality_floor_pass"] = False
    return scores


async def _provider_cases(inputs, output_dir, budget):
    from jarvis.authority.local_opa import ManagedOpaServer
    from jarvis.config import JarvisConfig
    from jarvis.memory.learning_extractors import build_learning_adapters

    config = JarvisConfig.from_environment()
    adapter, _ = build_learning_adapters(config.ai_provider)
    base._instrument(adapter, budget)
    rows = []
    try:
        with ManagedOpaServer() as opa:
            for index, episode in enumerate(inputs["episodes"]):
                if index:
                    await asyncio.sleep(8)
                try:
                    with tempfile.TemporaryDirectory(
                        prefix="fictional-v2-", dir=output_dir
                    ) as folder:
                        row = await base._episode(
                            episode, adapter, opa.endpoint, Path(folder)
                        )
                except Exception as exc:  # noqa: BLE001 - sanitized research failure boundary
                    row = {
                        "id": episode["id"],
                        "status": "unavailable",
                        "reason": type(exc).__name__,
                        "predictions": [],
                    }
                rows.append(row)
                (output_dir / "progress.json").write_text(
                    json.dumps(
                        {
                            "rows": rows,
                            "single_send_calls": budget.attempts,
                            "conservative_cumulative_send_upper_bound": PRIOR_SEND_RESERVE
                            + budget.attempts,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(
                    json.dumps(
                        {
                            "id": episode["id"],
                            "status": row["status"],
                            "committed": row.get("committed_count"),
                            "single_send_calls": budget.attempts,
                            "last_failure": adapter.last_failure,
                        }
                    ),
                    flush=True,
                )
                if (
                    row["status"] != "completed" and row.get("reason") != "timeout"
                ) or adapter.last_failure:
                    break
    finally:
        await adapter.close()
    return rows, {
        "provider": adapter.provider,
        "model": adapter.model_name,
        "usage": adapter.usage,
        "last_failure": adapter.last_failure,
    }


def run_capture_eval(
    output_dir, *, allow_provider=False, max_single_send_calls=MAX_NEW_SENDS
):
    if (
        type(max_single_send_calls) is not int
        or not 0 <= max_single_send_calls <= MAX_NEW_SENDS
    ):
        raise ValueError("remaining single-send cap must be0..65")
    inputs, gold = load_frozen_capture()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    budget = base.AttemptBudget(max_single_send_calls)
    take = budget.take

    def journal_take():
        take()
        (output_dir / "attempt_journal.json").write_text(
            json.dumps(
                {
                    "new_single_send_calls": budget.attempts,
                    "conservative_cumulative_send_upper_bound": PRIOR_SEND_RESERVE
                    + budget.attempts,
                    "total_cap": 270,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    budget.take = journal_take
    protocol = {
        "input_sha256": INPUT_HASH,
        "gold_sha256": GOLD_HASH,
        "reserved_prior_send_upper_bound": PRIOR_SEND_RESERVE,
        "new_single_send_cap": max_single_send_calls,
        "minimum_episode_spacing_seconds": 8,
        "answering": False,
        "retry": False,
        "candidate": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "scope": "fresh capture-only subset; no full90, answer or owner acceptance",
    }
    (output_dir / "protocol.json").write_text(
        json.dumps(protocol, indent=2) + "\n", encoding="utf-8"
    )
    rows = []
    usage = {}
    if allow_provider:
        rows, usage = asyncio.run(_provider_cases(inputs, output_dir, budget))
    scores = capture_scores(rows, gold)
    result = {
        "status": "contract_checked"
        if not allow_provider
        else (
            "incomplete"
            if len(rows) != 45 or scores["unavailable"]
            else "preliminary_semantic_pass"
            if scores["preliminary_semantic_floor"]
            else "preliminary_semantic_failed"
        ),
        "completed": scores["completed"],
        "unavailable": scores["unavailable"],
        "unrun": 45 - len(rows),
        "single_send_calls": budget.attempts,
        "conservative_cumulative_send_upper_bound": PRIOR_SEND_RESERVE
        + budget.attempts,
        "accepted": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "summary": result,
                "protocol": protocol,
                "scores": scores,
                "usage": usage,
                "request_latency_ms": base.distribution(budget.latencies),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fictional-provider-run", action="store_true")
    parser.add_argument("--max-single-send-calls", type=int, default=MAX_NEW_SENDS)
    args = parser.parse_args()
    print(
        json.dumps(
            run_capture_eval(
                args.output,
                allow_provider=args.allow_fictional_provider_run,
                max_single_send_calls=args.max_single_send_calls,
            )
        )
    )


if __name__ == "__main__":
    main()
