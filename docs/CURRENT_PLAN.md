# JARVIS — Current Execution Plan

**Reconciled with both development chats, 20 October 2026.** This file contains *current
priority and next actionable work*, not a complete chronology. The previous plan is
preserved verbatim at [the October 18 snapshot](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-18.md).
Historical engineering milestones and evidence remain in [Project State](PROJECT_STATE.md)
and the [Documentation Index](README.md).

## Owner direction — active personal intelligence (2026-10-19)

The owner approved architecture PR #288, PI-1A #289, and PI-1B #290.
All three passed their prescribed GitHub CI and were merged to `main`.
The owner has also explicitly requested **real activated personal-context assistance,
not an indefinite shadow feature**, after thorough testing. There are no
known existing personal memories in the owner's current deployment.

**Goal:** in a reliably authenticated OWNER conversation, JARVIS automatically
retrieves relevant permitted canonical facts and correctly *uses* them in
personalized advice, without an explicit memory search instruction. Empty
memory must yield an honest "I don't have that information yet", not fabricated
personal understanding. This is a permanent active product requirement.

**Release gates before activation on the owner machine:**
1. Confirm the actual Windows checkout/main SHA, configured memory enablement,
   SQLCipher/DPAPI health, voice model and plugin versions. No passwords or keys
   in reports.
2. Verify a trusted identity/turn binding that distinguishes owner requests
   from nearby guest speech. Existing speaker scoring is SHADOW diagnostics
   (not accepted proof of ownership); seeing an owner candidate on camera is
   not a verified speech attribution. Never release private owner history to
   an unverified speaker.
3. Validate real Gemini/LiveKit delivery with **fictional** memory facts,
   both initial and follow-up turns, and show the answer uses the right context.
   Test interruptions, correction, deletion, stale claims, absent memory,
   provider outages, no mid-session instruction spoofing, and token/cost.
4. Implement an **APPLY** path in the actual voice runtime with the existing
   canonical owner memory and Authority controls; do not represent isolated
   shadow-packet generation as activation. A provider tool or chat-context
   update must be proven on the pinned SDK/model.
5. Run full automated and owner-machine acceptance, then turn on the approved
   active path for the authenticated owner only. Preserve a documented OFF
   switch and fail-closed behavior on identity/provider failures.

**Automatic capture is a separate capability.** No indiscriminate recording,
implicit sensitive storage, or retention of all raw daily conversations is
approved by activating read-only context. Start with explicitly permitted facts
and add carefully governed natural learning after the initial active recall
release is proven.

**Status:** PRs #288–#291 MERGED. The unmerged
`feat/personal-intelligence-runtime-20261020` candidate implements the first
opt-in active owner-memory path in normal `jarvis-voice`, with fresh Windows Hello
consent for each exact canonical request, current reads and private audio guarding.
It retires the provider session after one personal answer; subsequent requests
require a fresh wake. This exact-consent fallback does not claim qualified
biometric speaker attribution. Protected main remains unchanged; owner acceptance
is to run the whole local app after software checks, not another isolated demo.
Automatic learning is still separate. See the
[runtime report](research/PERSONAL_INTELLIGENCE_RUNTIME_2026-10-20.md).

The two chats pursued the same native-extension direction. PR #289 supplies
an offline evaluation contract, #290 a policy-tested read-only foundation,
and #291 an opt-in fictional provider-delivery probe. None proves automatic
personalization. The previous chat's [draft PR #287](https://github.com/gkgajendra0/JARVIS_V1/pull/287)
contains separate native-shadow and multilingual diagnostic evidence; it is
unmerged and must not be counted as code or acceptance on `main`, or merged
wholesale over the newer implementation. Preserve useful evidence and compare
individual contracts before reuse.

The [October 20 reconciliation audit](research/PERSONAL_INTELLIGENCE_RECONCILIATION_AUDIT_2026-10-20.md)
records the handover, verified scope, defects and remaining qualification.

The subsequent [fictional provider/usefulness qualification](research/PERSONAL_CONTEXT_DELIVERY_QUALIFICATION_2026-10-20.md)
demonstrated initial-history delivery and automatic realtime tool selection for
three ordinary dinner questions after an explicit context-use instruction to the
isolated test agent. Tool availability alone failed. Mid-session history updates
remain unqualified. A names-only structured relevance adapter now has offline
contracts, but actual semantic selections were unavailable due provider HTTP
timeouts/503. None of these experiments activates production memory or proves
trusted spoken-owner attribution, populated-session forgetting or held-out quality.

## Owner priority: personal intelligence, before more framework work

The owner has clarified that JARVIS's defining product must be an intelligent,
deeply contextual **personal assistant who knows the owner over time**, understands
preferences, experiences, relationships, decisions and evolving circumstances,
and proactively assists where permitted. The movie-inspired behavior is a goal,
not a claim of current capability. Coding/project continuity and autonomous
self-repair are *supporting* functions, not the primary end-user test.

Permanent requirements: [Product](PRODUCT.md) and Section 17 of
[Autonomous Self-Management North Star](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md).
CAP-053 remains **PLANNED for accepted production**; its first active read slice
is implemented in the unmerged runtime candidate.

### Immediate next work — finish normal-app acceptance and promotion

The owner-log correction failure is repaired in the same candidate: natural
correction/deletion proposals resolve the actual canonical target, then require
fresh concrete owner approval. See the [October 21 repair report](research/MEMORY_INTENT_REPAIR_2026-10-21.md).
This supplies the requested implementation for normal local-app testing; it does
not mark spoken acceptance or protected promotion complete.

1. Complete final automated checks and independent review for the normal-runtime
   candidate; preserve exact-head evidence and publish the implementation report.
2. Owner runs the complete local app with --personal-context apply and asks
   everyday English/Hindi/Hinglish questions, including explicit remember,
   correction/deletion and restart. No further isolated microphone demo is needed.
3. Record actual spoken usefulness, semantic relevance/negative cases, language,
   latency and provider failures honestly. Automated synthetic proposals prove
   wiring and release policy, not live model quality or billed cost.
4. Promote reviewed stacked candidates only through protected-main gates and
   explicit owner approval. Automatic learning and seamless verified-speaker
   follow-ups remain later work. Do not restart vendor comparisons as a substitute
   for completing this active native slice.

The native architecture is already owner-approved. Do not ask for that same
decision again or restart a vendor benchmark as a substitute for integration.
The owner requested general fictional tests instead of supplying personal
examples; no owner-authored examples are a prerequisite to continued development.

**First behavioral acceptance:** after several sessions and a restart, JARVIS
responds meaningfully to personally relevant everyday questions using
previously authorized, corrected and still-current facts *without* explicit
"search memory" prompting, while refusing to guess facts or leak restricted
information. Natural, accurate assistant use is the measure—not only a
retrieval benchmark score.

## What is already accepted vs deferred

- Steps 0–3: conversation, wake/voice, vision foundation, identity/trust and
  observability accepted to their documented scope.
- Step 4: **BOUNDED**. Encrypted SQLCipher persistent memory and explicit
  operations accepted; automatic candidate admission and automatic
  provider-context memory injection **disabled**. Natural-language live
  semantic recall has a deferred owner-machine acceptance gate.
- Steps 5–6: provider resilience/research **BOUNDED**.
- Step 7: generic capability runtime and safe reads **DONE**.
- WorkStore/DBOS durable work, Self-Awareness, Hands foundations and bounded
  deterministic R2 recovery are accepted for their documented boundaries.
- Engineering Phases 2–10A are accepted to their defined scopes; Phase 9
  full external-device lifecycle remains deferred; full proactive autonomy
  has not been promoted. Phase 11 is **next in that engineering program**,
  not the current owner-directed implementation instruction.
- Cost optimization C6 Work Context is **SHADOW**, not accepted as applied
  production reasoning context.

See [Current Architecture](CURRENT_ARCHITECTURE.md) and
[Project State](PROJECT_STATE.md) for authoritative scope and evidence.

## Previous work and parallel obligations — not cancelled

- PR #243 provider-model lifecycle is merged. That status alone does not prove
  the new personal-context delivery path or spoken owner attribution.
- The previously requested bounded Cost Optimization program is recorded in
  [Cost Optimization Master Plan](JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md)
  and its original [implementation plan](reference/JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md).
  The prior rule not to purchase paid-brain credits before the documented
  pre-credit gate remains unchanged.
- The Phase 9 full external TV capability lifecycle has **not** been proven
  end to end. Its acceptance gate is still deferred.
- Step 8 notes/tasks/reminders remains the next *numbered product* step if
  that program resumes.
- Phase 11 autonomous capability-gap detection remains the next planned
  *cross-cutting engineering* research/architecture step, without
  implementation authorization.
- Open issues and accepted, bounded or deferred details remain in Project
  State and GitHub; no previous owner approval is silently revoked by a
  documentation cleanup.

## Governance and change gates

Use the established sequence: research -> architecture -> explicit owner
approval -> isolated PR -> automated tests -> applicable owner-machine
acceptance -> documentation reconciliation -> protected promotion.

The owner authorized audit reconciliation and repairs to reproduced contract
violations. This does not authorize new personal-data retention, cloud release
of local-only data, a different canonical store, paid fallback purchases or
bypass of Authority/OPA. The approved active product goal still requires the
release gates above. **Protected main remains unchanged until the owner
approves and all required checks pass.**

## Next action

Complete owner-machine qualification and protected promotion of the reviewed
repair slice, then qualify synthetic provider delivery and the trusted
owner-turn boundary. Continue
through the implementation/qualification sequence above until a real owner
observation, exact promotion approval or unavailable resource is needed.
