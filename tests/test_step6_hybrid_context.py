"""Adversarial offline tests for Step 6 hybrid memory and context selection."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tools.research.step5_memory_decision_acceptance import frozen_assertions
from tools.research.step6_hybrid_context_acceptance import (
    run_synthetic_hybrid_benchmark,
)

from jarvis.memory.research_decision_gate import Assertion
from jarvis.memory.research_hybrid_context import (
    ContextRequest,
    EvidenceStream,
    HybridSafetyError,
    assemble_context,
)

_DAY_V1 = "synthetic-workshop-day-v1"
_DAY_V2 = "synthetic-workshop-day-v2"
_VENUE = "synthetic-workshop-venue-v1"


def _request(
    preds: tuple[str, ...] = ("workshop_day",),
    *,
    max_chars: int = 2048,
) -> ContextRequest:
    return ContextRequest("synthetic-atlas", preds, max_chars=max_chars)


def _streams() -> tuple[EvidenceStream, ...]:
    return (
        EvidenceStream("hindsight", (_DAY_V2, _VENUE)),
        EvidenceStream("lexical", (_DAY_V1,)),
        EvidenceStream("temporal", (_DAY_V2, _DAY_V1)),
    )


def test_fused_candidates_pack_complete_history_and_sources():
    packet = assemble_context(frozen_assertions(), _streams(), _request())
    assert packet.status == "ready"
    assert packet.production_promotion_allowed is False
    assert packet.included_predicates == ("workshop_day",)
    assert set(packet.included_assertion_ids) == {_DAY_V1, _DAY_V2}
    payload = json.loads(packet.payload_json)
    assert len(payload) == 1
    assert [s["value"] for s in payload[0]["states"]] == [
        "saturday",
        "sunday",
    ]
    assert all(s["source_ref"].startswith("conversation:synthetic:") for s in payload[0]["states"])
    assert packet.chars_used == len(packet.payload_json)
    assert packet.chars_used <= 2048


def test_never_supply_unretrieved_older_fact():
    single = assemble_context(
        frozen_assertions(), (EvidenceStream("hindsight", (_DAY_V2,)),), _request()
    )
    assert single.status == "abstain"
    assert single.payload_json == "[]"
    assert single.included_assertion_ids == ()
    assert single.reason_code == "no_complete_verified_lineage"


def test_fuse_two_partial_sources_to_complete_lineage():
    packet = assemble_context(
        frozen_assertions(),
        (
            EvidenceStream("hindsight", (_DAY_V2,)),
            EvidenceStream("lexical", (_DAY_V1,)),
        ),
        _request(),
    )
    assert packet.status == "ready"
    assert set(packet.included_assertion_ids) == {_DAY_V1, _DAY_V2}


def test_unknown_question_does_not_expose_other_memory():
    packet = assemble_context(
        frozen_assertions(),
        _streams(),
        _request(("nonexistent",)),
    )
    assert packet.status == "abstain"
    assert packet.withheld_predicates == ("nonexistent",)
    assert packet.payload_json == "[]"


def test_scoped_subject_does_not_leak_nile():
    packet = assemble_context(
        frozen_assertions(),
        (EvidenceStream("hindsight", (
            "synthetic-report-day-v1", "synthetic-report-day-v2",
        )),),
        _request(),
    )
    assert packet.status == "abstain"


def test_independent_predicate_can_be_included_without_day_lineage():
    packet = assemble_context(
        frozen_assertions(),
        (EvidenceStream("hindsight", (_VENUE, _DAY_V2)),),
        _request(("workshop_day", "workshop_venue")),
    )
    assert packet.status == "ready"
    assert packet.included_predicates == ("workshop_venue",)
    assert packet.withheld_predicates == ("workshop_day",)
    assert packet.included_assertion_ids == (_VENUE,)


def test_budget_does_not_truncate_source_lineage():
    packet = assemble_context(
        frozen_assertions(), _streams(), _request(max_chars=256)
    )
    assert packet.status == "abstain"
    assert packet.reason_code == "context_budget_exceeded"
    assert packet.payload_json == "[]"
    assert packet.chars_used == 2


def test_ranking_is_reproducible_on_equal_input():
    one = assemble_context(
        frozen_assertions(),
        _streams(),
        _request(("workshop_day", "workshop_venue")),
    )
    two = assemble_context(
        frozen_assertions(),
        _streams(),
        _request(("workshop_day", "workshop_venue")),
    )
    assert one == two


@pytest.mark.parametrize(
    "invalid",
    [
        (EvidenceStream("hindsight", (_DAY_V1, _DAY_V1)),),
        (EvidenceStream("hindsight", ("synthetic-unknown-id",)),),
        (
            EvidenceStream("hindsight", (_DAY_V1,)),
            EvidenceStream("hindsight", (_DAY_V2,)),
        ),
        (EvidenceStream("not-a-real-engine", (_DAY_V1,)),),
        (EvidenceStream("hindsight", [_DAY_V1]),),
        (EvidenceStream("hindsight", (None,)),),
    ],
)
def test_rejects_forged_duplicate_or_malformed_candidate_streams(invalid):
    with pytest.raises(HybridSafetyError):
        assemble_context(frozen_assertions(), invalid, _request())


@pytest.mark.parametrize(
    "invalid",
    [
        ContextRequest("owner-person", ("workshop_day",)),
        ContextRequest("synthetic-atlas", ("bad!predicate",)),
        ContextRequest("synthetic-atlas", ("workshop_day", "workshop_day")),
        ContextRequest("synthetic-atlas", ("workshop_day",), max_chars=255),
        ContextRequest("synthetic-atlas", ("workshop_day",), max_chars=9000),
        ContextRequest("synthetic-atlas", ("workshop_day",), max_chars=True),
        ContextRequest("synthetic-atlas", ("workshop_day",), max_groups=0),
        ContextRequest("synthetic-atlas", ()),
    ],
)
def test_rejects_untrusted_query_and_budget(invalid):
    with pytest.raises(HybridSafetyError):
        assemble_context(frozen_assertions(), _streams(), invalid)


def test_canonical_provenance_tampering_is_rejected():
    facts = frozen_assertions()
    bad = replace(facts[0], source_ref="conversation:private:owner")
    with pytest.raises(HybridSafetyError, match="untrusted_canonical_fixture"):
        assemble_context((bad, *facts[1:]), _streams(), _request())


def test_conflicting_revision_fork_never_enters_context():
    facts = frozen_assertions()
    original = next(f for f in facts if f.assertion_id == _DAY_V1)
    newer = next(f for f in facts if f.assertion_id == _DAY_V2)
    fork: Assertion = replace(
        newer,
        assertion_id="synthetic-workshop-day-v2-fork",
        value="friday",
    )
    packet = assemble_context(
        (original, newer, fork),
        (EvidenceStream("hindsight", (_DAY_V1, _DAY_V2, fork.assertion_id)),),
        _request(),
    )
    assert packet.status == "abstain"
    assert packet.reason_code == "no_complete_verified_lineage"


def test_constructed_3600_fact_benchmark_reports_limits():
    report = run_synthetic_hybrid_benchmark()
    assert report["status"] == "pass"
    assert report["synthetic_assertions"] == 3600
    assert report["constructed_queries"] == 240
    assert report["complete_hybrid_contexts"] == 240
    assert report["incomplete_lineages_rejected"] == 240
    assert report["provider_results_simulated"] is True
    assert report["real_hindsight_large_scale_measured"] is False
    assert report["graphiti_or_mem0_installed"] is False
    assert report["production_memory_write"] is False


def test_standalone_isolated_cli_is_offline():
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "research" / "step6_hybrid_context_acceptance.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "pass"
    assert data["production_promotion_allowed"] is False
