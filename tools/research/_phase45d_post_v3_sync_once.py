from __future__ import annotations

import re
from pathlib import Path

PLAN = Path("docs/CURRENT_PLAN.md")


def main() -> None:
    text = PLAN.read_text(encoding="utf-8")

    stage_pattern = re.compile(
        r"\*\*STEP 3 COMPLETE \+ MERGED .*? PHASE 4\.5E BLOCKED\*\*"
    )
    stage = (
        "**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — "
        "PHASE 4.5D ACTIVE — FRESH V3 FAIL_CALIBRATION / RETIRED — V3 VALIDATION "
        "UNEXPOSED — GEMINI 3.8 FLASH CALIBRATION DIAGNOSTIC NEXT — PHASE 4.5E BLOCKED**"
    )
    text, count = stage_pattern.subn(stage, text, count=1)
    assert count == 1

    active_pattern = re.compile(
        r"## Active 4\.5D direction — FRESH V3 ACCEPTANCE\n.*?\n---\n\n## Phase 4\.5E — BLOCKED",
        re.DOTALL,
    )
    active = """## Active 4.5D direction — POST-V3 GEMINI 3.8 CALIBRATION DIAGNOSTIC

Fresh V3 has been executed once and is **FAIL_CALIBRATION / RETIRED**. Do not rerun it, overwrite it, or execute its untouched validation half.

Durable result:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_V3_RESULT.md`.

Frozen owner-run V3 evidence:

- implementation SHA `783a5b49cdf31a957c403066f1ea421c007354a4`;
- corpus SHA-256 `baac40840bc260a01f4fc630570e4578dbdf8dc9f36c8b3192c6bb6471191195`;
- calibration `170 TP / 14 FP`, empirical precision `0.923913`;
- one-sided 95% Clopper-Pearson lower precision bound `0.883609731`;
- positive Recall@10 and reranked Top-1 both `170/180 = 0.944444`;
- EN positive release recall `1.0`, HI `0.833333`, Hinglish `1.0`;
- false releases: `5 positive retrieval misses + 3 near_miss + 1 ambiguous + 1 unsupported_source + 4 historical`;
- security-boundary leaks: four `historical` cases;
- **validation was not executed**.

The failure is not marginal. With `170` true releases, at most `3` false releases would satisfy the frozen exact 95% precision-confidence gate; V3 produced `14`.

### Failure diagnosis

The ten positive Top-10 misses were all Hindi and concentrated in two predicates:

- five `archive_destination` misses; Gemini 3.5 Flash-Lite incorrectly RELEASED all five wrong Top-1 documents;
- five `signin_method` misses; Gemini correctly abstained on all five.

Whenever the expected positive memory entered Top-10, the frozen Qwen reranker placed it Top-1. This keeps the ranking problem localized to first-stage multilingual candidate starvation rather than reranker ordering.

The remaining semantic false releases were concentrated in scope-sensitive cases: Hinglish near-miss/ambiguity, one English unsupported-source query, and Hindi/Hinglish historical queries.

### Research-first next candidate — Gemini 3.8 Flash

Google released stable GA `gemini-3.8-flash` on September 2, 2026 and positions it as its most intelligent Flash model for complex workflows with higher factual rigor. It supports the same Interactions API and structured outputs plus configurable thinking. This is a materially stronger current production model than the failed Flash-Lite judge, so it is the next mature technology to test before adding custom semantic logic.

Frozen development method:

- `docs/research/STEP_4_PHASE_4_5D_GEMINI38_CALIBRATION_DIAGNOSTIC_METHOD.md`.

Harness:

- `tools/research/step4_phase45d_gemini38_calibration_diagnostic.py`.

The diagnostic uses **only the already exposed V3 calibration split** and changes one semantic variable:

```text
same V3 calibration only
same canonical eligibility/security
same Qwen3 256d FTS5 + exact cosine + equal RRF
same Top-10 candidate window
same Qwen3 reranker + frozen instruction
same one-query/document Interactions request shape
same semantic sufficiency prompt + structured schema + store=False

Gemini 3.5 Flash-Lite
        ↓ only changed semantic variable
Gemini 3.8 Flash, thinking_level=medium
```

Before any Gemini 3.8 scoring is accepted as comparable evidence, the harness must reproduce every one of the 360 V3 calibration Top-1 IDs and positive Recall@10/Top-1 flags from the retired owner artifact.

Development selection for a fresh V4 design requires the existing exact precision, recall, language and zero-security-release gates. Even a perfect diagnostic is development evidence only; V4 would need a completely fresh acceptance corpus. The untouched V3 validation split must not be reused as V4 acceptance evidence.

If Gemini 3.8 fails this diagnostic, stop model-hopping and research/implement the structure-aware fallback: parse memory queries into canonical subject/relation/temporal/source constraints, apply deterministic metadata filtering before semantic release, and evaluate multilingual NLI only as a task-matched secondary verifier if needed.

---

## Phase 4.5E — BLOCKED"""
    text, count = active_pattern.subn(active, text, count=1)
    assert count == 1

    text = text.replace(
        "9. **4.5D — ACTIVE: development architecture selected 39/39; fresh V3 method/corpus/harness frozen; owner V3 acceptance next.**",
        "9. **4.5D — ACTIVE: V3 FAIL_CALIBRATION / RETIRED with validation unexposed; Gemini 3.8 calibration-only diagnostic next.**",
        1,
    )

    do_not_anchor = "- alter the frozen V3 corpus, prompt, API shape, model revisions or gates after owner acceptance begins;"
    replacement = (
        "- rerun or overwrite the failed V3 acceptance artifact;\n"
        "- execute the untouched V3 validation half after calibration failure;\n"
        "- retune the V3 prompt/model/corpus/gates and claim it is still fresh V3 evidence;\n"
        "- use the untouched V3 validation split as V4 acceptance evidence;"
    )
    assert do_not_anchor in text
    text = text.replace(do_not_anchor, replacement, 1)

    immediate_pattern = re.compile(r"## Immediate Next Action\n.*\Z", re.DOTALL)
    immediate = """## Immediate Next Action

**PASS THE GEMINI 3.8 CALIBRATION-ONLY DIAGNOSTIC THROUGH CI ON A CLEAN EXACT SHA, THEN RUN IT ONCE AGAINST THE RETIRED OWNER V3 CALIBRATION ARTIFACT.**

The diagnostic must use `.step4-phase45d-final-v3-acceptance.json` only as exposed development input, prove V3 validation was never executed, reproduce all 360 calibration retrieval decisions, and never access the V3 validation split.

If `gemini-3.8-flash` with medium thinking satisfies the frozen exact precision/recall/language/security development gates, freeze it only for **fresh V4 design**. If it fails, move to the researched structure-aware query-planning/metadata-filter architecture rather than prompt-tuning or generic relevance-model cycling.

Phase 4.5E remains blocked.
"""
    text, count = immediate_pattern.subn(immediate, text, count=1)
    assert count == 1

    PLAN.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
