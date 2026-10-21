# Automatic conversational learning for JARVIS

**Date:** 21 October 2026. **Status:** proposed written design for owner review.
**Baseline:** main `7de92b3d0507ca52cfa3b653ddd976e3356a7102`.
**Branch:** `feat/personal-auto-learning-20261021`.
This document does not enable capture, change installed settings, or approve a
new production permission. CAP-053 remains partial until implementation and
normal-app acceptance prove the behaviors below.

## Owner-readable decision

JARVIS should learn useful everyday facts from an ordinary conversation without
asking “shall I remember that?” or requiring “remember” in each utterance. It
should retain those facts across restart, use relevant current facts in later
answers, and honor changes, corrections and forgetting.

Reuse the existing model integration, encrypted memory and voice runtime. Add
automatic admission and reconciliation; do not add another primary memory
service or train an AI model from scratch. Do not repeat the previous broad
vendor benchmark. A newly observed failure can justify a targeted adapter study.

**Material proposal requiring review:** the first release uses an explicitly
opened, private owner session. One Windows Hello challenge opens a 15-minute
memory session; five minutes without accepted user input ends it sooner. The
owner is delegating the active conversation input channel for standard personal
memory reads and automatic learning during that period. There is no per-fact
confirmation or Hello challenge, and no automatic renewal. Wake/sleep does not
extend the grant. Restart, Windows lock/disconnect/logoff/user switch, manual
clear or an unhealthy continuity monitor revokes it.

This is **session delegation, not biometric attribution of every speaker**.
Windows Hello verifies the person opening the session; it cannot establish who
speaks later. Current CAM++/active-speaker diagnostics remain shadow. A guest
speaking inside a delegated session might be treated as the input source; that
case is not solved by a timeout or owner presence on camera. Initial support is
therefore private, owner-operated conversations only. No shared-room/guest-safe
claim or unattended always-on owner capture is permitted from this design.
If the owner requires verified identity for every turn instead, production
activation must wait for a separately qualified attribution path. The system
must not silently choose that trade-off for the owner.

## 1. Intent, constraints and success

Confirmed intent from this chat:

- Automatically remember important information without a save question.
- Automatically use relevant information in future conversation.
- Use existing advanced technology where it demonstrates value; research widely
  first, then narrow on evidence rather than inventing basic AI capabilities.
- Reuse prior tests and their failures; test the actual complete local JARVIS.
- General fictional English, Hindi and Hinglish scenarios are sufficient before
  owner acceptance. Owner-authored examples and isolated spoken demos are not
  prerequisites.

Proposed first-release scope: ordinary standard-sensitivity owned items (including
multiple vehicles), food/response preferences, explicitly stated routines and
ongoing goals. Only directly stated information qualifies. A one-off choice is
not silently generalized into a stable preference. Inferred traits, medical or
financial details, credentials, private/local-only facts and third-party profiles
do not acquire automatic admission under this first grant. Existing explicitly
governed memory operations remain available for their accepted scope.

Acceptance scenario: an owner session casually supplies two fictional vehicles
and a dietary preference, then resumes after restart with a new owner session.
JARVIS uses appropriate current facts in a relevant request. Selling one vehicle
preserves the other; correcting a preference changes later answers. Forgetting
removes the relevant memory and prevents old work from putting it back. At no
point does JARVIS ask to save each eligible fact.

Non-goals: continuous ambient recording, full transcript retention, new reminder
execution, autonomous external actions, new voice/vision models, personal model
fine-tuning, a graph-database migration, global Hands permission changes, or
claiming an entire Iron Man-style assistant is complete.

## 2. Research and approach decision

Three considered approaches:

1. **Extend native JARVIS — selected for this slice.** Reuse provider-native
   extraction, SQLCipher/DPAPI, canonical lifecycle and personal-context tools.
   New engineering is application-specific admission, identity/lifecycle binding
   and useful later use. Selection is about integration fit, not a measured
   finding that native extraction always beats external frameworks.
2. **External extraction/retrieval adapter.** LangMem and Hindsight remain
   replaceable candidates when a specific gap warrants them. An external
   extractor would still return proposals to the same JARVIS admission boundary;
   it would not gain write or permission authority.
3. **External memory runtime takeover.** Not selected: replacing canonical truth,
   migrating owner history and reconciling two state/permission systems are not
   prerequisites to this behavior.

Evidence to preserve:

- Historical Qwen/BGE/EmbeddingGemma, fusion and reranking comparisons establish
  useful ranking components, not reliable automatic admission or answerability.
- Qwen utility classification, GLiClass Mini/Ultra question roles, frozen
  embedding/LogisticRegression guards and several QA/NLI release formulations
  failed their tested roles. They are not proposed again as default gates.
- LangMem's recorded 18-case pilot had 11/18 correct labels. Native recorded
  14/18 recovered across runs and also had failures; that is not a clean
  generalized winner comparison.
- Hindsight's smaller recorded tests underperformed lexical matching. The later
  supplied handover reports 240-fact decisions of 56/68 at K=8 and 63/68 at K=16,
  whereas the older protocol still says not measured. Preserve that later
  owner-reported evidence and the provenance discrepancy, not an “overall failed”
  label. Retrieval plus fixture decisions did not prove natural capture/use.
- The new model role remains the active provider's configured extraction model;
  the repository Gemini default is `gemini-3.5-flash-lite`. Voice model and
  provider family are not changed. Existing APIs/SDKs are reused; no package
  upgrade, extra model download or external service is a prerequisite.

New targeted source checks confirm two limits: Google's structured output
requires application validation of semantic values, and Microsoft's
UserConsentVerifier verifies the person responding to the challenge. A schema
and an authentication event do not independently prove later fact semantics or
speaker identity. See sources in section 12.

## 3. Runtime flow and ownership

```text
owner opens scoped memory session -> Authority-issued in-memory grant
accepted canonical USER turn -> ephemeral source receipt -> bounded worker
  -> structured extraction of multiple grounded candidates
  -> importance / source / sensitivity / suppression checks
  -> authorized canonical candidate lookup + reconciliation
  -> JARVIS-built exact mutation + one-use child permit
  -> atomic canonical lifecycle write + idempotence receipt
later question -> permitted current-fact selection -> existing voice tool result
  -> answer/audio guarded by grant, question binding and record versions
```

ConversationSession owns accepted text; Authority owns grants and child permits;
MemoryRuntime owns SQLCipher connections; the canonical lifecycle owns mutation
and history; the voice runtime owns capture and provider/audio retirement.
No model can create an accepted source, grant, permit, canonical assertion ID or
verification status. Do not relabel extracted candidates `OWNER_EXPLICIT`.

Candidate processing runs at runtime scope so ending a wake/provider session
does not accidentally cancel an eligible, already accepted turn before admission.
It retains only bounded process-memory receipts, never durable raw turns.
Shutdown cancels pending work; committed canonical facts survive restart.

## 4. Session permission contract

Add the permission as a narrow extension of existing Authority/CapabilityRuntime,
not a global T2 relaxation or a second permission system. Opening the session
binds a code-owned policy version/digest, runtime nonce, Windows session identity
and continuity generation, configured active provider, monotonic creation/expiry
and allowed memory operations/categories. No model-supplied TTL or scope.

Register a distinct code-owned personal-learning capability and narrowly scoped
policy operation. Policy evaluation must require the fresh strong approval for
opening that exact delegation and validate its registered scope for each child
permit. Extend the existing policy/registry contracts explicitly; do not classify
arbitrary persistent writes as low-risk or treat a Python receipt object as an
approval. The grant cannot satisfy a T3 requirement for an unrelated action.

The grant allows eligible standard owner-fact reads and automatic create/change/
correction/retraction proposals within that policy. Each commit obtains a child
permit bound to its source receipt, exact payload digest, resolved target/version
and suppression epoch. Child permits are one-use; proposal confidence cannot
substitute for one. Opening a grant neither opens an existing private record nor
authorizes medical, financial, external, file, device or code actions.

Existing exact-request memory mode remains the fallback. Explicit physical
forget and private/local-only operations retain their existing action-specific
approval; this release removes per-fact *automatic save* approval, not unrelated
destructive/security gates. Denied or expired auto sessions do not trigger a
Hello prompt for every candidate. The system reports the session state locally
and continues ordinary conversation without personal-memory access.

Grant invalidation and final commit use the existing serialized/locked authority
boundary. Validate before any protected lookup, before provider release, inside
the write transaction and before audio starts. Lock/expiry while an inference is
pending discards its proposal and clears protected output. Grants never persist
or silently survive restart/reconnect.

## 5. Grounded multi-fact extraction

Extend the existing extraction adapter with a separate batch contract so the
accepted single-proposal shadow path and explicit controls do not break.
Input is the accepted source turn plus at most three preceding accepted USER
turns from the same delegated input session, total at most 8,000 UTF-8 bytes.
Oversize inputs are rejected, not truncated into a different claim. Prior turns
help references; they cannot independently authorize replayed writes.

Return at most eight proposals with category, direct-statement/change/correction/
retraction/transient disposition, bounded values, evidence references and
confidence as diagnostics. Every new value or identity label must be supported
by an exact source span from the accepted input, with original script preserved.
Application checks validate span offsets/content, source identity, latest-turn
anchoring and temporal consistency. A grounded span does not prove the model
understood ownership/negation; holdout tests separately measure those semantics.

No assistant text, web/email/file content or tool result is an owner statement.
Quoted, hypothetical, uncertain or temporary statements do not become durable
ownership/preferences. Current “do not remember this” controls veto the turn
before extraction and invalidate already queued candidates from that turn.
Ambiguous candidates are dropped from durable admission without a save prompt;
JARVIS may ask a useful factual clarification when the conversation requires it.

Raw utterances and source spans remain ephemeral. Canonical provenance stores
turn/source references, time and evidence digest, with `evidence_text=None`, as
required by the existing lifecycle. Saved normalized facts are the intended
personal memory, not an excuse to retain the full conversation.

## 6. Canonical representation and reconciliation

Use existing semantic assertions and their supported TEXT/JSON value types.
Add typed application schemas, not an external entity database. Owner remains
the canonical subject. Stable scalar facets use a code-owned registry. Each
owned item, routine or goal receives a server-generated opaque entity ID and
predicate, allowing two vehicles to exist without overwriting one scalar key.
JSON values hold the typed standard fact; `normalized_text` provides a bounded
human-readable fact for existing retrieval/context delivery.

Model reconciliation can select only candidates from a bounded authorized
catalog of actual current assertion/entity IDs or `new`/`uncertain`. The server
resolves IDs and versions. Expose only standard, policy-eligible records, after
session validation; do not use catalog membership as a private-information
oracle. Consult existing exact/lexical/eligible semantic retrieval. Do not make
dense scores alone identity or overwrite authority.

Actions:

- New directly supported item: create a stable item identity.
- Proven same current value: no-op, not a duplicate record.
- Real-world change (“sold the bike”): close current ownership while preserving
  legitimate history; leave other vehicle records untouched.
- Explicit factual correction: use lifecycle correction with exact version.
- Withdrawal: retract only the uniquely resolved supported assertion.
- Unclear referent or conflicting candidates: no canonical change.
- Legacy explicit text facet: preserve it; do not guess a destructive conversion
  into new entities. A uniquely supported mapping can be proposed, otherwise
  omit an automatic write rather than create contradictory owner facts.

The new admission method belongs in MemoryService and invokes the existing
MemoryLifecycleService. Existing explicit methods still require explicit-source
provenance. Automatic admission accepts only an Authority-issued delegated-owner
receipt and records `OWNER_DIRECT`, not invented explicit approval or factual
verification. Add transaction-batch support where one utterance needs multiple
related mutations; validate all targets before the batch commits.

## 7. Persistence, replay and forgetting

Add one forward-only migration in the existing encrypted database for learning
idempotence receipts and auto-learning suppression metadata. Do not edit the
accepted migration files. A receipt binds source-turn identity, candidate ordinal,
policy version and semantic payload digest; replay cannot duplicate a commit.
All receipt/epoch/target checks and lifecycle writes occur atomically through the
existing serialized writer. Concurrent explicit changes force a stale result;
they do not silently overwrite a newer version.

Physical forget purges the targeted entity's current/history/source/derived
representations, invalidates provider context and pending proposals, and places
a standard registry-facet-level suppression marker. It retains no forgotten
value, label, raw text or reconstructible low-entropy value hash. For the initial
release, forgetting one vehicle conservatively disables future *automatic*
vehicle learning until an explicit re-enable/remember operation; surviving
vehicles remain readable. This policy avoids retaining the forgotten bike's
identity just to recognize it later. Explain the scope in inspection/status,
not an unsolicited spoken prompt.

Forget also removes learning receipts/payload digests tied to the forgotten
assertions and their source lineage. Replay prevention thereafter relies on the
scope suppression and source-epoch invalidation, not retention of a hash from
which a forgotten low-entropy value could be reconstructed. Existing-memory
forget and the suppression/receipt cleanup must share the same transaction.

“Don't remember this” vetoes the current turn. “Don't remember my vehicles”
suppresses that facet class. Auto-learning OFF revokes grants and cancels pending
work, without deleting existing owner memory. Uncommitted receipts are discarded
on shutdown; no durable retry queue stores original utterances.

## 8. Importance, freshness and resource bounds

The first policy permits directly stated stable preferences, owned items,
explicit routines and ongoing goals because they can affect later assistance.
No model-selected importance threshold alone grants a write. Temporary needs
remain in existing LiveContext for that conversation and are not silently made
permanent. Completed goals/ended ownership become historical, not current.
Changeable old facts can be qualified as last known; no arbitrary “still true”
claim follows merely from persistence.

Proposed fixed bounds for the first implementation:

- 32 queued turn receipts, at most 8,000 UTF-8 bytes each; maximum one extraction
  and one reconciliation provider call per processed turn; no automatic retries.
- One background inference in flight; extraction timeout 10 seconds,
  reconciliation timeout 10 seconds; receipt maximum age 30 seconds.
- Up to eight proposed facts per turn; up to 32 reconciliation candidates.
- Do not perform extraction on every audio frame or partial transcript. A new
  accepted turn can cancel a pending unstarted no-longer-useful request.
- Queue overflow drops new candidates with a status count; it never blocks voice.
- Existing context limit remains at most four facts and 1,800 UTF-8 bytes per
  answer until a separate measured adjustment is justified.
- No new always-resident GPU model or service. Report provider calls/tokens and
  background latency; do not describe cloud inference as free or purely local.

These bounds are proposed engineering settings, not measured quality claims or
an agreed new spending budget. Preserve existing provider/quota controls; no paid
fallback, credit purchase or new service account is authorized by this design.

## 9. Relevant use and provider/audio lifecycle

Keep normal-app personal-context tools. The scoped grant replaces repeated
exact-read approval only for eligible standard facts within the delegated
session; it does not widen sensitivity. Selection must honor the actual asked
relation: an owned bike does not answer why it was bought; a preference does
not prove medical restrictions or a budget. Unknowns remain unknown.

Maintain per-answer question binding, canonical version checks and audio guards.
Current one-personal-answer provider-history retirement remains the initial
qualified boundary; a fresh wake can reuse the live scoped grant without another
Hello. Do not claim seamless multi-turn private history. A later question must
read current facts again. On correction/forget/expiry, retire provider history
and queued audio before another answer can use a stale released fact. Protect
against a background commit retiring its own source before the transaction ends.

Normal conversation continues while learning runs. Never announce a successful
permanent save from model prose or a pending extraction. If the owner asks whether
something was remembered, answer from canonical commit evidence. No unsolicited
save prompt or per-fact success announcement is required.

## 10. Component boundaries and implementation order

Proposed new modules (not implemented by this document):

| Component | Responsibility / existing integration |
| --- | --- |
| `authority/personal_learning.py` | Scoped delegation, grant validation and child permit lifecycle; reuse existing authority session/approval/permit infrastructure |
| `memory/learning_contracts.py` | Batch proposals, span receipts, typed entity/scalar facts and admission results |
| `memory/learning_policy.py` | Source/category/lifetime/suppression eligibility, independent of model confidence |
| `memory/learning_reconciliation.py` | Bounded closed-ID catalog resolution, exact target/version and create/change/no-op/uncertain plan |
| `memory/learning_runtime.py` | Runtime-scoped bounded worker and ephemeral receipt cleanup |
| Existing `memory/service.py`, `lifecycle.py`, `runtime.py` | Sole facade, transactional canonical lifecycle and database worker ownership |
| Existing `memory/extractors.py`, `ai_provider.py` | Active-provider structured batch/reconciliation adapters, no new vendor runtime |
| Existing `capabilities/runtime.py`, `voice/personal_context.py` | Scoped authorization and current-fact release, preserving legacy exact mode |
| Existing authority policy and capability registry | Explicit registered memory-only delegation rule; unrelated persistent/destructive operation requirements remain intact |
| Existing `voice/production_runtime.py`, `agent.py`, `config.py` | Normal launch integration, session state, prompt/policy alignment and OFF path |
| New memory migration | Atomic receipt/suppression metadata in existing SQLCipher, no second truth store |

Implementation sequence after written-design and task-plan review:

1. Scoped authority and revocation contracts, including explicit delegation limits.
2. Batch extraction and typed eligibility with fictional provider fixtures.
3. Entity reconciliation, transactional admission/replay and forgetting suppression.
4. Normal-runtime worker and grant-backed standard context delivery.
5. Provider-shaped fictional end-to-end qualification, cost/latency evidence and
   regression suite, followed by normal local-app owner acceptance.
6. Documentation/ADR reconciliation, reviewed PR and separately authorized
   protected promotion. Production activation is not inferred from unit tests.

This is an architecture/spec sequence, not the reviewed executable task plan.

## 11. Verification and release criteria

Write meaningful failing contract tests before implementation; reuse accepted
fixtures only where their scope allows. Retired research corpora are not fresh
acceptance material. Fresh held-out conversations cover:

- Two items from one utterance, multilingual equivalent facts, genuine changes,
  false prior statements, retractions and missing references.
- Current-user fact vs quotation/hypothetical/third party; transient vs stable;
  no-per-fact-confirmation behavior and no false claims of successful saving.
- Existing scalar/legacy text conflicts, same-model two-vehicle ambiguity,
  concurrent explicit correction and duplicate/replayed accepted events.
- Grant absent/expired/denied, lock/unlock epoch changes during inference and
  transaction/audio release, process restart, provider timeout and queue overflow.
- Forget one item without removing the other, physical history/derived cleanup,
  no stale provider audio and no old candidate re-admission.
- Relevant personalized advice vs unrelated question, unknown requested relation,
  corrected preference, absence of memory and honest unavailable states.

Hard requirements: no unpermitted canonical write/release; no duplicate commit;
no wrong-item update in tested cases; no sensitive/secret automatic admission;
no save question for eligible facts; restart persistence and complete correction/
forget propagation; explicit evidence when a provider/case is unavailable.

On the fresh semantic holdout, proposed release floors are: auto-admission
precision at least 0.95, capture recall at least 0.80 overall and 0.70 in each
of English/Hindi/Hinglish, and relevant-use success at least 0.85 overall with
no observed false personal claim from absent/irrelevant facts. Publish raw counts
and uncertainty; do not turn these empirical floors into guarantees. Any hard
permission/lifecycle failure blocks release regardless of aggregate score.
Holdout size must be chosen and frozen before execution; it is part of the
subsequent task plan, not an opportunity to stop when a favorable score appears.

Measure baseline vs enabled voice callback latency, time to first speech,
background p50/p95 latency, tokens/calls, process/GPU memory and queue pressure.
Proposed local scheduling budget: added accepted-turn callback p95 <=10 ms in
the same controlled harness. Real provider/audio measurements must be reported
separately; do not claim a latency win from incomparable earlier experiments.

Owner acceptance is the whole normal local app: supply fictional facts, restart,
ask relevant questions, change a fact and forget it. The owner is not asked to
complete another broad vendor benchmark or a standalone microphone demo.

## 12. Research provenance and review boundary

Repository authorities: `docs/PRODUCT.md`, `docs/CURRENT_PLAN.md`,
`docs/QUALITY_GATES.md`, current architecture and the bounded October 21 acceptance.
Existing broad research: `docs/research/STEP4_MEMORY_DECISION_MODERNIZATION_2026-10-16.md`
at historical ref `efff5b4f6c7a9309027bbd96f2dda4870f49dc32`; original Step-4
technology/results and deferred closures at
`677badddbba8d7739344d849f891158e6bd6f566`; October 19 native architecture.

The detailed source inventory is also saved at
`C:\Users\gkgaj\Documents\ChatGPT\Jarvis_V1\reports\JARVIS_PRIOR_MEMORY_TECH_EXPERIMENT_AUDIT_2026-10-21.md`.
Its historical evidence stays distinct from production state.

Targeted primary-source check, 21 October:

- [Google structured output and application value validation](https://ai.google.dev/gemini-api/docs/structured-output).
- [Microsoft UserConsentVerifier](https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.ui.userconsentverifier).

Owner review must cover the private-session delegation trade-off, initial
categories, resource/session limits, conservative facet suppression after forget
and retained fresh-wake boundary. This written design does not claim owner
approval of those concrete details merely because the feature goal was approved.
After review, write the executable task plan and proceed with the selected
implementation workflow. No product code or installed configuration changes are
part of this design-only commit.
