# JARVIS — Current Execution Plan

**Reconciled with both development chats, 20 October 2026.** This file contains *current
priority and next actionable work*, not a complete chronology. The previous plan is
preserved verbatim at [the October 18 snapshot](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-18.md).
Historical engineering milestones and evidence remain in [Project State](PROJECT_STATE.md)
and the [Documentation Index](README.md).

## Active owner request — automatic conversational learning (21 October 2026)

The owner requested implementation after reviewing the earlier research and
experiment inventory. Desired behavior: important eligible everyday information
is learned and used automatically, without a per-fact save question. This
supersedes the subsequently discussed proposal/confirmation product experience;
it does not claim automatic admission is already implemented or active.

PRs #292, #293 and #294 have been promoted; the reviewed implementation is on
`main` at `7de92b3d0507ca52cfa3b653ddd976e3356a7102`. The earlier promotion
action below is completed. Existing bounded owner acceptance remains valid.

Current work is the
[written automatic-learning design](superpowers/specs/2026-10-21-personal-auto-learning-design.md),
on `feat/personal-auto-learning-20261021`. **Status: written design approved by
the owner; executable task plan prepared for review. No automatic-learning
product code or production settings changed.** It reuses
native extraction, canonical memory and context delivery, and preserves prior
external-framework/classifier failures rather than repeating those trials.
The concrete new permission proposal is a private, explicitly delegated owner
session; it does not claim qualified biometric attribution of each later turn.

Next: review the [executable task plan](superpowers/plans/2026-10-21-personal-auto-learning.md),
select execution method and implement the accepted automatic-admission/runtime path. The owner's
instruction to research broadly and narrow on evidence is a continuing constraint;
new targeted research is appropriate for a concrete unsolved interface or quality
gap, not as a substitute for delivery. Do not ask again for the already approved
native architecture or require owner-authored examples/isolated microphone demos.

## Owner direction — active personal intelligence (2026-10-19)

The owner approved architecture PR #288, PI-1A #289, and PI-1B #290.
All three passed their prescribed GitHub CI and were merged to `main`.
The owner has also explicitly requested **real activated personal-context assistance,
not an indefinite shadow feature**, after thorough testing. The owner subsequently
tested an existing saved preference in the configured Windows deployment.

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

**Status:** PRs #288–#291 MERGED. PR #294 and its dependencies #292/#293 supply the first
opt-in active owner-memory path in normal `jarvis-voice`, with fresh Windows Hello
consent for each exact canonical request, current reads and private audio guarding.
It retires the provider session after one personal answer; subsequent requests
require a fresh wake. This exact-consent fallback does not claim qualified
biometric speaker attribution. On October 21 the owner confirmed the normal-app
saved-preference recall/correction/restart/restore sequence and authorized checked
stack promotion. See the [bounded acceptance record](acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md);
the PRs record actual merge status. Broader everyday advice quality remains open.
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
CAP-053 is **PARTIAL**: the opt-in saved-preference flow has bounded owner
acceptance; the broader personal-intelligence contract is not complete.

### Earlier PI-1 release sequence — promotion complete; qualification retained

The owner-log correction failure is repaired in the same candidate: natural
correction/deletion proposals resolve the actual canonical target, then require
fresh concrete owner approval. See the [October 21 repair report](research/MEMORY_INTENT_REPAIR_2026-10-21.md).
The owner confirmed correct spoken results for the prescribed saved-diet
sequence. Promotion was explicitly authorized conditional on checks; this does
not accept broader advice quality, automatic learning or seamless attribution.

1. **Completed:** authorized #292 → #293 → #294 promotion. Preserve owner acceptance
   and exact-head/protected-main verification evidence.
2. Qualify personally useful everyday advice with general fictional scenarios in
   English/Hindi/Hinglish, including relevant/irrelevant context and honest absence.
   Saved-preference recall acceptance alone does not prove this broader behavior.
3. Record language, latency, provider failures and cost honestly. Prepare the
   bounded natural-learning design through existing memory/authority contracts;
   new automatic durable capture requires its own architecture approval.
4. Seamless verified-speaker follow-ups remain later work. Do not restart vendor
   comparisons as a substitute for completing this native personal-assistant path.

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
  operations accepted; automatic candidate admission remains **disabled**.
  Opt-in exact-consented context and natural correction now have bounded
  owner recall/correction/restart acceptance; broader semantic quality remains open.
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

The owner approved the October 21 automatic-learning written design. Review its
executable task plan, select execution method and implement the slice through
the established lifecycle.
Retain the broader advice, owner-input/session and normal-app acceptance gates;
do not restart completed PI-1 promotion or old vendor experiments. Continue
until a concrete required owner review, observation or unavailable resource is
needed, and identify that dependency explicitly.
