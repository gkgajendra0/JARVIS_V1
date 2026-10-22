# Gemini Free-first / Paid-fallback: proposed architecture

Date: 22 October 2026. Status: **OWNER-APPROVED WRITTEN DESIGN** (22 October2026: “Approve written design”); implementation and live acceptance not started.

## 1. Requested outcome and inspected baseline

The owner requested automatic use of the existing Free Gemini project for eligible normal operations, bounded fallback to a separately funded Paid project on quota/rate-limit failure, and recovery to Free. Existing personal context, Authority, privacy, deterministic/local paths, ChatGPT-plan priority, cost optimization and dedicated TTS must survive. This request authorizes preparing software, not billing changes, credit purchases, paid live calls or protected-main merge.

Inspected and fetched the existing Desktop checkout `C:/Users/gkgaj/Desktop/jarvis_v1`: clean branch `feat/pi3-question-context-20261022`, local/remote head `211c3ade4d15ff41447524b4fa742b9cf552f0e2`. Protected `origin/main` is `7de92b3d` (PR #294). The candidate includes unmerged PI-2 #295 and PI-3A #296. Preserve that dependency; do not replace it with main or push changes into either existing PR. This design branch is `design/gemini-free-paid-fallback-20261022`.

The request is architectural: it extends target invocation, durable replay, cross-lane paid admission and Live transport replacement. Current Plan's research -> architecture -> explicit owner approval sequence and Quality Gates section 2 apply. Written-design review precedes the executable implementation plan. Retain the owner's Native execution preference for the eventual plan.

## 2. Findings and selected approach

Existing components to extend:

- `brain_routing/work.py`: Global Brain Router's deterministic/abstain/model decision; preserve it as the top-level cost/need policy.
- `model_routing/models.py`, `router.py`, `registry.py`, `eligibility.py`, `health.py`, `invoker.py`, `store.py`: existing provider-neutral target identity, credential_ref, immutable registry digest, target-scoped health, decisions, bounded attempts and durable lineage.
- `model_routing/cost.py`: versioned CostProfile, nullable unknown cost, routing-attempt telemetry and non-model provider events. Extend these owners for paid reservations/settlement and non-Work inference attribution; do not build an unrelated cost database/router.
- `work/reasoner.py`: existing routed reasoning, provider-failure classification, attempts and fallback. Inference is separate from capability execution.
- `hands/provider_adapters.py`: structured inference and ChatGPT-plan primary. The default factory currently resolves only the default provider key; the target adapter caches by target but does not forward credential_ref.
- `memory/learning_extractors.py`: Gemini Interactions extraction/resolution, accepted-source policy and sanitized failures. Its current failure boundary hides the normalized quota failure from a routing consumer; preserve sanitized public errors while carrying typed internal failure facts.
- `voice/livekit_session.py`, `voice/provider_resilience.py`, `voice/runtime.py`, `voice/canonical_active_speaker_runtime.py`: canonical conversation bridge, existing failure observer, controller and personal-context/learning integration. Current terminal failure/close marks canonical conversation failed/closed; a safe transport replacement must distinguish handoff from actual session close.

Options considered: (A) extend these owners and add a narrow shared invocation policy within model_routing (selected); (B) use only provider/LiveKit retry/fallback wrappers (insufficient durable decisions, shared spend and tool replay protection); (C) add a separate Free/Paid router (rejected, competing routing authority). No new third-party routing framework, inference provider, background polling service or package upgrade is proposed.

Pinned installation inspected without network inference: LiveKit Agents/plugin 1.8.3, google-genai 2.22.0. Agent.update_options can replace an LLM, while Gemini RealtimeModel.update_options cannot replace its key; construct a new model instance. Google documents resumption within a Live session, not cross-project transfer; do not assume a Free handle works on Paid. LiveKit documents explicit context propagation on handoff. These are supported interfaces to test against pinned code, not proof that live cross-project acceptance has happened.

## 3. Credentials, targets and routing priority

Keep `GOOGLE_API_KEY` as the existing Free credential. No alternate Paid variable exists in the inspected credential policy; add `JARVIS_GEMINI_PAID_API_KEY`. Resolve values from the launched Windows process environment at the credential boundary, by allowlisted reference, and pass an explicit key to each client. Never mutate process GOOGLE_API_KEY to switch clients. Do not place keys or key fingerprints in target IDs, reprs, logs, exceptions, telemetry, snapshots or commits. Tests use canary keys and assert their absence from diagnostics.

Continue existing `JARVIS_TTS_GOOGLE_API_KEY` / `JARVIS_TTS_OPENAI_API_KEY` and legacy TTS resolution independently. TTS is not silently switched onto the Paid fallback credential. No secret is requested in chat. A new terminal/process is needed after owner changes persisted Windows environment variables.

Extend existing ModelTarget registrations with separate service/model/credential-slot IDs, e.g. a new Gemini Free and Paid target for each eligible Work, Hands, memory and Live role. Reuse credential_ref; keep provider_id `gemini`. Free and Paid may use the same approved model but have independent health and prices. Per-model quota failures do not poison every Free model/service. Paid balance/auth failures disable the applicable Paid credential scope, not Free or dedicated TTS.

Ordering remains deterministic/cached/local where eligible -> configured ChatGPT-plan primary where already enabled -> eligible Gemini Free -> Gemini Paid only on the authorized pressure edge. Do not make Free outrank an accepted deterministic/local/ChatGPT-plan path. Preserve existing non-Gemini and local fallback edges/authority; this feature creates no new cross-provider release permission.

Fallback is explicitly opt-in (`JARVIS_GEMINI_PAID_FALLBACK_ENABLED`, default false). New configuration follows existing machine-setting precedence and environment-override policy. Missing Paid key, approval/configuration, price/FX bounds or budget admits no Paid traffic. Existing single-key behavior and old targets remain compatible while disabled. Enabling software is distinct from approving the first real paid test; implementation/tests must not activate it on the owner machine.

## 4. Eligible failures, bounded attempts and Free recovery

Use normalized provider failures from provider_resilience. Paid pressure fallback is allowed only for a Free request with verified quota/rate-limit failure (HTTP 429 or equivalent typed Gemini/WebSocket provider evidence), and after privacy/Authority/budget admission. Raw exception text is untrusted and is never an instruction. Authentication/permission/bad-request/model-configuration failures fail closed for this new paid edge and produce actionable sanitized diagnostics; they do not silently spend to hide a misconfiguration.

HTTP 402 / typed depleted Paid balance is non-retryable for the Paid credential scope; no automatic reload or purchase. Preserve existing unrelated failure-class meanings and serialized values. HTTP 503, timeout and network loss retain existing bounded resilience; they do not automatically trigger this newly funded quota-only edge. A project switch is not a demonstrated fix for provider-wide overload.

One logical request can visit Paid at most once. The Free->Paid path permits at most two inference target visits; an already-enabled ChatGPT-plan->Free->Paid path permits at most three. Bound all provider/SDK retries as part of the existing attempt policy; no nested invisible retry multiplier. Cancellation, stop, expiry and output already delivered can prevent replay even when a provider failure is eligible.

Extend existing target health with trustworthy Retry-After/reset information where available. Unknown 429 pressure uses configurable exponential cooldown (default 60 seconds, doubling to at most 15 minutes); it is not mislabeled daily quota. A verified daily-quota limit can defer to the next reset in America/Los_Angeles, including DST; do not infer a daily quota from RESOURCE_EXHAUSTED alone.

Recovery is demand-driven: after cooldown, at most one real eligible request claims a shared half-open Free lease. Other concurrent requests use the eligible existing path while it resolves. A successful real Free result marks that target healthy; another pressure failure extends cooldown. No periodic health generations, billable warmups, account/key rotation or endless probing. Retain failed Free attempts as failures, not rewritten successes.

For Live, a healthy Paid connection stays through active input speech, output playback and in-flight tools. Consider Free at the next safe idle/turn boundary or natural next session when cooldown allows. Do not terminate current speech just to reduce cost. A failed recovery attempt may return to the eligible Paid target within the same bounded handoff policy, with no duplicate tool action.

## 5. Shared paid ceiling, pricing and telemetry

Initial internal paid-fallback ceiling is **INR 350 cumulative for one explicit budget identity**, across eligible Live, Hands, Work and memory fallback. It survives process/runtime restart and concurrent callers; there is no automatic daily/monthly reset. Raising/replacing the budget identity is an explicit owner configuration action. It does not replace earlier whole-system monthly cost planning. No billing account API, payment method, balance top-up or auto-reload is added.

Extend existing cost/store ownership with additive budget/reservation/settlement records. Reserve integer INR minor units transactionally before a Paid SDK operation, using a stable invocation identity and compare-and-swap/transaction semantics. Spent plus outstanding reservations must stay within the ceiling. Test multiple connections/processes against the same ledger, not only an asyncio lock. Existing Work attempts remain the canonical attempt facts; cross-lane records reference their original lane/operation IDs without inventing WorkItems for voice or memory.

Each reservation pins model, credential slot, price profile/version/effective interval, modality rates, output/input/context bounds and INR-per-USD FX source/version/effective interval plus configured margin. Price data is a configured reviewed schedule citing the official pricing source; no speculative rate, invented exchange rate or live paid count-tokens request. Extend CostProfile additively for audio/video/cached/thinking dimensions actually charged. Missing/stale/non-finite price, FX, modality, output bounds or unsupported billing dimension makes Paid ineligible. Free project identity is configured by the owner; local code cannot prove a key's billing tier without account access.

Structured calls reserve a conservative upper bound covering bounded request size/context and maximum output including thinking, then settle against observed usage. Include paid context restoration, retries, failed attempts with uncertain usage and possible provider-side processing. Unknown usage remains unknown, never zero. Keep uncertain reservations charged/held and block further unbounded Paid admissions until safely reconciled. A cancellation or restart does not refund a possibly accepted provider request. An unsent request can release its reservation with evidence.

Live additionally needs bounded transport intervals, maximum output and retained context, modality-aware usage ingestion, and an outstanding reserve before audio/video can be sent. Reserve the next bounded interval before streaming it; stop admitting paid frames/output when a reserve cannot be acquired. Usage may be delayed/cumulative: deduplicate by transport epoch/event identity and account for context reprocessing. If pinned SDK metadata cannot support a defensible bound, Paid Live remains unavailable with an explicit reason; do not label an unbounded stream protected by a token-total counter. Keep safe local status/wake behavior available.

This is an internal admission ceiling, not a guaranteed cap on Google's invoice: asynchronous provider accounting, other software using the same project, taxes and FX can differ. The ledger reports known estimated spend, reserved/uncertain exposure, usage completeness, price/FX version, lane/model/target, failure class and fallback reason without private prompts or credentials. Do not advertise an exact remaining rupee balance when data is incomplete.

## 6. Durable replay and crash safety

Do not rename existing target IDs, rewrite old RoutingDecision/Attempt payloads, or change legacy registry digests simply by introducing optional fields. Preserve old serialized inputs/digest behavior when optional additions are absent. New Free/Paid registries/policy versions have distinct immutable identities and are persisted with nonsecret target descriptors sufficient for later replay. Registry identity excludes runtime health and actual secret values.

Resolve historical decisions against their original registry/policy. Retain the source-approved legacy default/ChatGPT pool so matching existing v1 decisions still replay. If a historical descriptor cannot be recovered/verified, fail closed with an explicit provenance diagnostic; do not reinterpret that decision under the new targets. Existing v1 decisions do not silently acquire a new paid edge. New v2 decisions persist the bounded Free/Paid lineage and resume it without generating duplicate routing-request IDs, attempts or spend reservations.

On crash after dispatch but before a recorded response, preserve an uncertain attempt and its exposure. Recover from durable evidence or report outcome unknown; never assume the request was unsent and dispatch another paid operation for free. Inference retry does not replay completed capability actions. WorkItem/WorkStep and Authority remain the owners of execution/recovery and irreversible effects.

## 7. Live voice handoff and personal-context continuity

The existing resilience observer/controller owns transport failure diagnosis and handoff scheduling. Extend that path using existing ModelRouter eligibility/target health/budget services; do not add a voice router that chooses independently. Select and reserve the Paid target before constructing a Paid RealtimeModel with its explicit key.

Prefer a supported Agent-level model replacement that keeps the live AgentSession, canonical bridge, tools, audio ownership and existing private session objects. Distinguish intentional transport retirement from logical conversation close/fail so handoff does not invoke final-close learning/private-context cleanup. If pinned SDK behavior requires replacing transport resources, rebind the same logical conversation/observers and test event ordering; canonical session identity and accepted turns are not recreated from raw provider history.

At handoff: fence old transport events/audio, stop stale output, collect the current accepted canonical snapshot and valid completed tool results, instantiate the same approved model/voice/options/tool schemas/instructions on the target, restore authorized context, and continue the already accepted unanswered question without demanding an extra wake where safe. Do not use a Free resumption handle on Paid. Do not replay raw microphone history, provisional transcript fragments, interrupted assistant tails or model-provided tool instructions as accepted evidence.

Deduplicate restored messages by canonical turn/tool operation IDs; observers must not learn the same turn again. Retain the existing tool execution ledger and one-shot Authority permits across reconnect. Completed tool calls are represented by their result, not re-executed. Pending/uncertain mutating tool work is reconciled through its canonical owner; it blocks automatic regeneration if replay could repeat an irreversible action. Never promise exactly-once remote side effects without an idempotency/reconciliation contract.

Personal-context release budget, selected evidence/currentness signatures, suppression/forget state, source eligibility and output guards survive or are re-established without broadening. Revalidate grant/session/OS continuity before restore, tool access and audio release. Do not renew the maximum 15-minute grant or five-minute idle timeout, rerun Hello automatically, or restore a previously retired private history. Expired/locked/forgotten state stops private continuation, even if Paid is healthy. Preserve all existing context-only/OFF paths and explicit mutation confirmations.

A response partially heard before failure must not be replayed from the start as though unheard. Continue only where canonical completion/output state is defensible; otherwise give a short local interruption status and request the missing detail. No-extra-wake continuation is best effort, not permission to invent unaccepted words or repeat an action. Speech addressing/phone-call discrimination is a separate known gap and is not changed here.

## 8. Hands, Work, memory and production composition

Inject the same target/credential-aware invocation and cost/health owners into eligible Gemini calls. Extend structured-client factory signatures compatibly so legacy clients/tests remain valid; cache by immutable target credential slot/model/generation, never a global switched key. Disable hidden SDK retries where the router owns attempts.

Work continues through GlobalBrainRouterReasoner -> ModelRouter -> ModelInvoker and the existing reasoner attempt ledger. Hands retains deterministic execution and ChatGPT-plan precedence; retry only semantic planning/validation calls before approved execution, not desktop clicks, sends, purchases, filesystem mutations or capability commits. Existing local fallback remains configured and governed.

Memory extraction/resolution/semantic calls may fallback as inference only. Recheck the original accepted source, grant, suppression and currentness after the provider await, before any admission. A fallback cannot extend an expired source deadline. Canonical memory writes retain existing idempotence/currentness rules; do not retry write admission as an inference operation. Private/local-only payload restrictions apply equally to Paid; an allowlisted key does not authorize new cloud disclosure.

Update production composition at its existing factory/runtime boundary, CLI preflight and bounded status diagnostics. Preflight reports slot/configuration readiness without paid model probes. Preserve dedicated TTS, local status speech, backend selection, machine-setting precedence and existing startup behavior while fallback is disabled. Do not start the local app or edit saved owner settings during implementation.

## 9. Verification and exact acceptance contract

Use synthetic/fake provider clients and forced SDK event boundaries; block external inference in tests. Add meaningful RED/GREEN cases before implementation, then targeted regressions, one fresh final review under Native execution and the required full suite/lint/format/whitespace checks. Any created review PR is isolated against the dependency and attached to this chat; protected merge is a separate owner step.

Required matrix:

1. Free success -> no Paid client/call/reservation; old disabled/single-key behavior unchanged.
2. Typed quota/rate failure -> exactly one eligible Paid attempt with the Paid canary key; unrelated target health unchanged; secrets absent in errors/logs/replay.
3. Cooldown -> no Free polling; one half-open demand request under concurrency; success returns future traffic to Free; repeated pressure extends cooldown. Verify daily reset/DST and Retry-After bounds.
4. Free/Paid auth/permission failures, Paid 402, 400/404, 503/timeout/unknown -> correct explicit classification and bounded policy, no purchase or accidental paid hop.
5. Missing/stale price/FX, missing/cumulative/duplicate usage, uncertain failures/cancellation, cap boundary, restart and multiprocess race -> no unknown-as-zero and no double reservation/settlement or admission beyond the internal ceiling.
6. Live accepted-turn/tools restoration, no extra wake on safe quota handoff, same voice/options, no duplicate learning observer and no replay of already played speech/completed tools. Verify failed setup, late old events, cancellation, speech-active recovery deferral and fallback exhaustion.
7. Personal-context OFF/context-only/APPLY, expiry/lock/stop, source/permit replacement, correction/forget, exhausted release budget and private-history retirement -> unchanged authority and data-release limits across both directions of reconnect.
8. New durable Work v2 fails over and resumes after process restart with identical request lineage and no duplicate action/cost; old v1 decisions/serialized fixtures/digests replay unchanged; unverifiable registry fails closed.
9. Hands/Work side effect succeeded or outcome uncertain before provider loss -> no automatic second action. ChatGPT-plan/deterministic/local/TTS paths remain unaffected.
10. Exact-head Linux/Windows/Hello/DPAPI and relevant SQLCipher checks; no old-head substitution. Report actual skipped/unavailable evidence and performance limits.

Owner-machine acceptance, **only after separate explicit paid-call approval**:

- Use the final reviewed source revision; keep both project keys in Windows environment variables and confirm they belong to separate intended projects. Preserve the dedicated TTS variable. Do not paste keys in chat or logs.
- Configure the reviewed price/FX schedule, INR350 cumulative budget identity and opt-in flag in a disposable/test profile using the existing profile mechanism. Record effective settings without secrets; no billing/account automation.
- Run the whole normal app with the intended personal-context/learning flags. Introduce only fictional facts and verify Free target use, real accepted conversation, correct ordinary responses and canonical save/recall behavior.
- Use a deterministic test-only failure injector restricted to the local acceptance harness (no production env-triggered fake quota). At most one controlled Free-pressure/Paid-handoff scenario after budget approval; do not burn real quota to manufacture exhaustion. Verify no extra wake, same tools/context, one action maximum and observed Paid usage/settlement.
- Release simulated pressure, wait for the configured cooldown and a safe boundary, then verify one demand-driven Free attempt and subsequent Free use. No paid/background probe loop.
- Exercise an interrupted non-destructive Work task, restart and resume the same WorkItem; compare lineage/cost records and action counters. Validate expired private session/forget and failed Paid/budget denial with injected failures instead of exhausting money or disabling a real key.
- Record expected/observed English/Hindi/Hinglish behavior, source revision, target transitions, known/reserved/unknown costs and provider errors. No owner-memory reset, raw private transcripts or isolated mic-only acceptance.
- Disable the opt-in flag to restore legacy routing. Keep historical attempts/reservations for reconciliation; disabling is not forgetting or deleting memory.

## 10. Sources, non-goals and approval

Primary sources checked on 22 October 2026:

- Google error codes: https://ai.google.dev/gemini-api/docs/api-errors (429 pressure and 402 balance exhaustion require different handling).
- Google rate limits: https://ai.google.dev/gemini-api/docs/rate-limits (limits depend on project/model; daily reset and actual capacity apply).
- Google Live session management: https://ai.google.dev/gemini-api/docs/live-api/session-management (resumption/connection lifecycle; no documented cross-project guarantee).
- Google Live usage: https://ai.google.dev/gemini-api/docs/live-api/capabilities (usage metadata and modality accounting).
- Google pricing: https://ai.google.dev/gemini-api/docs/pricing (configured price schedules must identify exact model/service/modality/effective version).
- LiveKit Gemini: https://docs.livekit.io/agents/models/realtime/gemini/ and handoff/context documentation https://docs.livekit.io/agents/logic/agents-handoffs/ . Installed source signatures were also inspected.

Non-goals: a new router/brain/store/provider, new models or dependency upgrades, billing administration, paid network tests before approval, automatic top-ups, key/project rotation to evade limits, universal 503 failover, per-speaker biometric/addressing changes, renewed private authority, full PI-2/PI-3 qualification, production deployment or protected merge.

Design assumptions requiring review: the initial INR350 allowance is cumulative and restart-safe, paid fallback is opt-in/off until owner activation, and its new automatic edge is quota/rate-limit-only. These choices fulfill the request without silently granting purchases or unlimited retries. No implementation plan or product changes are marked complete by this document.
