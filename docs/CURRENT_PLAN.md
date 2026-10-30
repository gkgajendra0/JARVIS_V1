# JARVIS — Current Execution Plan

Updated 31 October 2026 (Asia/Kolkata). This file owns the next task; accepted runtime evidence remains in [Project State](PROJECT_STATE.md).

## Active owner decision: project conversations with Gemini and local memory

Read the [implementation contract](PROJECT_CONVERSATION_MEMORY.md) first, then the [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md).

The owner selected: existing Gemini for understanding/search requests/answers; automatic local conversation recording; persistent named projects/threads; existing encrypted personal memory and local retrieval; context delivered before the substantive answer. Reuse successful components. No paid hosted agent, new memory framework, local LLM or training pipeline is selected for the initial delivery. API cost is an explicit constraint.

## Current step: documentation before implementation

The owner requested Git cleanup and durable detailed documentation first, then building. This pass preserves existing work, names the isolated worktree branch, consolidates this direction, and marks competing options historical/deferred. Product code, dependencies, model/provider settings, installed checkout and activation are unchanged.

**Next implementation task, after the owner's instruction:** Task 0 in the build plan: establish the pinned transport contract for accepted transcript -> durable archive commit -> selected context delivered -> answer generation -> guarded audio. Do not treat buffered uninformed speech as satisfying the contract. Use the predeclared controlled speech/text/TTS fallback only for a demonstrated native capability blocker.

## Delivery sequence

| Stage | Deliverable | Status |
|---|---|---|
| Documentation cleanup | One current contract, goals, build plan and historical evidence links | Documented in this pass; publication verification recorded in Git/PR |
| Task 0 | Pinned voice ordering contract and supported integration seam | NOT STARTED |
| Task 1 | Automatic encrypted original-event archive and durable receipts | NOT STARTED |
| Task 2 | Persistent project/thread selection and local search/read tools | NOT STARTED |
| Task 3 | Source-aware project/personal context delivered before answers | NOT STARTED |
| Task 4 | Inspect/correct/forget controls and isolated Windows entrypoint | NOT STARTED |
| Task 5 | End-to-end integrity, actual-model, cost/latency and native acceptance | NOT STARTED |

## First user-visible outcome

Nepal discussion -> connected follow-up -> sleep -> follow-up -> switch to interviews -> restart -> named Nepal status -> correction -> recall/source inspection -> forget -> restart. Full source discussion remains available when Gemini omits a structured update. Different projects must not mix. Relevant established personal facts remain usable across projects.

The implementation contract defines G1–G8, failure behavior, proposed acceptance thresholds, source authority and cost bounds. Do not call documentation or historical component tests completion of these goals.

## Retained candidate evidence and known limits

PR [#303](https://github.com/gkgajendra0/JARVIS_V1/pull/303) remains draft. Its existing code candidate saves model-proposed topic fields, not full conversation history. Baseline product head `7800e984780b36ee18dd5e4be61a85b899bc7def` had 624 focused tests and two exact-head hosted CI passes, but the owner's actual Nepal trace restored empty details. Native connected-conversation acceptance FAILED; replacement implementation is not complete.

Earlier full local pytest was stopped by automatic approval review for an outbound Microsoft telemetry connection with unknown payload; do not retry/bypass it indirectly. An unrelated isolated process-recovery regression also remains recorded. Use appropriate scoped checks and hosted CI. Do not claim the entire local suite passes.

Keep installed runtime activation and merging separate from isolated development. Existing authority/speaker boundaries and cost governors remain in force; no additional paid inference budget follows from this plan.

## Reading order and historical records

1. [Product and design contract](PROJECT_CONVERSATION_MEMORY.md).
2. [Execution tasks](superpowers/plans/2026-10-31-project-conversation-memory.md).
3. [Evidence ledger](PROJECT_STATE.md) and [Quality Gates](QUALITY_GATES.md).
4. Earlier research only for the exact component question it addresses. No repeat vendor bake-off as a substitute for integration.

The complete previous Current Plan is preserved at [31 October snapshot](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-31.md). Its dated priorities and relative links are historical, not current execution instructions. Prior accepted product milestones and unrelated workstreams are not deleted or reclassified by this feature plan.
