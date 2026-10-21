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

**Status:** PRs #288–#291 MERGED; active owner memory -> live voice model
integration **NOT IMPLEMENTED / NOT ACTIVE**. The owner-machine identity and
provider acceptance are required; do not claim otherwise. The objective is
active release, with isolated tests only as a means to validate it.

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

## Owner priority: personal intelligence, before more framework work

The owner has clarified that JARVIS's defining product must be an intelligent,
deeply contextual **personal assistant who knows the owner over time**, understands
preferences, experiences, relationships, decisions and evolving circumstances,
and proactively assists where permitted. The movie-inspired behavior is a goal,
not a claim of current capability. Coding/project continuity and autonomous
self-repair are *supporting* functions, not the primary end-user test.

Permanent requirements: [Product](PRODUCT.md) and Section 17 of
[Autonomous Self-Management North Star](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md).
CAP-053 (Personal Intelligence and Automatic Context Use) is **PLANNED**.

### Immediate next work — qualify the approved native architecture

1. Qualify and promote the reviewed repairs to the reproduced runtime,
   privacy, storage and provider-probe defects recorded in the audit. Local
   regressions and independent fix review passed; exact-head CI and applicable
   owner-machine acceptance remain promotion gates. Preserve canonical truth
   and normal Authority throughout.
2. Use the pinned-SDK fictional probe to qualify actual provider delivery.
   Its original session/agent API mismatch must be repaired before a paid
   live test; offline preflight alone is not delivery evidence. Compare
   initial-history, accepted-turn update and tool-result paths as PI-1C requires.
3. Add a measured question-to-facet relevance selector to the existing canonical
   reader boundary. The PI-1B fixture selector is not a natural-language router.
   Revalidate corrections, deletion, freshness, source policy and turn binding
   at consumption; preserve unavailable versus absent memory distinctions.
   Reuse relevant #287 contract evidence for accepted-turn identity, cancellation,
   duplicate/reconnect invalidation and bounded outstanding reads without adding
   a competing coordinator or claiming its text diagnostics prove live voice.
4. Establish trusted owner/turn attribution before private release. Speaker
   scores and camera presence remain diagnostics, not authority. Qualify guest,
   interruption, reconnect and identity-loss behavior on the actual runtime.
5. Run matched baseline/context answers and independent qualitative review on
   fixed and held-out everyday scenarios, then restart/outage tests. Include
   Hindi, Hinglish and English as priority forms plus explicitly reported
   broader-language coverage. Record actual useful application, errors,
   whole-turn and first-response latency, token usage and cost; do not infer
   end-to-end success from corpus validation or retrieved facts.
6. Implement and qualify the actual APPLY bridge and reversible OFF switch,
   complete owner-machine acceptance, and enable the approved path only for
   the authenticated owner. Automatic learning/admission remains a separate
   later capability; optional local-model training remains deferred.

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
