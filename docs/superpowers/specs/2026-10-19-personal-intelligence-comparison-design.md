# Personal intelligence comparison and shadow-context design

**Status:** proposed bounded architecture; no runtime activation.
**Baseline:** main `a7ef430d614cf60bd11298ab352a342216594736`.
**Authority:** [Current Plan](../../CURRENT_PLAN.md), [Quality Gates](../../QUALITY_GATES.md)
and Section 17 of the existing North Star.
[Comparative evidence](../../research/PERSONAL_INTELLIGENCE_COMPARATIVE_DECISION_2026-10-19.md).

## Outcome and boundary

Give the owner useful everyday answers informed by relevant, authorized, current
context across sessions and restart. The first delivery is a fictional comparison
lab followed by an approved read-only shadow selector. Production provider input
changes, natural durable admission and proactive actions are separate gates.

Keep Python 3.11 compatibility. Add no runtime dependency in the first slice.
Use only fictional data in the comparison. Do not change canonical stores,
production flags, turn ownership, Authority, retention or spending policy.
No raw audio or real owner transcripts enter this research package.

## One architecture

Accepted owner turn + identity + time + provider release policy
-> eligible canonical sources and current session/work observations
-> replaceable context candidate adapter
-> JARVIS source/currentness/release validation
-> bounded PersonalContextPacket
-> shadow evidence only.

Apply to the live conversation provider only in a later approved slice with a
verified provider bridge. Memory is evidence, never execution permission.
External memory services are derived processors/indexes with explicit lifecycle
synchronization; they do not own canonical owner facts, consent or Work state.

The selector returns current relevant evidence or an explicit abstention.
External inferences without inspectable supporting sources cannot be elevated
to canonical facts. Conflicting sources may be presented as uncertainty; timestamps
alone do not make a third-party claim supersede an owner correction.

## Proposed selector interface

These are new interfaces, not claims about existing constructors:

- `PersonalContextRequest`: accepted `turn_id`, `session_id`, `requester`,
  `utterance`, `as_of` (timezone-aware), `destination`, `token_budget`,
  `deadline_ms`.
- `PersonalContextEvidence`: `source_ids`, `text`, `subject`,
  `observed_at`, `valid_until` (optional), `sensitivity`,
  `authority_class`, `source_version`. These fields come from canonical
  wrappers, not from an external model declaring its own authority.
- `PersonalContextPacket`: `turn_id`, `session_id`, `status`
  (ready/abstain/unavailable/stale_turn), `evidence`, `token_count`,
  `reason_codes`, `elapsed_ms`.
- `PersonalContextSelector.select(request) -> PersonalContextPacket`, asynchronous,
  with cancellation. Reads only; no writer, conversation-provider or executor handle.

Reject a packet whose turn/session changed, source was revoked/superseded,
destination is not permitted, or deadline expired. Empty/failed retrieval cannot
invent profile defaults. Revalidate source version at release to close the
correction/forget race. Reconnect invalidates in-flight packets. Existing
`ContextPacket` remains the owner of provider-facing context assembly.

Read sources through existing memory read/release boundaries and canonical Work
state. Do not query SQLCipher tables directly to bypass eligibility. The existing
exact reader is not assumed to provide general episodic search. Prototype that
missing capability in the lab before proposing a production schema expansion.

## Comparison contract

Freeze the public corpus and protocol before running candidates. Hold answerer,
prompt, tools, sampling, query sequence and context budget constant within a
comparison. Record each candidate's ingestion, extraction, reflection, profile
construction, retrieval and synchronization models/costs separately.

Required arms:
1. Accepted JARVIS behavior, including its existing bounded recall where available.
2. Compact source-linked profile plus permitted history search.
3. Optional finalists: Hindsight, Honcho and Supermemory as distinct configurations.

Include a no-personal-context ablation; do not describe it as the full JARVIS
baseline. Oracle evidence is diagnostic only and cannot enter a candidate arm.
Public rubrics and required/forbidden source IDs are evaluator-only.

Ingest events chronologically into isolated fictional identities. Permission
metadata is supplied by the fixture; this tests policy enforcement, not automated
consent classification. Correction handling and relevance selection must not use
the rubric. A verified forget event carries target source IDs as an operation;
this is legitimate lifecycle input, not the answer key.

Every adapter must support reset, bounded ingestion, completion/readiness,
context selection, explicit source invalidation and cleanup. If a service cannot
meet provenance/deletion contracts, report unsupported or fail that gate; do not
award safety credit because a wrapper removed all useful output.

## Acceptance and failure policy

Report answer usefulness separately from evidence retrieval. Blind candidate
labels for answer review; score each listed requirement and prohibition with
recorded rationale. Use deterministic trace checks for known source release,
turn binding and operation boundaries, plus semantic review for paraphrased
leaks and wrong claims. Source IDs alone cannot detect semantic leakage.

Any restricted cloud release, guest leak, unauthorized action or reappearance of
verified-forgotten content is a blocking lifecycle/privacy failure.
PI019's irrelevant gardening mention is a relevance failure, not automatically a
privacy incident. Corrections, subject attribution and truthful uncertainty must
pass their explicit cases before a variant qualifies.

The 20-case set is too small for a general quality claim. Use three repeats per
public case for variance, report paired per-case outcomes and all failures, then
add an independently authored frozen holdout before final selection. Repeated
runs of one case are not independent users. A quality tie favors the simpler
qualifying arm. Do not select a vendor when quality, lifecycle or cost evidence
is missing.

Record cold/warm p50/p95 context latency, time to first spoken output in the voice
probe, errors/timeouts, input/output/model tokens, ingestion/rebuild/delete cost,
CPU/RAM/GPU active and idle use, service versions and reproducible artifacts.
Budgets must be configured and fixed before trials; no silent retries or spending.

## Voice bridge, rollout and rollback

First probe the accepted provider configuration with fictional turns. Verify
when context becomes available relative to the first response, the accepted user
turn binding, interruption, delayed retrieval, duplicate events and reconnect.
The documented LiveKit pre-response hook requires agent-side detection for realtime
models; do not assume it runs with the existing provider-native configuration.

The first implementation remains SHADOW and records operational identifiers and
reason codes, not raw private content. Shadow has no conversation-provider
mutation call. OFF is the rollback: cancel outstanding reads, discard packets and
leave accepted behavior unchanged. A later APPLY design must independently prove
timing, prompt semantics, stale-packet rejection and owner-machine acceptance.

## Decision gates

- Research package: source citations, public fictional fixtures, protocol and
  structural validation; no claim that comparative trials ran.
- Comparison lab: functioning execution service and approved existing model
  route/allowance; no new purchases or real owner data.
- Shadow implementation: bounded architecture owner approval under Current Plan,
  isolated PR, TDD, full CI and failure-path review.
- Provider apply / natural admission / proactivity: separate designs and applicable
  explicit owner approvals; no promotion through benchmark scores alone.

This document leaves external vendor selection open until measurements. It does
not leave state ownership or the next bounded delivery ambiguous.
