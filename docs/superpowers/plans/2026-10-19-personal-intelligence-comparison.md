# Personal Intelligence Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox syntax for tracking. No subagent dispatch is requested.

**Goal:** Measure the smallest reliable personal-context path before choosing an external service or changing production conversation behavior.

**Architecture:** A fictional lab compares accepted JARVIS, compact profile/history and optional service adapters using a common answerer. JARVIS retains canonical state and policy ownership. A separately approved read-only selector progresses to shadow only after comparison and interface evidence.

**Tech Stack:** Python 3.11+, standard library for lab contracts, existing pytest/Ruff/CI; existing approved model route only.

**Spec:** [Personal intelligence comparison design](../specs/2026-10-19-personal-intelligence-comparison-design.md).

## Global Constraints

- Keep Python 3.11 compatibility.
- Add no runtime dependency in the first slice.
- Use only fictional data in the comparison.
- Do not change canonical stores, production flags, turn ownership, Authority, retention or spending policy.
- No raw audio or real owner transcripts enter this research package.

## Review Focus

1. Missing/incorrect permission metadata must fail closed before external ingestion (Task 1).
2. A cancelled turn or reconnect must invalidate delayed evidence (Task 3).
3. A forgotten source must not survive in profiles or resumed caches (Tasks 1–2).
4. A source-less vendor inference must not become a canonical fact (Tasks 2–3).
5. Cold start, readiness timeouts and provider failure must remain explicit in results (Task 2).

## Delivery status

The initial package supplied research, design, protocol and public fictional data.
Task 1 now has an offline contract harness and focused regression tests. Its CLI
remains validation-only; Task 2 owns the future explicit live-run configuration.
The first harness releases original source quotes and uses a labelled conservative
UTF-8 byte budget. It does not measure derived profile/reflect quality or exact
token cost. Task 2 measurements and Task 3 production integration are not complete.
Read the spec and Current Plan before implementation; architecture approval remains
required for the shadow runtime, not implied by unit-test success.

An [exploratory diagnostic](../../research/PERSONAL_INTELLIGENCE_COMPARISON_RESULTS_2026-10-19.md)
now supplies single-pass text evidence. Task 2 remains incomplete: the native baseline,
vendor trials, repeats and independent holdout are still open. Its proposal to build
the bounded native shadow path first is an owner-reviewable sequence adjustment;
do not silently treat it as approval or as completed Task 2 evidence.

### Task 1: A non-oracle fictional comparison harness

**Create:** `tools/research/personal_intelligence_comparison.py`.
**Test:** `tests/test_personal_intelligence_comparison.py`.
**Consume:** `benchmarks/personal_intelligence_v1.json` and its protocol.

**Interfaces:**
- `load_cases(path: Path) -> list[dict]`: validate schema version, unique IDs,
  timezone-aware ordered timestamps, actor/permission fields and local source refs.
- `candidate_input(case: dict, *, destination: str) -> dict`: strict allowlist
  projection excluding evaluation metadata and prohibited destination content.
- `MemoryTrialAdapter` async protocol:
  `reset(identity: str) -> None`,
  `ingest(event: dict) -> None`,
  `wait_ready(timeout_s: float) -> bool`,
  `invalidate(source_ids: tuple[str, ...]) -> None`,
  `select(query: dict, token_budget: int) -> dict`,
  `close() -> None`.
- `run_case(case: dict, adapter: MemoryTrialAdapter, answerer: Callable, *, destination: str, token_budget: int, timeout_s: float) -> dict`.
  The output is a trace, not a self-awarded quality score.
- CLI defaults to validation only; executing models requires an explicit run config
  identifying approved route, budgets and output directory. No arbitrary shell hooks.

- [ ] Write tests for strict gold exclusion even when additional nested evaluation
  fields are present; reject unknown candidate fields rather than copying the case.
- [ ] Test cloud exclusion, guest isolation, absent/malformed permission metadata,
  future/naive timestamps, duplicate IDs and cross-case source references.
- [ ] Test chronological forget dispatch, post-forget profile invalidation,
  readiness timeout, cleanup after failure and no mutating answer tools.
- [ ] Run the focused tests, confirm the intended missing-contract failures, then
  implement only these contracts. Do not call external models in unit tests.
- [ ] Run focused tests, Ruff and the full repository suite on the exact branch
  head. Report failures and platform limits; commit the independently testable lab.

### Task 2: Baselines, bounded adapters and measured selection

**Extend:** `tools/research/personal_intelligence_comparison.py`.
**Create:** `tools/research/personal_intelligence_adapters.py`.
**Test:** `tests/test_personal_intelligence_adapters.py`.
**Evidence:** `docs/research/PERSONAL_INTELLIGENCE_COMPARISON_RESULTS_YYYY-MM-DD.md`
only after actual runs. Store bulky fictional traces as linked run artifacts.

**Interfaces:** implement Task 1's protocol. `select` returns
`{status, evidence: [{text, source_ids}], elapsed_ms}`. A common local validator
resolves source IDs and rejects invalid lineage before answerer release.
Adapter model/provider configuration is an explicit run input, never embedded secrets.

- [ ] Write/run failing tests for a genuinely rebuilt profile after correction,
  unsupported source lineage, incomplete forget, readiness timeout and partial
  provider failure. Use local protocol fixtures for contract tests and distinct
  opt-in service integration tests.
- [ ] Implement accepted-JARVIS and compact-profile/history arms first, plus the
  separate no-context ablation. Preserve bounded recall behavior in the incumbent
  arm; do not relabel an intentionally weak arm as the production baseline.
- [ ] Before a new external dependency, record version/artifact/license provenance
  and permitted model route. Implement finalist adapters one at a time only where
  their lifecycle/provenance contract can be exercised.
- [ ] Run public cases three times per arm using the protocol's common answerer and
  fixed budgets; capture failures, readiness, total costs, cold/warm latency and
  resources. Actually restart/reopen stores for persistence tests.
- [ ] Blind review outputs using the public rubric and independent adjudication.
  Freeze independently authored holdout cases before candidate output inspection.
  Run them once the quality procedure is fixed; keep public and held-out results distinct.
- [ ] Reject blocking privacy/lifecycle/authority failures. Compare paired usefulness
  outcomes and cost. If no external candidate demonstrates an advantage, retain the
  simpler qualifying baseline. Record inconclusive outcomes without a vendor winner.
- [ ] Run full tests/Ruff and self-review source lineage, fixture leakage and claims.
  Publish evidence with exact candidate identities; no production acceptance language.

### Task 3: Approved read-only shadow selector and provider bridge probe

**Gate:** owner explicitly approved read-only test mode and native-before-vendor
delivery on 2026-10-19. Task 2's initial context diagnostic is available; complete
native model/answer baselines and service comparisons remain open. This authorized
sequence adjustment does not waive those later evidence requirements. Inspect
actual provider code before finalizing changes.

**Create:** `src/jarvis/memory/personal_context.py`.
**Test:** `tests/test_personal_context.py`.
**Reuse/read:** `memory/query.py`, `release_guard.py`, `context.py`,
`live_context.py`; `voice/context_adapter.py`, `context_sync.py`,
`production_runtime.py`; canonical Work readers.
Any runtime wiring change needs a separately reviewed diff; do not pre-authorize
a broad change to all these files.

**Interfaces:** implement the spec's PersonalContextRequest, Evidence, Packet and
async `PersonalContextSelector.select`. Existing memory/read/release interfaces
remain authoritative. Task 2 adapters propose candidates; local source validation
determines eligibility.

**First slice ruling:** preserve exact native recall with one explicit personal
owner fact; measure broader advice relevance later. Use `budget_units/used_units`
with the existing UTF-8 byte estimator, not fictional token counts. Add a disposable
fictional probe; no production runtime activation. Local accepted-event simulation
is distinct from real voice timing/owner-machine acceptance.

- [ ] Write/run failing tests for accepted-turn binding, correction/forget racing
  release, expired observations, guest/local-only exclusion, token limits,
  cancellation, reconnect and unavailable sources.
- [ ] Implement the minimal read-only selector with no writer/executor/provider
  mutation handle. Test that shadow cannot invoke conversation context updates.
- [ ] Probe fictional live turns under the existing turn-detection configuration.
  Capture first-response timing, late context, interruption, duplicate events and
  reconnect. If no safe timely delivery seam exists, record the limitation and
  propose a separate bridge design; do not change turn ownership silently.
- [ ] Run full required CI, self-review and applicable owner-machine shadow
  acceptance. OFF cancels outstanding work and discards packets.
- [ ] Prepare one bounded PR and exact-head evidence. Keep APPLY, implicit durable
  admission and proactivity gated separately; protected merge needs owner approval.

## Self-review

The tasks cover input isolation, fair baselines, lifecycle, answer use, operational
cost and shadow integration. No task implements automatic personal-data capture or
replaces Work/conversation ownership. The public fixtures are intentionally small;
they cannot replace independent holdout or real voice acceptance. External service
selection remains an empirical Task 2 outcome, not an assumption in Task 1.
