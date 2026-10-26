"""Frozen fresh90/30-pair fictional qualification; never owner acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import subprocess
import tempfile
from pathlib import Path

from tools.research import personal_auto_learning_eval as base

ROOT = Path(__file__).resolve().parents[2]
INPUT_HASH = "5f23aaafe33d22aec625e7ae5422764060887c7a3e3af2b76fab498033ab9f19"
GOLD_HASH = "44b16dc01370aae55c69adab771d2351beb3733d8caaabf15a535591220c3617"
PRIOR_SEND_RESERVE = 266
TOTAL_CEILING = 532
MAX_NEW_SENDS = TOTAL_CEILING - PRIOR_SEND_RESERVE


def load_frozen_v4():
    raw = (ROOT / "benchmarks/personal_auto_learning_v4.json").read_bytes()
    goldraw = (ROOT / "benchmarks/personal_auto_learning_v4_gold.json").read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != INPUT_HASH
        or hashlib.sha256(goldraw).hexdigest() != GOLD_HASH
    ):
        raise ValueError("frozen input/gold hash mismatch")
    inputs, gold = json.loads(raw), json.loads(goldraw)
    required = {
        "id",
        "language",
        "turns",
        "seed",
        "question",
        "answer_subset",
        "control",
    }
    episodes = inputs["episodes"]
    if (
        inputs.get("fictional") is not True
        or len(episodes) != 90
        or len({e["id"] for e in episodes}) != 90
    ):
        raise ValueError("90 unique fictional cases required")
    if (
        any(set(e) != required for e in episodes)
        or sum(e["answer_subset"] for e in episodes) != 30
    ):
        raise ValueError("input fields or answer subset invalid")
    for language in ("en", "hi", "hinglish"):
        selected = [e for e in episodes if e["language"] == language]
        kinds = [
            gold["episodes"][e["id"]]["answer_kind"]
            for e in selected
            if e["answer_subset"]
        ]
        if len(selected) != 30 or sorted(kinds) != sorted(
            ["relevant"] * 6 + ["irrelevant"] * 2 + ["unknown_relation"] * 2
        ):
            raise ValueError("language or answer-kind balance changed")
    return inputs, gold


def context_mismatches(rows, gold):
    failures = []
    for row in rows:
        if row["status"] != "completed":
            continue
        expected = gold["episodes"][row["id"]]
        text = "\n".join(f["text"] for f in row.get("facts", []))
        if (
            (expected.get("context_empty") and row.get("facts"))
            or any(
                value.casefold() not in text.casefold()
                for value in expected.get("context_contains", [])
            )
            or any(
                value.casefold() in text.casefold()
                for value in expected.get("context_excludes", [])
            )
        ):
            failures.append(row["id"])
    return failures


def _persist(out, rows, pairs, keys, budget):
    for name, value in [
        (
            "progress.json",
            {
                "rows": rows,
                "single_send_calls": budget.attempts,
                "conservative_cumulative_send_upper_bound": PRIOR_SEND_RESERVE
                + budget.attempts,
            },
        ),
        ("blind_answers.json", pairs),
        ("answer_arm_key.json", keys),
    ]:
        (out / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


async def execute_cases(
    inputs, out, budget, learning, answering, endpoint, *, spacing=8, trace=None
):
    rows, pairs, keys = [], [], []
    trace = trace if trace is not None else []
    for index, episode in enumerate(inputs["episodes"]):
        if index:
            await asyncio.sleep(spacing)
        trace.clear()
        row = None
        try:
            with tempfile.TemporaryDirectory(prefix="fictional-v4-", dir=out) as folder:
                row = await base._episode(episode, learning, endpoint, Path(folder))
            rows.append(row)
            if row["status"] != "completed" or learning.last_failure:
                break
            if episode["answer_subset"]:
                answers = {}
                for arm, facts in [("baseline", []), ("enabled", row["facts"])]:
                    raw = await asyncio.wait_for(
                        answering._request(
                            base.ANSWER_PROMPT,
                            base.answer_payload(episode["question"], facts),
                            base.ANSWER_SCHEMA,
                        ),
                        10,
                    )
                    if not isinstance(raw.get("answer"), str):
                        raise TypeError("invalid answer schema")
                    answers[arm] = raw["answer"]
                order = (
                    ["baseline", "enabled"]
                    if secrets.randbits(1)
                    else ["enabled", "baseline"]
                )
                pairs.append(
                    {
                        "id": episode["id"],
                        "question": episode["question"],
                        "facts": row["facts"],
                        "A": answers[order[0]],
                        "B": answers[order[1]],
                    }
                )
                keys.append({"id": episode["id"], "A": order[0], "B": order[1]})
                row["answer_status"] = "paired"
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - sanitized fictional research boundary
            if row is not None:
                row["answer_status"] = "unavailable"
                row["answer_failure"] = type(exc).__name__
            else:
                row = {
                    "id": episode["id"],
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "predictions": [],
                }
                rows.append(row)
            break
        finally:
            if row is not None:
                row["fictional_learning_trace"] = list(trace)
            _persist(out, rows, pairs, keys, budget)
            print(
                json.dumps(
                    {
                        "id": episode["id"],
                        "status": row["status"] if row else "unavailable",
                        "committed": row.get("committed_count") if row else None,
                        "answer": row.get("answer_status") if row else None,
                        "single_send_calls": budget.attempts,
                        "last_failures": [
                            learning.last_failure,
                            answering.last_failure,
                        ],
                    }
                ),
                flush=True,
            )
    return rows, pairs, keys


async def _provider_run(inputs, out, budget):
    from jarvis.ai_provider import resolve_ai_role_model
    from jarvis.authority.local_opa import ManagedOpaServer
    from jarvis.config import JarvisConfig
    from jarvis.memory.learning_extractors import (
        EXTRACTION_PROMPT,
        build_learning_adapters,
    )
    from jarvis.memory.learning_policy import LearningPolicy

    config = JarvisConfig.from_environment()
    adapters, trace = [], []
    original_policy = LearningPolicy.evaluate

    def observed_policy(self, source, candidate, suppressed_categories=frozenset()):
        result = original_policy(self, source, candidate, suppressed_categories)
        trace.append(
            {
                "stage": "policy",
                "candidate": candidate.model_dump(mode="json"),
                "status": result.status,
                "reason": result.reason,
            }
        )
        return result

    LearningPolicy.evaluate = observed_policy
    try:
        learning, _ = build_learning_adapters(config.ai_provider)
        adapters.append(base._instrument(learning, budget))
        answering, _ = build_learning_adapters(
            config.ai_provider,
            resolve_ai_role_model(
                config.ai_provider,
                "work_orchestration",
                configured_model=config.work_orchestration_model,
            ),
        )
        adapters.append(base._instrument(answering, budget))
        request = learning._request

        async def traced_request(prompt, payload, schema):
            event = {
                "stage": "extract" if prompt == EXTRACTION_PROMPT else "resolve",
                "fictional_input": payload,
            }
            trace.append(event)
            try:
                result = await request(prompt, payload, schema)
                event["output"] = result
                return result
            except (Exception, asyncio.CancelledError) as exc:
                event["unavailable"] = type(exc).__name__
                raise

        learning._request = traced_request
        with ManagedOpaServer() as opa:
            rows, pairs, keys = await execute_cases(
                inputs, out, budget, learning, answering, opa.endpoint, trace=trace
            )
        return (
            rows,
            pairs,
            keys,
            [
                {
                    "provider": a.provider,
                    "requested_model": a.model_name,
                    "usage": a.usage,
                    "attempts": a.attempts,
                    "last_failure": a.last_failure,
                }
                for a in adapters
            ],
        )
    finally:
        LearningPolicy.evaluate = original_policy
        for adapter in adapters:
            await adapter.close()


def run_fresh_eval(
    output_dir, *, allow_provider=False, max_single_send_calls=MAX_NEW_SENDS
):
    if (
        type(max_single_send_calls) is not int
        or not 0 <= max_single_send_calls <= MAX_NEW_SENDS
    ):
        raise ValueError("remaining authorized cap must be0..266")
    inputs, gold = load_frozen_v4()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    budget = base.AttemptBudget(max_single_send_calls)
    take = budget.take

    def journal():
        take()
        (out / "attempt_journal.json").write_text(
            json.dumps(
                {
                    "single_send_calls": budget.attempts,
                    "conservative_cumulative_send_upper_bound": PRIOR_SEND_RESERVE
                    + budget.attempts,
                    "approved_ceiling": TOTAL_CEILING,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    budget.take = journal
    protocol = {
        "candidate": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "input_sha256": INPUT_HASH,
        "gold_sha256": GOLD_HASH,
        "reserved_prior_send_upper_bound": PRIOR_SEND_RESERVE,
        "new_single_send_cap": max_single_send_calls,
        "cumulative_ceiling": TOTAL_CEILING,
        "episode_spacing_seconds": 8,
        "retry": False,
        "answer_pairs": 30,
        "stop": "any semantic-stage unavailability or answer/provider failure; no replay",
        "provenance_limit": "requested model recorded; server alias/effective model is not proven by requested string",
        "owner_acceptance": False,
    }
    (out / "protocol.json").write_text(
        json.dumps(protocol, indent=2) + "\n", encoding="utf-8"
    )
    rows, pairs, _keys, usage = [], [], [], []
    if allow_provider:
        try:
            rows, pairs, _keys, usage = asyncio.run(_provider_run(inputs, out, budget))
        except Exception as exc:  # noqa: BLE001 - startup failure must remain unavailable evidence
            progress_path = out / "progress.json"
            rows = (
                json.loads(progress_path.read_text(encoding="utf-8"))["rows"]
                if progress_path.exists()
                else []
            )
            if not rows:
                rows = [
                    {
                        "id": inputs["episodes"][0]["id"],
                        "status": "unavailable",
                        "reason": "resources_unavailable",
                        "failure_kind": type(exc).__name__,
                        "predictions": [],
                    }
                ]
            pairs_path = out / "blind_answers.json"
            pairs = (
                json.loads(pairs_path.read_text(encoding="utf-8"))
                if pairs_path.exists()
                else []
            )
    scores = base.score_rows(rows, gold)
    scores["context_mismatches"] = context_mismatches(rows, gold)
    scores["complete_answer_pairs"] = len(pairs)
    scores["advice_review"] = "pending blind author review; no owner acceptance"
    result = {
        "status": "contract_checked"
        if not allow_provider
        else "provider_checks_complete_pending_review"
        if scores["completed"] == 90 and not scores["unavailable"] and len(pairs) == 30
        else "incomplete",
        "completed": scores["completed"],
        "unavailable": scores["unavailable"],
        "unrun": 90 - len(rows),
        "answer_pairs": len(pairs),
        "single_send_calls": budget.attempts,
        "conservative_cumulative_send_upper_bound": PRIOR_SEND_RESERVE
        + budget.attempts,
        "accepted": False,
    }
    artifact = {
        "summary": result,
        "protocol": protocol,
        "scores": scores,
        "usage": usage,
        "rows": rows,
        "request_latency_ms": base.distribution(budget.latencies),
        "accepted_turn_callback_ms": base.distribution(
            [v for r in rows for v in r.get("callback_ms", [])]
        ),
        "baseline_callback_ms": base.distribution(
            [v for r in rows for v in r.get("baseline_ms", [])]
        ),
    }
    (out / "summary.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
            run_fresh_eval(
                args.output,
                allow_provider=args.allow_fictional_provider_run,
                max_single_send_calls=args.max_single_send_calls,
            )
        )
    )


if __name__ == "__main__":
    main()
