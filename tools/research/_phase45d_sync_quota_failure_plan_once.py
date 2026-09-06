"""One-time helper to synchronize CURRENT_PLAN after final composite quota failure."""

from __future__ import annotations

from pathlib import Path


OLD_STAGE = (
    "**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — "
    "PHASE 4.5D ACTIVE — PROVIDER-INDEPENDENT COMPOSITE GATE SELECTED — "
    "FRESH FINAL ACCEPTANCE FROZEN — PHASE 4.5E BLOCKED**"
)
NEW_STAGE = (
    "**STEP 3 COMPLETE + MERGED — STEP 4 PHASES 4.0A–4.5C COMPLETE — "
    "PHASE 4.5D ACTIVE — PROVIDER-INDEPENDENT COMPOSITE GATE SELECTED — "
    "FRESH FINAL ACCEPTANCE QUOTA-INTERRUPTED / CORPUS PRESERVED — "
    "PHASE 4.5E BLOCKED**"
)

OLD_HEADING = "### Fresh final composite acceptance — FROZEN / OWNER RUN NEXT"
NEW_HEADING = (
    "### Fresh final composite acceptance — FROZEN / FIRST OWNER EXECUTION "
    "QUOTA-INTERRUPTED / RERUN UNCHANGED AFTER QUOTA"
)

OLD_ORDER = (
    "9. **4.5D — ACTIVE: provider-independent composite gate selected; "
    "fresh final composite acceptance frozen and owner run next.**"
)
NEW_ORDER = (
    "9. **4.5D — ACTIVE: provider-independent composite gate selected; fresh final "
    "composite acceptance frozen; first execution ended in provider quota failure "
    "before a complete artifact; rerun unchanged after quota is available.**"
)

OLD_NEXT = """## Immediate Next Action

**PASS THE GEMINI 3.8 CALIBRATION-ONLY DIAGNOSTIC THROUGH CI ON A CLEAN EXACT SHA, THEN RUN IT ONCE AGAINST THE RETIRED OWNER V3 CALIBRATION ARTIFACT.**

The diagnostic must use `.step4-phase45d-final-v3-acceptance.json` only as exposed development input, prove V3 validation was never executed, reproduce all 360 calibration retrieval decisions, and never access the V3 validation split.

If `gemini-3.8-flash` with medium thinking satisfies the frozen exact precision/recall/language/security development gates, freeze it only for **fresh V4 design**. If it fails, move to the researched structure-aware query-planning/metadata-filter architecture rather than prompt-tuning or generic relevance-model cycling.

Phase 4.5E remains blocked.
"""

NEW_NEXT = """## Immediate Next Action

**RERUN THE EXACT SAME FROZEN FINAL COMPOSITE ACCEPTANCE ONLY AFTER THE GEMINI PROJECT HAS SUFFICIENT REQUEST QUOTA.**

The first owner execution on SHA `6cba430ca9d8ea8c95c542c0664e64bd9cffbd21` stopped after case 31 because Google returned HTTP `429` for the free-tier request quota (`generate_content_free_tier_requests`, limit `500`) on `gemini-3.5-flash-lite`. No complete acceptance artifact, summary, or decision was produced.

Durable execution record:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_COMPOSITE_ACCEPTANCE_EXECUTION_FAILURE.md`.

This is transport/quota failure only. The frozen corpus, model, prompt/schema, local guard, request shape, deterministic policy, acceptance gates, and corpus SHA remain unchanged. Do not tune against the 31 partial printed results and do not create a replacement corpus.

Before rerun, verify the final acceptance artifact is still absent and the frozen corpus SHA remains `69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`. Then execute the same acceptance harness with `--device cuda --gemini-rpm 12` after the relevant quota resets or the same project has adequate paid quota.

Phase 4.5E remains blocked until a complete fresh final artifact passes every frozen gate and closure evidence is recorded on a green exact SHA.
"""

INSERT_AFTER = (
    "The owner acceptance uses current `gemini-3.5-flash-lite` only as the structured "
    "proposal adapter. This does **not** make memory authority Gemini-specific and "
    "does not add another production provider switch."
)
INCIDENT = """

First owner execution on `2026-09-06` used SHA `6cba430ca9d8ea8c95c542c0664e64bd9cffbd21`, passed environment/corpus preflight, and began the frozen 255-case run. Google returned HTTP `429` after case 31 for `generativelanguage.googleapis.com/generate_content_free_tier_requests` with limit `500`. The harness terminated before writing a complete artifact.

Per the frozen method, this is **EXECUTION_FAILURE_QUOTA**, not `FAIL_ACCEPTANCE`. The first 31 partial console observations are non-evidentiary and must not be used for tuning. The corpus remains the same fresh acceptance corpus and may be rerun unchanged once sufficient provider quota is available.

Durable execution record:

- `docs/research/STEP_4_PHASE_4_5D_FINAL_COMPOSITE_ACCEPTANCE_EXECUTION_FAILURE.md`.
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one {label} marker")
    return text.replace(old, new, 1)


def main() -> None:
    path = Path("docs/CURRENT_PLAN.md")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, OLD_STAGE, NEW_STAGE, "stage")
    text = replace_once(text, OLD_HEADING, NEW_HEADING, "acceptance heading")
    text = replace_once(text, OLD_ORDER, NEW_ORDER, "implementation order")
    text = replace_once(text, OLD_NEXT, NEW_NEXT, "immediate next action")
    if INSERT_AFTER not in text:
        raise RuntimeError("acceptance provider paragraph marker not found")
    text = text.replace(INSERT_AFTER, INSERT_AFTER + INCIDENT, 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
