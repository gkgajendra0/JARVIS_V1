# JARVIS — Current Execution Plan

Updated 31 October 2026 (Asia/Kolkata). This file owns the next task; accepted runtime evidence remains in [Project State](PROJECT_STATE.md).

## Active owner decision: project conversations with Gemini and local memory

Read the [implementation contract](PROJECT_CONVERSATION_MEMORY.md) first, then the [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md).

The owner selected: existing Gemini for understanding/search requests/answers; automatic local conversation recording; persistent named projects/threads; existing encrypted personal memory and local retrieval; context delivered before the substantive answer. Reuse successful components. No paid hosted agent, new memory framework, local LLM or training pipeline is selected for the initial delivery. API cost is an explicit constraint.

## Current step: implementation in the isolated checkout

The owner authorized implementation. The first increment adds an awaited reply-dispatch boundary, immutable archive contracts, an explicit original-history authority scope, migration 5, an event store and a required recorder. The runtime owns the archive through its existing encrypted workers. The normal voice path is not connected to these components yet.

The pinned native Gemini adapter can start generation before final transcription; the installed-handler characterization reproduces that ordering without a network request. See the [transport contract and limitations](research/PROJECT_MEMORY_TRANSPORT_CONTRACT.md). The controlled text dispatch seam is tested locally. The pinned Google Cloud Speech STT requires credentials distinct from a Gemini API key, so no new speech service/account is silently enabled.

**Next implementation work:** complete Task 1 integration, then Task 2 persistent project routing and authenticated local reads. Tool events have storage support but still need their canonical capture adapter. Connect the recorder to the controlled reply coordinator in Task 3; do not attach it as a best-effort transcript observer or treat native voice as qualified.

## Delivery sequence

| Stage | Deliverable | Status |
|---|---|---|
| Documentation cleanup | One current contract, goals, build plan and historical evidence links | Complete; published before implementation |
| Task 0 | Pinned voice ordering contract and supported integration seam | Local boundary implemented/tested; live transport qualification OPEN |
| Task 1 | Automatic encrypted original-event archive and durable receipts | Storage/authority/recorder implemented; runtime/tool capture integration OPEN |
| Task 2 | Persistent project/thread selection and local search/read tools | NOT STARTED |
| Task 3 | Source-aware project/personal context delivered before answers | NOT STARTED |
| Task 4 | Inspect/correct/forget controls and isolated Windows entrypoint | NOT STARTED |
| Task 5 | End-to-end integrity, actual-model, cost/latency and native acceptance | NOT STARTED |

## Current foundation verification

- 397 scoped learning, authority, archive, transport, memory/migration and voice-bridge tests passed; four additional semantic-checkpoint compatibility tests passed after updating their migration-5 expectations. Repository Ruff check passed.
- Independent foundation review found two recorder concurrency/retry defects. Both were reproduced with failing tests and repaired; reviewer independently reran all four recorder tests successfully.
- Local SQL transaction tests use SQLite fixtures. Windows SQLCipher CI and real-provider, microphone, playback and native owner acceptance are separate evidence; no new pass is implied.
- No real provider request or paid inference was made. The previously rejected full local suite was not rerun or bypassed.

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
