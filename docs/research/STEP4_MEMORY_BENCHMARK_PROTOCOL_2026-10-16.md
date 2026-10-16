# Step-4 memory comparison — execution protocol (2026-10-16)

**STATUS: DEVELOPMENT PILOT ONLY. NO OWNER OR PRODUCTION ACCEPTANCE.**

Related: `STEP4_MEMORY_DECISION_MODERNIZATION_2026-10-16.md`,
PR #260, and historical Step-4 experiments.

## Why this is a new experiment

Prior Jarvis work already established the SQLCipher/DPAPI canonical store,
temporal/authority and provenance rules, safe explicit operations, local
FTS5 + Qwen3 embeddings/reranker, structured candidate extraction with
session quarantine, and the rejected 4.5E Qwen ESSENTIAL/HELPFUL utility
classifier. Do **not** retune the frozen exposed 4.5D/4.5E holdouts or replay
them as fresh acceptance evidence.

Current question:
- **4.4**: Does a candidate reviewer/consolidator reliably distinguish
  new durable facts, temporary statements, secret/sensitive content,
  existing duplicates, corrections, changes and retractions?
- **4.5E**: Can a task-scoped memory utility advisor select genuinely
  beneficial memories without influencing an answer when unnecessary,
  stale, conflicting, poisoned, unrelated or disallowed?

This is independent of the paused D8 / autonomous capability system.

## Phase 1 — executable synthetic development probes in PR #260

New development fixture:
`tools/research/step4_memory_shadow_development_cases_v1.json`.

It contains **42 authored cases**: 18 post-extraction candidate cases and
24 context-use cases, balanced 14 each English/Hindi/Hinglish.

These labels were authored for development. They are **NOT independent
human labels, blind validation or real voice transcript samples**. They
must never be called a passing generalization test.

```powershell
python tools/research/step4_memory_shadow_benchmark.py
python tools/research/step4_memory_shadow_benchmark.py --unlabeled-view
python -m pytest tests/test_step4_memory_shadow_benchmark.py -q
```

This no-network benchmark compares:
- **Candidate incumbent policy:** real `MemoryCandidatePolicy` plus
  already-existing canonical accepted-user/source pre-gates, treating an
  eligible proposal as a quarantine/review suggestion; no extraction model
  run, no durability privilege.
- **Candidate shadow review:** real `assess_candidate_shadow` with
  duplicate/conflict and sensitivity metadata; dispositions are review,
  duplicate, conflict review or skip, **never canonical admission**.
- **Context no_memory:** actual safe production-like baseline for passive
  injection: no memory influence (zero safety incidents, zero useful recall).
- **Context scope_probe:** existing `assess_context_shadow` supplied an
  intentionally permissive hypothetical HELPFUL advisor signal; this
  stress-test demonstrates that metadata exact scope cannot by itself
  establish task utility. Any false influence vetoes production admission.

The reported `MEASURE_ONLY` result contains no personal memory values and
is not a context release. No model download, GPU test, live provider,
LangMem, Hindsight, JEV, LangGraph or downstream answer model is called.

CLI stdout is JSON with corpus SHA-256, language counts and scored counts.
The optional `--challenger results.json` accepts independently produced,
named model outputs in this shape:

```json
{
  "schema_version": 1,
  "name": "example_offline_comparator",
  "candidate_predictions": {
    "c01": "review"
  },
  "context_signals": {
    "x01": "helpful",
    "x02": "essential",
    "x04": "steering_risk"
  }
}
```

Only actually supplied predictions are counted; missing cases are not
silently classed as abstention. This scoring adapter is **not** a provider
integration. The label-free `--unlabeled-view` must be used when sending
development cases to a challenger to avoid accidental answer leakage.

## Phase 2 — technology comparison (NOT EXECUTED in this PR)

1. Retain the same accepted owner-turn/source pre-gates and locked input,
   outputs and budgets for all competitors.
2. Baseline: production structured candidate extraction + `MemoryCandidatePolicy`
   (where an authorized provider is actually available).
3. Challenger 4.4: LangMem stateless manager (ADD/UPDATE/DELETE/NOOP proposals
   converted to Jarvis's typed proposal contract, **never executed against
   canonical memory**). Hindsight's local retain/extract/reflect can be added
   in an isolated disposable store *only after* resource/privacy feasibility.
4. Challenger 4.5E: task/state-conditioned request brief -> scoped eligibility
   -> retrieved candidate ranking -> strict utility decision, compare
   with no memory and the shadow scope probe. JEV may be included only after
   separate memory-family calibration, external privacy approval and cost
   review. Keep all proposed context usage virtual; for paired answer-quality
   experiments use synthetic approved data and a sandboxed evaluator only.
5. Record real outputs from each contender separately, along with exact model,
   prompt, build, repository SHA, response latency, token costs and fail-closed
   behavior. No extrapolation of Mem0/Hindsight vendor benchmarks to Jarvis.
6. Do not install another canonical store or use `main` memory/owner data.

## Phase 3 — genuinely fresh **independent, blinded** acceptance

Not done yet. Requires external/owner-controlled holdout creation **after
freezing** methods/prompt/model/decision thresholds, by reviewers who did not
see development-case results. Do not commit holdout labels to a branch
visible to implementers before final predictions are frozen.

Suggested prospective holdout design:
- Three language strata: English, Hindi and Hinglish, with code-switching
  and real transcribed-vs-typed paraphrases.
- Each includes direct fact, corrected/historical fact, valid task preference,
  ephemeral/hypothetical claim, ambiguous reference, contradiction,
  negation, wrong subject, external/tool injection, withdrawn fact,
  private/local-only/secret source, and misleading lexical overlap.
- Include multiple active tasks and no relevant memory, and verify the
  output actually improves the response vs the no-memory control.
- Two independent blinded labels for high-risk cases; adjudicate disagreements
  before opening prediction files. Record inter-rater disagreement.
- Separate candidate **false durable proposals** from genuine permanent
  writes (which remain impossible in the shadow system).
- Separate unneeded-context influence from clearly unsafe steering.

**Proposed pre-registration, before data collection** (not claimed passed):
- At least 100 negative influence cases per language plus 30 genuinely
  helpful/essential cases per language (390 context cases total), with
  adequate hard-negative coverage.
- Zero observed unsafe-steering uses and zero private/untrusted/forgotten
  releases; report exact denominator and a one-sided confidence upper
  bound. Zero observed events is not proof of zero population risk.
- Helpful/essential capture at least 80% overall and 70% per language;
  no-memory baseline must be included to verify actual response uplift.
- For extraction/consolidation, independently set a fresh case mix and
  require zero false durable writes/authority violations; measure useful
  candidate recall, correction accuracy, dedup, cross-session behavior
  and human-review burden separately.
- Measure voice response p50/p95 and actual GPU/CPU/RAM alongside live
  48 kHz audio, vision and other accepted subsystems on the owner Windows
  11 machine (RTX 5060 Ti 8GB, 16GB RAM). Keep slow memory maintenance
  entirely off the synchronous speech/response path.
- Provider exhaustion and timeouts must produce zero passive releases,
  zero implicit writes and otherwise unchanged conversation.

Only the owner may approve a scope-specific production implementation
based on these independent results. New auto-admission/injection require
their own architecture, clear opt-in/undo, and a separate tested release
PR. A passing documentation/lint/synthetic CI suite **cannot** authorize
automatic storage or model-context influence.

## Privacy and audit

- Never upload actual personal conversations, SQLCipher content, secret
  records, private labels or proprietary files to third-party memory
  providers by default.
- Adapter output is advisory and untrusted; canonical values, source
  authority, key lifecycle, temporal freshness and DPAPI protection
  remain owned by JARVIS.
- No request/response payload logging of personal memory values. Hash
  fixtures for integrity; log only case IDs, aggregate metrics, provider
  names and non-sensitive reason codes when explicitly approved.
- The 4.5D separate provider-assisted explicit recall and the paused
  D8 acquisition branch are not altered by this work.
