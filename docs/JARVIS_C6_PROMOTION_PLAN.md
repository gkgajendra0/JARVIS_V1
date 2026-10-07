# JARVIS C6 Prompt-Compression Promotion Plan

Status: **RESEARCH / PROMOTION DESIGN ONLY**

Production state remains unchanged:

- `JARVIS_WORK_PROMPT_COMPRESSION_MODE=off` by default;
- no global APPLY;
- RESEARCH is the only initial eligible Work type;
- DEVELOPMENT/CODING is excluded from first promotion;
- PR #252 remains draft/unmerged until the bounded promotion evidence is complete.

## 1. Evidence already accepted

The first valid model-routed LLMLingua-2 proof passed on owner-machine commit
`3749bcea09556ea48ccbbcf6c2688eb67e0588c1` using
`research_ready_for_digest_bound_finalize`.

Accepted result:

- complete canonical history: 14 steps / 144,459 serialized chars;
- current production window: 12 steps / 132,570 serialized chars;
- retained rate: 0.85;
- compressed complete history: 130,887 serialized chars;
- full-history serialized reduction: 9.40%;
- compressed complete history: 1.27% smaller than the current serialized payload;
- full-history A/A baseline stable;
- action, exact parameters, goal-complete, needs-owner and owner-question all identical;
- provider input-token reduction versus raw full history: 12.47%;
- local CPU compression latency: about 16.1 seconds;
- no Work action, routing mutation, provider-circuit mutation or paid fallback;
- canonical Work state remained uncompressed.

This proves technical feasibility. It does **not** prove that production APPLY is the
best operational tradeoff.

## 2. External release-engineering basis

The promotion design follows established progressive-exposure practice rather than
inventing a Jarvis-specific release philosophy.

- Google SRE defines canarying as a partial, time-limited deployment evaluated before
  broader rollout and recommends limiting blast radius while observing real traffic:
  https://sre.google/workbook/canarying-releases/
- Microsoft Safe Deployment Practices require progressive exposure, health checks before
  each phase, and immediate halt/recovery when issues appear:
  https://learn.microsoft.com/azure/well-architected/operational-excellence/safe-deployments
- AWS MLOps guidance explicitly distinguishes shadow deployment (new path receives
  traffic but does not serve the result) from canary deployment (a small portion of
  production traffic is served by the new path):
  https://docs.aws.amazon.com/prescriptive-guidance/latest/mlops-checklist/continuous-deployment.html
- Microsoft LLMLingua-2 reports task-agnostic prompt compression with lower compression
  overhead than prior LLMLingua approaches, but the published benchmark does not replace
  Jarvis-specific semantic and latency acceptance:
  https://www.microsoft.com/en-us/research/publication/llmlingua-2-data-distillation-for-efficient-and-faithful-task-agnostic-prompt-compression/

Jarvis therefore treats its own owner-machine evidence as authoritative for promotion.

## 3. Promotion principle

C6 promotion has three independent gates:

1. **semantic quality** — compressed complete history must preserve the important model
   decision under the unchanged strict comparator;
2. **economic/token value** — compressed complete history must use fewer real provider
   input tokens than the payload Jarvis sends today;
3. **operational value** — local compression latency/failures must not make normal Jarvis
   operation materially worse.

A pass on one gate cannot substitute for another.

## 4. Stage P0 — OFF (current production)

Current state.

- Current 12-step provider payload is served.
- LLMLingua does not run.
- This remains the immediate rollback target for every later stage.

Exit gate: none; this is the safe baseline.

## 5. Stage P1 — bounded admission evidence

### P1-A: current-production token measurement

Use the already accepted three-call semantic PASS report and make exactly one new
ChatGPT-plan call with today's exact current payload.

Required result:

- accepted compressed-full-history provider input tokens <
  current-production provider input tokens.

The probe must fail closed if any of these drift from the accepted proof:

- Work reasoner / system-prompt implementation;
- prompt-compression implementation;
- ChatGPT-plan/provider adapter;
- benchmark fixture;
- C6 acceptance harness;
- compressor library/model revisions;
- compressor dependency versions;
- rebuilt current/full/compressed payload digests.

The probe never enables APPLY.

### P1-B: representative semantic corpus

One valid finalize fixture is not enough for broad promotion.

Before a serving canary, obtain strict PASS evidence on at least **three genuinely
model-owned RESEARCH decisions across at least two distinct action schemas**.

For every case:

1. full complete history -> model call A;
2. identical full complete history -> model call B;
3. if A != B under the strict comparator, mark the case **INCONCLUSIVE** and do not
   evaluate compression;
4. if A == B, send compressed complete history;
5. require exact equality for action, parameters, goal-complete, needs-owner and
   owner-question.

Do not weaken schemas/comparators to create a pass. Deterministic Phase-9 protocol steps
must not be used as model-equivalence fixtures.

The corpus should cover different reasoning shapes, not repeated variants of the already
passing finalize decision.

## 6. Stage P2 — operational SHADOW

Purpose: prove local compressor reliability and latency on real eligible RESEARCH work
without serving compressed context.

Important correction before any sustained production shadow soak:

The current `RoutedWorkReasoner._provider_payload()` SHADOW path waits for LLMLingua
before sending the unchanged current payload. At the observed ~16-second CPU latency,
that means SHADOW can slow production even though it cannot improve provider tokens.

Therefore sustained SHADOW must use one of these designs before promotion:

- preferred: non-serving asynchronous/background compression telemetry that does not
  delay the provider request; or
- a separate bounded diagnostic harness outside the normal interactive request path.

Do not accept "shadow" merely because the model sees the old payload; serving latency is
also production behavior.

Operational shadow evidence should record, without logging raw sensitive prompt text:

- eligible Work count and distinct Work IDs;
- full/current/compressed serialized sizes;
- candidate/compressed field counts;
- compression latency;
- compressor/fallback reason;
- exact compressor/model revisions;
- canonical request/payload digests;
- CPU/resource-lease contention.

Exit gate:

- no structural/canonical-state corruption;
- no unhandled compressor failure;
- no resource-lease deadlock/stampede;
- latency distribution reviewed on the owner machine.

## 7. Stage P3 — explicit RESEARCH CANARY

Do **not** overload global `apply` for first exposure. Add a distinct canary state or an
equally explicit bounded gate.

Initial canary contract:

- Work type: RESEARCH only;
- accepted LLMLingua model/library revisions only;
- accepted retained rate: **0.85** initially;
- complete canonical history remains source of truth;
- compressed text remains provider-view only;
- C6 hand-selected context APPLY and prompt-compression canary/APPLY cannot be active
  together;
- compressed full history is eligible only when it independently beats today's current
  payload in serialized chars and estimated tokens;
- deterministic, bounded exposure selector (stable Work/step identity, not ad-hoc
  randomness);
- explicit maximum canary budget so one owner cannot accidentally expose every RESEARCH
  decision;
- no DEVELOPMENT/CODING traffic;
- existing owner/Authority/promotion gates remain unchanged.

### Canary fallback

Before serving canary traffic, add a canary-specific failback path:

- compressor init/inference/validation failure -> current payload;
- compressed payload not smaller -> current payload;
- provider decision fails local response/action JSON-Schema validation -> retry once
  with the exact current payload **without treating compression failure as provider
  health failure**;
- if canary-specific failures repeat, disable canary and serve current payload.

Provider outages/quota failures continue through the existing provider-routing policy;
C6 must not create a new paid fallback.

### Canary telemetry

Persist enough evidence to answer:

- Was compressed context actually selected?
- How many full-history steps were retained?
- What were current/full/compressed sizes?
- What was local compression latency?
- What provider input-token usage was observed?
- Did any canary-specific fallback occur?
- Was the returned decision contract-valid?
- Did the Work later require owner correction/rework?

Do not persist raw compressed context merely for telemetry.

## 8. Stage P4 — RESEARCH APPLY

RESEARCH-only APPLY becomes eligible only after:

- P1-A confirms a real provider-token win versus today's production payload;
- representative P1-B semantic corpus passes;
- operational shadow is healthy;
- bounded serving canary completes without canary-specific correctness/safety failures;
- owner-machine latency/token tradeoff is judged worthwhile;
- rollback to OFF/current payload has been exercised.

Even then:

- only RESEARCH is promoted;
- rate stays pinned to the accepted value until a separate rate change is accepted;
- global DEVELOPMENT/CODING compression remains OFF.

## 9. DEVELOPMENT is a separate promotion

Do not infer DEVELOPMENT safety from RESEARCH success.

Development prompts contain different risk surfaces:

- source text and diffs;
- exact paths and command/test contracts;
- code-generation state;
- engineering-change/promotion evidence.

Any future DEVELOPMENT compression needs its own protected-field policy, fixtures,
semantic corpus, token/latency evidence and canary.

## 10. Stop / rollback conditions

Immediately stop canary/APPLY and return to OFF/current payload when any of the following
is observed:

- protected JSON structure/value changes;
- out-of-schema action parameters attributable to canary path;
- repeated compressor exceptions;
- compressed payload no longer beats current payload;
- model/compressor/runtime lineage drift without fresh acceptance;
- owner-visible decision regression or unexplained rework;
- resource starvation or unacceptable interactive latency;
- evidence that a supposedly deterministic protocol decision reached the model because
  of a control-plane regression.

Rollback changes only provider-view selection. Canonical Work history is never rolled
back because it was never compressed in storage.

## 11. Immediate next action

1. Keep production OFF.
2. Let CI validate the hardened one-call current-token probe.
3. Run that probe once on the owner machine using the saved
   `jarvis_c6_llmlingua_live_3749bcea.json` PASS report.
4. Record the PASS report SHA-256 and measured compressed-vs-current provider-token delta.
5. Only then decide whether the measured saving justifies further semantic fixtures and
   canary implementation given the ~16-second local CPU compression cost.

Do not rerun the already passing three-call finalize fixture unless its accepted runtime
lineage changes.
