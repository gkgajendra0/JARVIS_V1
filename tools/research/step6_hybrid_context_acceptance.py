"""Zero-network offline acceptance for the hybrid memory context prototype.

The simulated providers return fabricated ranked IDs. This demonstrates
gating/fusion behavior only; it is not a measured Graphiti/Mem0 deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.research.step5_memory_decision_acceptance import large_fictional_corpus

from jarvis.memory.research_hybrid_context import (
    ContextRequest,
    EvidenceStream,
    assemble_context,
)


def run_synthetic_hybrid_benchmark() -> dict[str, object]:
    corpus = large_fictional_corpus()  # 3,600 fictional assertions
    by_id = {fact.assertion_id: fact for fact in corpus}
    attempted = 0
    passed = 0
    rejection_cases = 0

    # 120 subjects x 2 predicates: every provider sees only part of the
    # required history; union completes lineage. This is a CONSTRUCTED test.
    for i in range(0, 600, 5):
        subject = f"synthetic-project-{i:04d}"
        for pred in ("schedule", "venue"):
            ids = tuple(f"synthetic-{i:04d}-{pred}-v{k}" for k in (1, 2, 3))
            distractor = f"synthetic-{(i + 1) % 600:04d}-{pred}-v1"
            streams = (
                EvidenceStream("hindsight", (distractor, ids[2])),
                EvidenceStream("lexical", (ids[0], distractor)),
                EvidenceStream("temporal", (ids[1],)),
            )
            packet = assemble_context(
                corpus,
                streams,
                ContextRequest(subject, (pred,), max_chars=1024),
            )
            attempted += 1
            decoded = json.loads(packet.payload_json)
            if (
                packet.status == "ready"
                and packet.included_predicates == (pred,)
                and set(packet.included_assertion_ids) == set(ids)
                and len(decoded) == 1
                and len(decoded[0]["states"]) == 3
                and all(
                    row["source_ref"] == by_id[row["assertion_id"]].source_ref
                    for row in decoded[0]["states"]
                )
                and packet.chars_used <= 1024
            ):
                passed += 1
            # A solo top-ranking corrected fact must never become context.
            missing = assemble_context(
                corpus,
                (EvidenceStream("hindsight", (ids[2],)),),
                ContextRequest(subject, (pred,), max_chars=1024),
            )
            if missing.status == "abstain":
                rejection_cases += 1

    return {
        "kind": "STEP6_OFFLINE_HYBRID_MEMORY_CONTRACT",
        "synthetic_assertions": len(corpus),
        "constructed_queries": attempted,
        "complete_hybrid_contexts": passed,
        "incomplete_lineages_rejected": rejection_cases,
        "status": "pass"
        if passed == attempted and rejection_cases == attempted
        else "fail",
        "provider_results_simulated": True,
        "real_hindsight_large_scale_measured": False,
        "graphiti_or_mem0_installed": False,
        "owner_data_accessed": False,
        "production_memory_write": False,
        "production_promotion_allowed": False,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = run_synthetic_hybrid_benchmark()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
