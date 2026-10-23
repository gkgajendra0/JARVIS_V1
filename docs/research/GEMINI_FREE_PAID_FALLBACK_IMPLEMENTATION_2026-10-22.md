# Gemini Free-first / Paid-fallback: implementation and acceptance record

**Later controlled Live amendment, 23 October:** public adapter/handoff implemented; final source b663dbbe passed 3,177 tests with 8 platform skips after one independent review and repair pass. Actual Paid voice remains denied for unqualified auxiliary accounting. The historical findings/results below describe the earlier candidate; the [new implementation and remaining-work record](GEMINI_CONTROLLED_LIVE_IMPLEMENTATION_2026-10-23.md) supersedes its transport status. Final exact-head hosted receipts are in draft PR #298; no real Paid call, activation or merge.

Reconciled 23 October 2026. Historical design/plan filenames retain 22 October.

## Actual outcome: PARTIAL candidate, not complete requested voice failover

Work reasoning, structured Hands planning, automatic memory extraction/resolution,
legacy candidate extraction, semantic recall and its release verifier consume the
existing ModelRouter through one protected RoutingRuntime and one cumulative
INR350 governor. Default OFF. No saved machine setting, owner-memory data, billing
account or project was changed. No paid or free inference was made for these tests.

**Automatic Paid Gemini Live voice is unavailable in this candidate.** The public
handoff/context/tool fences are implemented and fake-transport verified, but the
installed SDK cannot prove every charged reconnect/generation is admitted before
send. The real provider factory denies Paid Live before resolving its key or
constructing a client, including callers supplying arbitrary budget objects.
Normal/startup/standby/ephemeral voice retains the existing Free path. This does
not satisfy the full requested Paid voice continuity goal; do not merge/promote
or describe this as fully completed Gemini voice fallback.

Source branch: `feat/gemini-free-paid-fallback-20261022`; actual dependent base
`211c3ade4d15ff41447524b4fa742b9cf552f0e2` on
`feat/pi3-question-context-20261022` (#296, itself dependent on #295).
Product repair checkpoint (full local3071pass/8skip): `4782cdae1eb46c8fc81210f4fe1ef988c61d83bd`.
Implementation checkpoint before final review: `576463a3a0baca5b9022770a1b4a5ccf7daf9ba4`.
No main merge is authorized. Existing PI-2 extended-provider qualification and
PI-3A actual-model/spoken acceptance remain pending/deferred, not passed here.

Owner subsequently approved the [controlled Live plan](../superpowers/plans/2026-10-23-gemini-paid-live-controlled-transport.md) and Native offline execution. That extension is now in progress; no real Paid calls, activation or merge authorized. Its later source requires fresh verification.

## Routing and credential ownership

- Global Brain Router retains deterministic/local decisions. Phase-4 ModelRouter
  remains sole model selector. RoutingRuntime composes these services; it is not
  another router, authority, personal brain or memory database.
- Configured ChatGPT-plan priority stays ahead of Gemini; disconnected plan
  sessions become unavailable runtime facts. Saved Work retains its original
  decision order/identity and rechecks current availability before dispatch.
- Free uses `GOOGLE_API_KEY`; Paid uses `JARVIS_GEMINI_PAID_API_KEY`, resolved
  centrally from process/Windows user environment. No global key swapping.
- Dedicated TTS credentials and existing local/non-Gemini fallbacks are retained.
  This candidate funds bounded structured inference, not separate TTS or visual
  computer-use model calls. Existing Authority still owns every actual action.
- New targets use `{role}.gemini.{free|paid}.{model}` and registry version2.
  Legacy no-extra-fields registry digest remains
  `c200287907fdc1b68ad95c5ce4d3ba4b059a8372015885df14fcfd960af1d00c`.
  Additive immutable registry/price snapshots permit verifiable v2 replay; unknown
  or unverifiable historical registries fail closed. This is not a guarantee for
  arbitrary v1 model drift without a saved or source-approved historical registry.

Only genuine Free Gemini quota/rate-limit pressure creates the new Paid edge.
HTTP503/timeout/unknown/auth/request/model errors do not. Paid is visited at most
once per logical request; Free->Paid has at most2 target visits, configured
plan->Free->Paid at most3. A transient Free failure may earn one additional,
recorded same-target retry under existing health policy, never an extra Paid visit. Pinned Interactions resource retries are explicitly
turned off; the SDK normalized constructor attempts=0 back to retries otherwise.
Paid401/typed402 disable the Paid credential scope, independently of Free/TTS.
There is no automatic balance reload or hidden credential/account rotation.

Free pressure is durable and target-specific. Unknown limits use bounded60s
exponential cooldown, capped900s. Trusted Retry-After can exceed that cap; verified
per-day quota uses next Pacific midnight including DST. Ambiguous text is not
interpreted as a daily reset. Later pressure cannot shorten an existing trusted
cooldown. A shared CAS half-open lease permits one real demand attempt. Once a
call starts, PID plus process-creation identity fences it beyond claim expiry;
a dead owner is reclaimable after expiry, and cancellation releases ownership.
A hung/inaccessible process conservatively keeps the recovery slot occupied.
There is no background health generation. Success of actual inference is recovery
proof. Failed, completed or uncertain actions are not automatically replayed.

## Spending safeguards and honest unknowns

Default budget identity `gemini-paid-fallback-v1`, cumulative ceiling35000paise.
This is an internal admission ceiling based on reviewed conservative exposure,
not a provider billing balance, purchase authorization or guaranteed invoice cap.
Budget identity/ceiling is immutable once initialized; reopening cannot reset it.
All eligible lanes use the canonical protected SQLiteWorkStore extensions,
including when Work/DBOS execution is disabled. No fake WorkItem is created.

Each Paid dispatch requires a matching model/service price version, unexpired
price/FX intervals and complete usage dimensions. UTF-8 request/schema/envelope
bounds and a supported SDK output-token cap are reserved atomically before send.
Known usage includes thought tokens; cache is conservatively charged at full
input rate. Missing/partial/tool-use metadata cannot become zero. Possibly sent
calls retain exposure; incomplete usage blocks further Paid admission. Abrupt
process exit retains committed holds. Only proven-unsent cancellation refunds.
Observed overruns are recorded without clipping and block new Paid admission.

Accepted v2 Work inference results are codec-protected in the existing store and
reused on restart without another provider call, including a new price/FX config.
Unknown in-flight outcomes and repeated scoped identities fail closed. Unknown
v2 Work claims/exposure block the whole WorkItem across scheduler blocker/version
changes, so bookkeeping cannot buy a duplicate Paid request. Scoped memory/Hands
results are not cached as another personal payload store.

Routed semantic release re-reads the same exact current eligible assertion before
every Free/Paid dispatch and after the result. Forget, correction or conflicting
current evidence prevents release. The actual recall tool also binds these checks
to the original accepted conversation/utterance/activity epoch; session close or
a new request cannot release its old fact to a fallback. This grants no new
Authority or private-session consent.

Local status reports key-presence booleans (not validity), effective mode,
target cooldowns, price/FX versions and known/reserved/unknown exposure. Preflight
is informational for optional Paid unavailability and makes no inference probe.
Actual production model prices, FX, account project separation and Paid account
readiness have NOT been certified; synthetic tests are not market-price evidence.

## The precise Paid Live blocker

Installed/tested: LiveKit Agents/Google plugin1.8.3 and google-genai2.22.0.
`Agent.update_options(llm=...)` rejects a running realtime-model swap in this SDK;
public `AgentSession.update_agent` with bounded readiness is used instead.
Accepted canonical user/assistant turns and inert completed-invocation receipts
are restored, not provisional transcripts, provider handles or raw tool outputs.
Original tools, grants, selected evidence, release limits and private deadlines
remain; no new Hello or900s/300s renewal. Old streams/functions/audio/errors are
fenced by epoch and private output authorization. An untagged logical CloseEvent
still closes the logical session. Partly heard replies/pending or completed tools
prevent automatic replay. A safe unanswered user request can continue in the
fake-transport handoff harness without another wake word.

The REAL pinned SDK with ONLY its network client replaced reconnects twice on a
server GoAway with max_retry=0. Connection metrics arrive after the handshake;
tool/config changes can also restart the transport. Public frame/output gates
and per-generation max_output_tokens cannot bound all automatic reconnect/context
reprocessing or all server-driven turns. No SDK-private mutation or fabricated
per-second upper bound was added. `GeminiLiveBudget` is explicitly a compatibility
denial, not an implemented/funded streaming accountant. Consequently cumulative
Paid Live modality accounting, real Paid handoff and production Free-return from
Paid Live are not activated or qualified. Fake-transport recovery tests do not
prove those production features.

Next authorized work: implement the [controlled Paid Live transport design
proposal](../superpowers/specs/2026-10-23-gemini-paid-live-controlled-transport-design.md)
(OWNER APPROVED23October for Native offline implementation; not yet implemented) for a controlled Live transport adapter using supported Google/LiveKit interfaces (or a reviewed
upstream hook/version), covering pre-connect and per-turn admission plus existing
full-duplex/private/tool behavior. Retain this denial until the approved controlled transport is implemented and
verified. Increasing spend or bypassing the gate is not a fix.

Primary references: [Google Live protocol](https://ai.google.dev/api/live.md),
[Live session management](https://ai.google.dev/gemini-api/docs/live-api/session-management),
[LiveKit Google model API](https://docs.livekit.io/reference/python/livekit/plugins/google/realtime/index.html),
[Google thinking/output tokens](https://ai.google.dev/gemini-api/docs/thinking),
[Interactions reference](https://ai.google.dev/api/interactions-api-v1),
[official model prices](https://ai.google.dev/gemini-api/docs/pricing).
The reconnect and swap conclusions above also come from installed source and
executed pinned-SDK characterization tests, not assumptions about latest releases.

## Verification record

- Latest complete affected-task receipt:882 passed in95.17s; fallback, learning,
  routing/global brain, cost/provider resilience, voice/context, Hands and Work.
- Observed RED then GREEN: missing credentials/targets/scoped persistence,
  admission/price/unknown accounting, cross-process leases, actual SDK retries,
  shared factories, current source/Authority validation, voice epoch/context/tool
  fences, Paid401 scope, scoped status and connected-plan drift/durable resume.
- Real3-process Work/Hands/memory reservations contend for one35000paise budget;
  one20000 reservation wins and two are denied. Paid Live is excluded explicitly.
- Real `os._exit` after dispatch and after settlement retains durable reservation
  or exactly-once settlement. A repeated invocation cannot dispatch/refund again.
- Real canonical temporary memory/Authority lock/expiry/forget gates stop release
  and admission; original permits/deadlines remain. No owner DB was opened.
- Actual Hands orchestration with fake OS executor writes once for confirmed and
  unconfirmed outcomes, including subsequent quota/Paid inference. Actual SDK tool
  execution counter remains1 across the fake handoff. No real clipboard/action.
- One fresh independent review of211c3ade..acd33067 found six code defects;
  all entered one repair pass with observed failing tests first. Original-session
  release and cancellation cleanup regressions extended those same findings.
  No second review or implementation delegation was used. No deferred minors.
  See [review and verification evidence](GEMINI_FREE_PAID_FALLBACK_REVIEW_2026-10-23.md).
- Full-suite checkpoint before the final original-session guard:3069passed,
  8skipped,222.65s. 3,071 passed, 8 skipped in293.63s (4m53s); full repository pytest, isolated machine profile. Ruff check passed,1,043 files formatted, git diff --check passed..
- Exact-head hosted CI and draft PR: [Draft PR#298](https://github.com/gkgajendra0/JARVIS_V1/pull/298). Immutable checkpoint `bbaa99d45a86d4cea88b79f1f99781fe7193b25c`: all7hosted jobs passed; [CodeQuality](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/39932296115) Linux3073pass/6skip, Windows3075pass/4skip, Ruff, Hello, DPAPI, promotion-policy; [SQLCipher4.17](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/39932291571) build/bake-off/production adapter. These checks do not certify later controlled-Live changes.. These remain
  separate from real Paid provider/whole-app acceptance, which was not run.
- Performance: no active streaming budget/frame path exists, so there is no valid
  Paid Live overhead/latency measurement. Fake handoff readiness is bounded10s,
  and may drop unaccepted transition audio. No real provider latency was measured.

## Reproducible safe local checks (no live API)

From the Desktop checkout on this feature branch:

```powershell
Set-Location "$env:USERPROFILE\Desktop\jarvis_v1"
git status --short --branch
.\.venv\Scripts\python.exe -X utf8 -m pytest -o addopts= tests/gemini_fallback -q
```

Tests replace provider transport, isolate settings/stores and block external
network. They do not activate the normal app, change Windows environment settings,
read real personal memory, or spend provider quota. Full repository pytest uses
an isolated JARVIS_MACHINE_CONFIG and restores the prior process value.

## Whole normal-app owner acceptance: pending, no paid execution authorized

1. After the final reviewed revision/CI is recorded, preserve any local changes.
   In a clean checkout use `git fetch origin`,
   `git switch feat/gemini-free-paid-fallback-20261022`, then
   `git pull --ff-only origin feat/gemini-free-paid-fallback-20261022`.
   Install with `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.
   Do not reset/clean/rebase away owner changes or merge dependencies implicitly.
2. Preserve Free and dedicated TTS Windows environment variables. Configure the
   separate Paid variable through Windows, never print/paste its value. Status
   presence is not proof of project separation, valid credentials or paid balance.
3. A real Paid test needs EXPLICIT approval for request count, duration (where
   supported) and INR exposure before enabling it. None has been granted here.
   Do not copy an ON command into a normal live launch before that approval.
4. For an approved structured-inference test, use a reviewed model-specific
   price/FX catalog and the fixed35000paise identity. Relevant process settings:
   `JARVIS_GEMINI_PAID_FALLBACK_ENABLED`, `JARVIS_GEMINI_PAID_PRICING_FILE`,
   `JARVIS_GEMINI_PAID_CEILING_INR_MINOR`, `JARVIS_GEMINI_PAID_BUDGET_ID`.
   Persisted machine settings take precedence unless explicitly using the existing
   `JARVIS_RUNTIME_ENV_OVERRIDES=true` diagnostic mechanism. Preserve the existing
   machine/audio/model profile; do not replace it with a blank one. No setting was
   edited during implementation. Prices must cover each actual selected model.
5. To test the existing personal assistant without enabling Paid fallback, after
   owner elects to launch the normal app:

```powershell
$env:JARVIS_RUNTIME_ENV_OVERRIDES = 'true'
$env:JARVIS_GEMINI_PAID_FALLBACK_ENABLED = 'false'
.\.venv\Scripts\jarvis-voice.exe --personal-learning apply
```

   These are process-only overrides. They can use normal Free API quota. Exit the
   shell to discard them. Existing Hello/private-session boundaries still apply.
   Use fictional Hindi/Hinglish/English: "Mere paas ek City hai", later "Meri car
   ke baare mein kya yaad hai?", correction, forget, and fresh process recall.
   Verify context/currentness rather than treating every spoken confirmation as
   proof of durable storage. This is not Paid fallback acceptance.
6. Future approved Paid acceptance must use a local TEST-ONLY failure-injection
   harness, not real quota exhaustion, for quota/recovery/402/auth transitions;
   record target IDs, same canonical session/Work ID, one action maximum, and
   known/reserved/unknown cost. Offline harness is the fallback pytest suite.
   A whole-app Paid Live failure-injection launcher and actual no-extra-wake
   voice acceptance remain pending the supported Live adapter; do not claim the
   offline harness or an isolated microphone test substitutes for that goal.
7. Whole-app Paid voice cannot currently be accepted: its factory is blocked.
   No Paid activation or microphone-only test should be requested as if it could
   validate an implemented production voice feature.

### Pricing example: synthetic, deliberately unusable for production

The exact schema is shown below. The model ID does not match production and times
are historical/expired. Replace ALL identities/rates/intervals with reviewed
sources, never use these synthetic values as real costs. Unknown rates must not
be entered as zero. Catalog entries may independently cover different models.

```json
{"schema_version":1,"prices":[{"schema_version":1,"profile":{"profile_id":"synthetic-do-not-use","version":1,"effective_from_epoch":0,"effective_to_epoch":1000,"input_usd_per_million_tokens":200,"output_usd_per_million_tokens":200,"usage_rates_usd_per_million":[]},"model_id":"example-not-a-production-model","service_key":"structured","source":"synthetic:test-only","inr_per_usd":"100","fx_source":"synthetic:test-only","fx_version":"example-v1","fx_effective_from_epoch":0,"fx_effective_to_epoch":1000,"margin_bps":0}]}
```

### Disable and rollback

Set the opt-in flag OFF through the original profile/diagnostic mechanism and
restart after stopping current work normally. Legacy construction remains lazy;
this stops new Paid admission and restores original routing for new work. Do not
delete budget/attempt/history stores, change budget identity to evade a hold, or
reset personal memory. Existing accepted/uncertain durable v2 Work retains its
saved provenance; an already-dispatched result is not undone by a flag change.
No API purchases, billing-account changes, pricing approval, default activation,
paid acceptance or merge are implied by this record.

## Native rulings and tradeoffs (exhaustive, chronological)

- Task3: RED20price/budget/concurrency cases observed before product implementation. Ruling: freeze the ceiling per explicit budget identity and reject mismatched config — prevents concurrent old/new processes silently resetting/raising shared allowance — cost if wrong: owner must explicitly version the budget identity to change its allowance.

- Task5: Ruling: stable scoped inference identity is dispatched once and repeated/unknown outcomes fail closed without storing private result text — prevents concurrent/crash re-dispatch and avoids a new personal payload cache — cost if wrong: callers need a genuinely new eligible source/request for another inference; automatic scoped-result resume is unavailable, while Work retains its own durable continuation.

- Task6: Ruling: reviewed pricing file supports a keyed multi-model/service catalog while retaining the singular snapshot format — Work/Hands/memory/Live require independent model/modality prices under the one shared ceiling — cost if wrong: an invalid/ambiguous catalog blocks Paid admission until corrected, never silently uses another model price.

- Task6: Ruling: v2 Work adds codec-protected accepted inference results and one-shot attempt claims inside the existing routing SQLite store — durable resume must not pay or reason twice after an accepted result, while WorkStep/Authority still owns actions — cost if wrong: uncertain in-flight reasoning blocks for reconciliation instead of automatic redispatch; extra encrypted inference result storage is retained with Work lineage. v1 behavior stays unchanged.

- Task8: Ruling: replace plan's Agent.update_options realtime swap with supported AgentSession.update_agent plus readiness hook and public RealtimeModel/RealtimeSession transport adapters — pinned installed1.8.3 AgentActivity._update_models explicitly rejects swaps to/from RealtimeModel; no SDK internal mutation is permitted — cost if wrong: transfer fails closed after bounded readiness timeout, drops unaccepted transition audio, and may require a repeated utterance; canonical conversation, grants and tool instances are never recreated or renewed. SDK evidence: livekit/agents/voice/agent.py:update_options, voice/agent_activity.py:_update_models, voice/agent_session.py:update_agent.

- Task8: Ruling: restore completed tools as bounded inert invocation receipts, without raw result payloads that have no canonical owner revalidation hook — a local SDK completion proves invocation returned, not current truth or remote effect success; preserving tools/Authority and prohibiting automatic replay prevents duplicate effects — cost if wrong: detailed prior tool output must be freshly obtained from its canonical owner after handoff; no mutating operation is automatically retried.

- Task8: Ruling: an untagged AgentSession CloseEvent remains a logical close — SDK close events expose no originating transport identity, so suppressing one could resurrect a genuinely stopped/expired session; old provider errors/streams are instead fenced at the public RealtimeSession boundary — cost if wrong: an SDK race may end the conversation and require a new wake, rather than preserving unsafe private history.

- Task9: Ruling: take the approved unsupported-SDK fail-closed branch for actual Paid Live, not a synthetic interval cap — real pinned SDK transport test proves GoAway creates a second physical connection even with max_retry=0; no public pre-connect hook exists and output cap is per turn, not total server-driven turns. No private SDK patch, invented token-rate hard bound, or zero-cost missing usage. The real factory denies Paid before key/client creation even when given an arbitrary budget object. Structured Work/Hands/memory remain implemented; paid voice activation/stream accounting requires a reviewed supported transport extension. Cost if wrong: automatic Paid voice fallback is unavailable in this candidate; owner must choose a separately reviewed adapter change or accept Free voice availability. Safe recovery behavior remains independently verified using fake transport, not claimed as real Paid Live acceptance.

- Task11: Ruling: represent disconnected ChatGPT-plan session as an unavailable runtime target-health fact — credential-free targets intentionally bypass API-key presence, so a False connectivity callback alone was ignored; existing health policy handles it without registry/policy digest changes — cost if wrong: plan is excluded while disconnected; owner must reconnect it, and durable decisions retain their original provenance. Observed fresh-request connectivity drift RED before this fix.

- Final: Ruling: retain unconditional Paid Live denial under approved Task9 unsupported-SDK branch — safe public transport accounting is not implemented; fake handoff cannot certify funded voice — cost if wrong: requested automatic Paid voice remains unavailable and full feature cannot be claimed complete.

- Final: Ruling: account/project separation, funding, keys, actual price/FX and spoken/invoice acceptance remain unverified — user has not authorized Paid calls or account changes — cost if wrong: owner acceptance may reveal credential, funding or production pricing problems; default OFF retained.

- Final: Ruling: controlled-transport amendment is at review time a separate unapproved design proposal outside reviewed implementation — do not implement new transport under an accounting exception — cost if wrong: full Paid Live delivery waits for a supported reviewed transport decision.

- Final: Ruling: in-flight Free recovery owns a durable process PID plus creation-time fence beyond provisional lease expiry — a live pending call cannot be stolen on clock advance; dead owner becomes eligible after TTL, old version/health facts remain fenced — cost if wrong: an inaccessible or hung process keeps Free recovery occupied until cancellation/exit; other eligible demand can use bounded Paid. No extra API probes.

- Final: Ruling: unresolved v2 inference claims and unfinalized Paid exposure block new dispatch for the whole WorkItem across scheduler bookkeeping — a new blocker step is not a new authorized operation — cost if wrong: ambiguous Work stalls for reconciliation rather than paying or reasoning twice; legacy decision digests remain unchanged.

## Deferred minors

None. The independent reviewer reported no Minor findings.

## Changed files in this dependent candidate

Generated from the actual dependency diff plus this candidate's new files.
Includes source, tests and documentation; no billing/account/machine changes.

- `README.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `docs/CURRENT_PLAN.md`
- `docs/PERSONAL_INTELLIGENCE_ENABLEMENT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/research/GEMINI_FREE_PAID_FALLBACK_IMPLEMENTATION_2026-10-22.md`
- `docs/research/GEMINI_FREE_PAID_FALLBACK_REVIEW_2026-10-23.md`
- `docs/superpowers/plans/2026-10-22-gemini-free-paid-fallback.md`
- `docs/superpowers/specs/2026-10-22-gemini-free-paid-fallback-design.md`
- `docs/superpowers/specs/2026-10-23-gemini-paid-live-controlled-transport-design.md`
- `pyproject.toml`
- `src/jarvis/ai_provider.py`
- `src/jarvis/capabilities/runtime.py`
- `src/jarvis/config.py`
- `src/jarvis/hands/planner.py`
- `src/jarvis/hands/provider_adapters.py`
- `src/jarvis/memory/extractors.py`
- `src/jarvis/memory/learning_extractors.py`
- `src/jarvis/memory/learning_runtime.py`
- `src/jarvis/memory/provider_verified_query.py`
- `src/jarvis/memory/query_coordinator.py`
- `src/jarvis/memory/query_interpreters.py`
- `src/jarvis/memory/release_guard.py`
- `src/jarvis/model_routing/budget.py`
- `src/jarvis/model_routing/cost.py`
- `src/jarvis/model_routing/eligibility.py`
- `src/jarvis/model_routing/gemini.py`
- `src/jarvis/model_routing/health.py`
- `src/jarvis/model_routing/invoker.py`
- `src/jarvis/model_routing/models.py`
- `src/jarvis/model_routing/pricing.py`
- `src/jarvis/model_routing/registry.py`
- `src/jarvis/model_routing/router.py`
- `src/jarvis/model_routing/runtime.py`
- `src/jarvis/model_routing/status.py`
- `src/jarvis/model_routing/store.py`
- `src/jarvis/model_routing/strategy.py`
- `src/jarvis/preflight.py`
- `src/jarvis/provider_resilience.py`
- `src/jarvis/voice/audio.py`
- `src/jarvis/voice/canonical_active_speaker_runtime.py`
- `src/jarvis/voice/gemini_budget.py`
- `src/jarvis/voice/gemini_handoff.py`
- `src/jarvis/voice/gemini_transport.py`
- `src/jarvis/voice/livekit_session.py`
- `src/jarvis/voice/memory_tools.py`
- `src/jarvis/voice/personal_context.py`
- `src/jarvis/voice/production_runtime.py`
- `src/jarvis/voice/provider_resilience.py`
- `src/jarvis/voice/runtime.py`
- `src/jarvis/work/reasoner.py`
- `src/jarvis/work/runtime.py`
- `tests/gemini_fallback/__init__.py`
- `tests/gemini_fallback/conftest.py`
- `tests/gemini_fallback/helpers.py`
- `tests/gemini_fallback/live_helpers.py`
- `tests/gemini_fallback/test_budget_concurrency.py`
- `tests/gemini_fallback/test_crash_recovery.py`
- `tests/gemini_fallback/test_credentials.py`
- `tests/gemini_fallback/test_free_recovery.py`
- `tests/gemini_fallback/test_hands_memory.py`
- `tests/gemini_fallback/test_invocation.py`
- `tests/gemini_fallback/test_live_budget.py`
- `tests/gemini_fallback/test_live_context.py`
- `tests/gemini_fallback/test_live_handoff.py`
- `tests/gemini_fallback/test_live_recovery.py`
- `tests/gemini_fallback/test_live_tool_replay.py`
- `tests/gemini_fallback/test_memory_authority.py`
- `tests/gemini_fallback/test_paid_budget.py`
- `tests/gemini_fallback/test_pressure_policy.py`
- `tests/gemini_fallback/test_pricing.py`
- `tests/gemini_fallback/test_production_composition.py`
- `tests/gemini_fallback/test_replay_compatibility.py`
- `tests/gemini_fallback/test_retry_boundaries.py`
- `tests/gemini_fallback/test_review_repairs.py`
- `tests/gemini_fallback/test_scoped_routing.py`
- `tests/gemini_fallback/test_status.py`
- `tests/gemini_fallback/test_system_boundaries.py`
- `tests/gemini_fallback/test_targets.py`
- `tests/gemini_fallback/test_work_priority.py`
- `tests/gemini_fallback/test_work_resume.py`
- `tests/test_model_routing_provider_retry_boundary.py`
