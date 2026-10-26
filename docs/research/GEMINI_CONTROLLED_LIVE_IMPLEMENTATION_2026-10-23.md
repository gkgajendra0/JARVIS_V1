# Controlled Gemini Paid Live — implementation, remaining work and acceptance report

23 October 2026. SOFTWARE-VERIFIED / PRODUCTION GOAL PARTIAL. No real Paid API calls, saved activation, account/billing changes, purchase or merge.

## What is complete and what remains

| Work | Status |
| --- | --- |
| Exact public contract and explicit auxiliary billing proof interface | Software complete; actual production auxiliary proof remains unqualified |
| One existing durable shared 35,000 paise governor, modality pricing and stable trigger admission | Complete offline |
| Public Google Live/LiveKit adapter, bounded client activity, tools/events/context | Complete offline; real speech/latency/accounting unqualified |
| Normal production factory/handoff and safe actual-demand Free recovery | Wired and tested offline; real Paid admission intentionally denied without qualification |
| Adversarial acceptance, independent review and full-repository regression gate | Complete offline: 3,177 passed / 8 platform skips |
| Report and supported owner steps | Delivered; final revision hosted receipt is recorded in draft PR #298 |

At the report commit, five of six software tasks have completion receipts; Task 6 is publishing this report and collecting hosted checks. The final Task 6 receipt and exact docs-inclusive revision checks are recorded in [draft PR #298](https://github.com/gkgajendra0/JARVIS_V1/pull/298). This count is not a percentage of real Paid voice readiness.

**Remaining to deliver the requested normal-app Paid voice behavior:** qualify real auxiliary billing and complete usage semantics (or obtain approval for a changed spending policy); qualify actual model/service prices and FX; then separately authorize and perform bounded whole-app Paid/multilingual acceptance, including a whole-app failure-injection launcher. That launcher and actual acceptance are not delivered by the synthetic tests. A funded key alone cannot remove the contract denial.

The earlier structured Work/Hands/memory Free/Paid candidate is retained. Its verified immutable checkpoint was bbaa99d45a86d4cea88b79f1f99781fe7193b25c: local 3,071 pass / 8 skip and all seven hosted jobs passed, including Linux/Windows full suites, Hello/DPAPI and SQLCipher. Those checks DO NOT certify the newer Live amendment. Draft dependent PR #298 remains based on feat/pi3-question-context-20261022; no dependency/main merge.

## Source, architecture and billing boundaries

Actual checkout: C:/Users/gkgaj/Desktop/jarvis_v1, branch feat/gemini-free-paid-fallback-20261022. Amendment base is bbaa99d4; independent reviewer candidate is 2a1a993653e10098eb5da942462458a7e686b110. Review repairs were committed as ff7ae4257f735c1c84185172ec456a085d1bbfa1; the final verified source checkpoint is b663dbbefd31724fa372ffbd0b08deb5b7bad759. This report/entrypoint commit follows without product-code changes.

Pinned dependencies remain google-genai 2.22.0 and LiveKit agents 1.8.3. Reuse the existing Global Brain/Phase4 ModelRouter, RoutingRuntime, target health, cost store, PaidBudgetGovernor, canonical conversation, personal context and Authority owners. Optional PaidExposure.contract_ref binds reviewed Live envelope provenance while leaving legacy payloads unchanged. No competing router, memory authority or budget ledger.

GOOGLE_API_KEY remains Free; JARVIS_GEMINI_PAID_API_KEY is resolved lazily through the existing allowlisted target resolver. Dedicated TTS credentials and ChatGPT-plan routing remain their existing owners. Keys/provider payloads are not stored in the Live policy records; raw Live errors are reduced to normalized policy facts before SDK emission.

Each physical Paid connection has one prior durable admission, no SDK auto-reconnect/resumption/compression, client-owned activity and explicitly blocking tools. Same logical conversation/tools survive physical socket close. Another actual user turn or tool continuation needs a new admission. Physical lifetime 60 seconds (watchdog starts before admission/setup; normally 57 seconds active and three bounded cleanup slots), user input 30 seconds, bounded 160 ms PCM/preroll, owner 48 kHz mono resampled to 16 kHz; output 24 kHz. Disk reserve/settle stay off the synchronous input-frame path. Default Free/native server-turn behavior stays unchanged.

The cumulative internal ceiling is 35,000 paise across Live/Work/Hands/memory and survives restart. Changing budget identity must not be used to reset spend. Unknown/inconsistent usage retains exposure and blocks new Paid admission; an observed overrun is recorded, not clipped. No automatic credit purchase. Model-specific versioned price/FX and all modality rates are required; unknown values are not zero. This internal admission ceiling is not a claimed provider invoice guarantee.

## Real production qualification is still missing

Google documents extra transcription and proactive listening charges and re-billed context. The model token capacities and an approximate audio rate do not independently establish the missing auxiliary maxima/accounting interpretation. [Official billing guidance](https://ai.google.dev/gemini-api/docs/live-api/best-practices).

Therefore reviewed_live_contract(model) without explicit qualified auxiliary bounds rejects before client construction. Production has no fabricated auxiliary envelope or arbitrary test override; normal handoff wiring records paid_live_billing_contract_unqualified. Test-supplied synthetic bounds prove software mechanics only. A price file or funded key alone does not enable actual Paid Live. A sourced production contract/accounting qualification, or a separately approved design change, remains necessary; bounded real Paid experiments also require explicit approval.

## Evidence available so far

- Task 2: 89 passed in 16.62s; health/credential drift, cancellation, expiry, stable replay and shared ceiling.
- Task 3 public/context integration: 69 passed in 12.10s; actual public AgentSession synthetic Hindi/Hinglish/English streams, one fictional tool, no hidden reconnect, raw usage and duplicate events.
- Task 4: 554 passed in 60.85s; actual production factory/observer, same canonical session and unanswered request,401/402/503 policy, local microphone/VAD/end-point pipeline, Free recovery at actual idle demand.
- Task 5: 521 passed in 67.35s before expanded private cases; expanded private boundary13pass7.14s and crash/classification12pass13.18s. Actual temporary canonical memory/Authority, lock/forget/expiry during reserve/setup/tool and queued release; Hello count remains 1. Real process death and independent Live contenders with a durable Work 20,000 paise hold admit exactly three additional 3,993 paise holds, deny two, total 31,979 paise.
- One synthetic1000-frame measurement:48k->16k median0.0402ms, p990.0614ms, event-loop yield max0.0995ms, zero provider clients; reserve/settle replaced by failing guards. This is local idle-frame overhead, not real microphone/provider/ASR latency.
- Independent reviewer: five Important findings, zero Critical, zero Minor; all five reproduced RED and repaired in one pass. Controlled Live final suite: 106 passed in 39.88s. Actual public AgentSession cancellation/uncertain-send counters prove zero canceled actions and one uncertain action, respectively.
- First full-repository gate: 3,176 passed, eight skipped, one SDK-import allowlist failure in 300.59s; the exact approved public adapter was then registered in the existing architecture guard. This failed run is retained, not counted as success. Final full-suite and exact-head hosted results follow below.

## Final verification

Source b663dbbefd31724fa372ffbd0b08deb5b7bad759: `python -u -X utf8 -m pytest -o addopts= -o faulthandler_timeout=60 -q -ra` → **3,177 passed, 8 skipped in 278.01s**. Ruff check passed; Ruff format check: 1,068 files already formatted; git diff --check passed. The final adapter-policy/Live affected run: **123 passed in 42.96s**.

Skipped nodes (host platform/privilege conditions, not provider skips):

- `tests/test_capability_runtime.py::test_approved_root_blocks_parent_and_symlink_escape`
- `tests/test_engineering_substrate_artifacts.py::test_artifact_source_and_root_symlinks_are_rejected`
- `tests/test_engineering_substrate_sandbox.py::test_sandbox_rejects_symlink_and_docker_socket_mounts`
- `tests/test_incident_repair_workspace.py::test_diagnostic_workspace_blocks_sensitive_paths_traversal_and_symlinks`
- `tests/test_phase10_acceptance.py::test_phase10_owner_machine_acceptance_requires_windows`
- `tests/test_phase10a_acceptance.py::test_phase10a_owner_machine_acceptance_requires_windows`
- `tests/test_phase6_acceptance.py::test_owner_machine_acceptance_cannot_pass_on_non_windows`
- `tests/test_phase9_promotion_setup.py::test_promotion_setup_rejects_non_windows`

The docs-inclusive final-head hosted ledger lives in the **Exact revision verification** section of [draft PR #298](https://github.com/gkgajendra0/JARVIS_V1/pull/298): six Code Quality jobs plus manually dispatched SQLCipher 4.17 Windows. Verify its recorded head equals the PR head and each job actually completed successfully. This report does not pre-claim a future result or reuse bbaa99d4 checks as proof of new code. The PR body can record its own final revision without another Git commit that changes that revision.

## Known practical limits

Real provider pause handling, Hindi/Hinglish ASR/intent, paid invoice accounting, account separation/funding and key validity remain untested. Synthetic transcripts are supplied answers, not evidence Gemini understood live speech. Input waiting beyond 160 ms during a slow connection can overflow and fail closed; the per-turn handshake can require repeating an utterance. Incomplete-usage interruption/GoAway/close holds exposure and can stop Paid until reconciliation; it is not advertised as seamless barge-in. Standard exact `gemini-3.8-live` only; aliases/extended-thinking/video/unpriced auxiliary dimensions remain unsupported. Real provider and owner acceptance remain unqualified after the single review and repair pass.

## Exact owner-machine acceptance steps

Keep the whole normal app as the acceptance surface. No isolated microphone test substitutes for it. Before copying launch commands, inspect the final PR revision/checks and preserve local changes. In a clean checkout:

```powershell
Set-Location C:\Users\gkgaj\Desktop\jarvis_v1
git fetch origin
git switch feat/gemini-free-paid-fallback-20261022
git pull --ff-only origin feat/gemini-free-paid-fallback-20261022
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

For normal personal-assistant Free-only acceptance, only when the owner elects to launch (uses ordinary Free API quota; preserve dedicated TTS configuration):

```powershell
$env:JARVIS_RUNTIME_ENV_OVERRIDES = 'true'
$env:JARVIS_GEMINI_PAID_FALLBACK_ENABLED = 'false'
.\.venv\Scripts\jarvis-voice.exe --personal-context apply --personal-learning apply
```

Use fictional vehicles/preferences in Hindi/Hinglish/English, later recall, correction, forget and fresh-process recall. Confirm the current canonical fact and personal-session boundaries, not merely a spoken acknowledgement. Keep existing machine/audio/model settings and Hello session limits. Exit the shell to drop process overrides. No saved settings were changed here.

Paid whole-app acceptance cannot yet be requested as a working feature: qualification still denies it. After qualification and separate exact request-count/duration/reviewed-INR approval, record deterministic quota/recovery/402/auth injection, same canonical session/Work identity, one side effect, known/reserved/unknown spend and no new wake for an accepted unanswered request. Do not burn actual Free quota to force failover. A whole-app failure-injection launcher/spoken qualification must still be delivered/verified; current provider-free tests are the deterministic software harness only. No ON command is authorized by this report.

Rollback: keep fallback false and the existing Free/TTS/model profile; do not reset the persisted budget or delete unknown holds. No merge/account/billing change is part of this handoff.

## Rulings in this amendment, chronological

- Ruling: owner approval explicitly included the next executable plan and Native offline implementation — proceed through routine plan tasks without asking for the same authorization again — cost if wrong: material new behavior outside the approved public adapter/budget/turn-control scope still requires a separate decision; Paid calls/activation/merge remain excluded.
- Ruling: close the Paid physical connection on completed user turns while retaining the logical session; blocking tool continuations reserve again on the same bounded physical connection — documented proactive listening can charge idle input, so no indefinitely paid idle socket or approximate token/second hard bound — cost if wrong: an extra handshake/context replay per user turn adds latency and input cost; both are admitted before send and require whole-app qualification.
- Task1: Ruling: add explicit LiveAuxiliaryBounds to the model contract instead of inventing listening/ASR maxima from the model card — billing guide has extra charges and approximate audio token rate is not a hard bound; reviewed_live_contract accepts an optional explicit auxiliary envelope and otherwise rejects before clients — cost if wrong: actual Paid Live stays unavailable until a sourced production envelope/accounting interpretation is qualified; synthetic values cannot certify it. Generic offline admission/protocol work can still progress on the explicit contract.
- Task2: Ruling: bind optional Live contract_ref SHA256 into the existing PaidExposure payload, omitting it for legacy callers — equal counts with different auxiliary provenance must not replay under one trigger; original payload/digest stays compatible — cost if wrong: changed Live proof requires a new eligible operation; it cannot buy a retry of an ambiguous old dispatch.
- Task3: Ruling: treat public interrupt as a no-op only for an already completed blocking-tool generation — pinned AgentSession explicitly interrupts that completed generation before requesting its tool-result reply — cost if wrong: the socket can remain waiting for the tool until its60-second physical deadline; active-output interruption still closes and retains unknown cost, so genuine interruption may require Free/reconciliation.
- Task3: Ruling: wait at most5seconds for final generation usage before sending a fast tool result, preserving the serialized sender and concurrent receiver — actual public SDK can finish a local tool before the provider sends turnComplete — cost if wrong: delayed/missing usage fails closed and holds unknown instead of producing the tool reply; the action itself is not repeated.
- Task4: Ruling: normal production wiring retains unqualified-Paid denial, rather than injecting synthetic auxiliary proof or adding an arbitrary configuration override — official research still does not qualify listening/ASR maximum or complete accounting — cost if wrong: real Paid Live remains unavailable even though the controlled software adapter works with explicit synthetic contracts; further billing-contract qualification or an owner-approved design change is required before claiming the goal complete.
- Final scope: Ruling: retain the previous structured candidate review as immutable prior evidence, rather than re-review its pre-BASE range — the new review covers the amendment and the fresh full suite covers integrated regressions — cost if wrong: an old untested interaction could remain; no old CI is represented as new proof.
- Final scope: Ruling: accept the reviewer's exclusion of provider billing/price/FX investigation, while retaining the root's official-source research and production denial — synthetic usage cannot qualify real accounting — cost if wrong: funded Paid Live remains unavailable and actual price/account qualification is still required.
- Final scope: Ruling: treat synthetic multilingual transcripts/VAD as protocol evidence only — the reviewer had no real model/devices and cannot certify recognition or pauses — cost if wrong: spoken latency, interruptions or recognition may need changes during later whole-app acceptance.
- Final scope: Ruling: do not substitute temporary Authority tests or hosted Hello/DPAPI checks for the real owner's machine/session acceptance — reviewer access excluded owner security devices/profile — cost if wrong: machine-specific behavior remains to be verified by the owner after separate activation.
- Final scope: Ruling: finish fresh full-repository and exact-head hosted gates as the root's responsibility — reviewer did not run them and previous checkpoint results are insufficient — cost if wrong: the candidate cannot be marked software-verified until those gates pass.
- Final scope: Ruling: finish Task6 report and supported owner steps, but retain actual Paid/model/spoken acceptance as pending — an unfinished future deliverable at review HEAD is not acceptance evidence — cost if wrong: the requested end-to-end Paid voice goal remains partial even after offline tasks finish.
- Final: Ruling: start the absolute watchdog before admission/setup and reserve three bounded cleanup slots within the physical envelope (normally57seconds active plus3seconds teardown) — a queue-only abort cannot stop blocked public I/O — cost if wrong: earlier truncation and retained unknown exposure; local teardown timing does not certify backend invoice bounds.
- Final: Ruling: require usage on the actual turnComplete event for that lease, never a prior fully-shaped snapshot — later output makes an earlier snapshot insufficient final evidence — cost if wrong: providers emitting only separate/late final metadata stay unknown and block further Paid admission until qualified.
- Final: Ruling: refresh accepted canonical context on every physical open and retain inert tool receipts without replaying native actions — logical conversation must survive socket replacement under the original authority — cost if wrong: provisional/unaccepted speech is excluded and may need repetition; no new session grant is created.
- Final: Ruling: attempt eligible Free recovery before new Paid admission, shield the existing handoff owner and transfer only bounded160ms current PCM before enabling input — avoid buying another Paid turn after cooldown while preserving the original demand — cost if wrong: audio beyond the bounded buffer may still require repetition; real whole-app continuity needs owner qualification.
- Ruling: register only voice/gemini_live_session.py in the existing explicit provider-adapter import allowlist — the approved controlled transport needs public GenAI types, while key construction remains in the original livekit_session factory — cost if wrong: one additional exact module can import provider SDK types; no wildcard or policy bypass is permitted.

## Single independent review and deferred minors


Reviewer: review_controlled_live_amendment. Exact range bbaa99d45a86d4cea88b79f1f99781fe7193b25c..2a1a993653e10098eb5da942462458a7e686b110. Read-only, no source/index/HEAD changes, no network/inference/owner devices. Verdict NOT READY TO MERGE. Critical none; Important5; Minor none.

1. Physical deadline cannot stop blocked setup/send: timer starts after setup/history and abort queues behind blocked sender. Reproduced legal1s contract with setup pending past1.15s and blocked send still open after expiry. Includes teardown obligation.
2. Earlier fully-shaped usage snapshot treated as final: standalone raw_usage followed by more output and turnComplete without usage settles1paise/releases3993/unknown0. Finality must be associated with actual completed generation.
3. Spoken history omitted next physical connection: real AgentSession accepted spoken user/assistant turns, but replay _ctx only held typed inputs. Refresh original accepted canonical projection; preserve currentness, tools and receipts.
4. Receiver cancellation records _cancelled_tools/_failure, but source-release checks ignore both until sender processes abort. With sender blocked, cancelled cancel-me still delivered. Immediately invalidate release; add actual action-counter regression.
5. Expired Free cooldown still buys next Paid turn: speaking marks demand but inhibits recovery, while Paid start_user_activity opens client2/3993hold; only returns Free after second Paid turn. Need pre-dispatch demand boundary preserving authority/pending input.

Declined to judge, exhaustive:
- Original pre-BASE structured candidate: excluded scope, prior evidence consumed.
- Actual provider billing bounds/final usage guarantees/current external docs/priceFX: no network/provider investigation authorized to reviewer; explicit remaining gap.
- Real spoken multilingual recognition/pauses/barge-in/devices/end-to-end latency: synthetic protocol/VAD cannot establish it; excluded devices/inference.
- Actual Hello/DPAPI/owner-profile retention/saved machine: excluded owner/security-device access; temporary tests supporting only.
- Full repository/exact-head hosted success: pending root gates, not independently run.
- Future Task6 report/hosted/owner acceptance: unfinished at reviewed HEAD.

Root disposition before repairs: all5 Important accepted; no demonstrated Authority bypass warrants Critical grading, but canceled action release is materially unsafe and must be fixed. One RED-to-GREEN repair pass; no re-review. All declined judgments accepted as scope/evidence boundaries; original base remains prior verified, external documentation already researched by root but real billing/priceFX remains unqualified, real spoken/owner acceptance remains separate, root must still finish full suite/hosted/report and must not claim deferred acceptance passed.

Repair disposition: all five Important findings reproduced RED and repaired in one pass. Additional receiver-close and swallowed-cancellation races reproduced RED before repair. Full controlled Live suite106passed39.88s. Whole repository gate follows in Task5 completion receipt. No second review; no deferred minors.

## Deferred minors

None. The reviewer raised five Important findings, all accepted and reproduced before repair. No second review was run.

## Changed files in the amendment (relative to bbaa99d4)

- `README.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `docs/CURRENT_PLAN.md`
- `docs/PERSONAL_INTELLIGENCE_ENABLEMENT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/research/GEMINI_CONTROLLED_LIVE_CONTRACT_2026-10-23.md`
- `docs/research/GEMINI_CONTROLLED_LIVE_IMPLEMENTATION_2026-10-23.md`
- `docs/research/GEMINI_FREE_PAID_FALLBACK_IMPLEMENTATION_2026-10-22.md`
- `docs/research/GEMINI_FREE_PAID_FALLBACK_REVIEW_2026-10-23.md`
- `docs/superpowers/plans/2026-10-22-gemini-free-paid-fallback.md`
- `docs/superpowers/plans/2026-10-23-gemini-paid-live-controlled-transport.md`
- `docs/superpowers/specs/2026-10-23-gemini-paid-live-controlled-transport-design.md`
- `src/jarvis/model_routing/pricing.py`
- `src/jarvis/voice/gemini_handoff.py`
- `src/jarvis/voice/gemini_live_budget.py`
- `src/jarvis/voice/gemini_live_contract.py`
- `src/jarvis/voice/gemini_live_events.py`
- `src/jarvis/voice/gemini_live_model.py`
- `src/jarvis/voice/gemini_live_session.py`
- `src/jarvis/voice/gemini_transport.py`
- `src/jarvis/voice/livekit_session.py`
- `src/jarvis/voice/production_runtime.py`
- `tests/gemini_live/__init__.py`
- `tests/gemini_live/conftest.py`
- `tests/gemini_live/helpers.py`
- `tests/gemini_live/test_activity.py`
- `tests/gemini_live/test_agent_session.py`
- `tests/gemini_live/test_boundaries.py`
- `tests/gemini_live/test_budget.py`
- `tests/gemini_live/test_contract.py`
- `tests/gemini_live/test_crash.py`
- `tests/gemini_live/test_events.py`
- `tests/gemini_live/test_handoff.py`
- `tests/gemini_live/test_production.py`
- `tests/gemini_live/test_public_transport.py`
- `tests/gemini_live/test_recovery.py`
- `tests/gemini_live/test_review_repairs.py`
- `tests/gemini_live/test_tools.py`
- `tests/gemini_live/vad_helpers.py`
- `tests/test_ai_provider_policy.py`

## Complete dependent PR file manifest (relative to 211c3ade)

- `README.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `docs/CURRENT_PLAN.md`
- `docs/PERSONAL_INTELLIGENCE_ENABLEMENT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/research/GEMINI_CONTROLLED_LIVE_CONTRACT_2026-10-23.md`
- `docs/research/GEMINI_CONTROLLED_LIVE_IMPLEMENTATION_2026-10-23.md`
- `docs/research/GEMINI_FREE_PAID_FALLBACK_IMPLEMENTATION_2026-10-22.md`
- `docs/research/GEMINI_FREE_PAID_FALLBACK_REVIEW_2026-10-23.md`
- `docs/superpowers/plans/2026-10-22-gemini-free-paid-fallback.md`
- `docs/superpowers/plans/2026-10-23-gemini-paid-live-controlled-transport.md`
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
- `src/jarvis/voice/gemini_live_budget.py`
- `src/jarvis/voice/gemini_live_contract.py`
- `src/jarvis/voice/gemini_live_events.py`
- `src/jarvis/voice/gemini_live_model.py`
- `src/jarvis/voice/gemini_live_session.py`
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
- `tests/gemini_live/__init__.py`
- `tests/gemini_live/conftest.py`
- `tests/gemini_live/helpers.py`
- `tests/gemini_live/test_activity.py`
- `tests/gemini_live/test_agent_session.py`
- `tests/gemini_live/test_boundaries.py`
- `tests/gemini_live/test_budget.py`
- `tests/gemini_live/test_contract.py`
- `tests/gemini_live/test_crash.py`
- `tests/gemini_live/test_events.py`
- `tests/gemini_live/test_handoff.py`
- `tests/gemini_live/test_production.py`
- `tests/gemini_live/test_public_transport.py`
- `tests/gemini_live/test_recovery.py`
- `tests/gemini_live/test_review_repairs.py`
- `tests/gemini_live/test_tools.py`
- `tests/gemini_live/vad_helpers.py`
- `tests/test_ai_provider_policy.py`
- `tests/test_model_routing_provider_retry_boundary.py`
