# JARVIS — Current Execution Plan

Updated 31 October 2026 (Asia/Kolkata). This file owns the next task; accepted runtime evidence remains in [Project State](PROJECT_STATE.md).

## Active owner decision: project conversations with Gemini and local memory

Read the [implementation contract](PROJECT_CONVERSATION_MEMORY.md) first, then the [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md).

The owner selected: existing Gemini for understanding/search requests/answers; automatic local conversation recording; persistent named projects/threads; existing encrypted personal memory and local retrieval; context delivered before the substantive answer. Reuse successful components. No paid hosted agent, new memory framework, local LLM or training pipeline is selected for the initial delivery. API cost is an explicit constraint.

## Current step: connected controlled-text candidate

The isolated implementation now connects required capture, persistent projects/threads,
authorized local tools, bounded context and the existing Gemini answer/tool cycle.
Existing canonical personal reads use exact owner consent; no new learning write scope
or standalone extraction call is enabled. See the [acceptance/evidence guide](project-memory-acceptance.md).

The normal voice path remains unchanged. Pinned native Gemini generation can precede
final transcription; a compatible controlled STT path is still unqualified. The first owner Windows text attempt at `7b6c6ede` failed during routing because
production Rego lacked conversation-history delegation. The repair adds the narrow
policy branch and a mandatory real-OPA CI regression. The next owner dependency is
a generation-failure reproduction in the retained lab: the owner rerun at
`d8504526` saved original turns and recalled Jimny/permit after sleep, but one
status request failed with `ValueError` during generation. Exception detail was
discarded; use the redacted failure probe with the same pinned source/profile.
Do not restart with empty history or claim full acceptance. No general rollout/merge is claimed.

| Stage | Software status | Outstanding evidence |
|---|---|---|
| Task 0 | Native ordering characterized; awaited controlled dispatch and serialized payload tested | Native speech/STT/TTS qualification |
| Task 1 | Required user/assistant/tool metadata capture, receipts, omissions and migration 5 connected | Actual owner-machine operation |
| Task 2 | Persistent routing, exact aliases, duplicate clarification, thread selection, project-wide bounded search/read | Natural-language/model usefulness |
| Task 3 | Project/personal evidence, source/revision guards and ordinary answer/tool cycle connected | Actual Gemini answer quality and cost |
| Task 4 | Authenticated console controls, explicit deletion and isolated exact-source launcher | Windows launcher/Hello execution |
| Task 5 | 200-event replay; frozen 60+40 questions; independent review/fixes | Actual-model questions and owner acceptance |

## Verification and unresolved limits

Prior connected-candidate local scoped verification: 484 tests passed, repository Ruff passed, and 93 relative
links in seven changed Markdown files resolve. Exact-head CI is recorded alongside
the published candidate, separately from historical results. The replay reconciles all 200 events,
10 projects and 30 segments after reopen; 200 duplicate callbacks do not add events.
The four Important review findings were reproduced and repaired. Search outcome
metadata and late assistant delivery also have payload/source regressions.

Policy-repair unaffected scoped verification: 375 passed; real-OPA final matrix
requires hosted CI after local automatic review stopped possible OPA telemetry.
The old simplified-policy fixtures missed the owner failure; see the acceptance
guide for the cause and repair. Owner acceptance remains OPEN.

The 100 frozen actual-model questions are UNRUN. No real provider request, microphone
or native playback test ran here. Tests use SQLite fixtures and fake OS/Hello;
provider-boundary fixtures do not count as generated-answer quality. The conservative
6,000 wire-byte upper estimate is not calibrated provider token usage.

The earlier full local pytest telemetry rejection remains in force. Use scoped tests
and hosted CI, without rerunning/bypassing that command. Installed settings/checkout
and protected main remain unchanged.

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
