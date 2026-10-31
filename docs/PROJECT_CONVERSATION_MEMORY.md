# Project conversations and personal memory — implementation contract

**Decision date:** 31 October 2026, Asia/Kolkata.
**Status:** implementation authorized and started; controlled text capture/routing/retrieval/context/controls are implemented and under software verification. Actual model/Windows/native acceptance remain open. See [Current Plan](CURRENT_PLAN.md).
**Priority:** complete reliable conversation continuity before adding another memory framework or local model.
**Execution:** [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md).
**Authority:** scoped feature design subordinate to [Product](PRODUCT.md), [North Star](AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md), [Quality Gates](QUALITY_GATES.md) and [Current Plan](CURRENT_PLAN.md). This is not another master plan or a statement of accepted production behavior.

## 1. What we are building and why

Jarvis must preserve an ongoing discussion, keep unrelated projects separate, and use relevant established personal facts when answering. The owner should be able to discuss a Nepal trip, use Jarvis for interviews, let it sleep or restart, then ask for Nepal's status without explaining the trip again. The owner must also be able to see what was saved and where it belongs.

The observed candidate restored a topic called Nepal trip with empty details. It saved selected model-proposed fields, not the discussion. Successful storage/retrieval component tests did not establish natural live capture and answering. The source discussion must survive even when a model omits a structured update.

**Chosen design:** Gemini supplies language understanding, memory-update proposals, search requests and answers. Jarvis automatically records accepted eligible turns, owns project/thread identity, searches local evidence, validates proposals and supplies context before substantive answers. Existing SQLCipher storage, personal-memory lifecycle, retrieval and voice protection are reused.

**First delivery:** a complete isolated Nepal -> other project -> sleep/restart -> Nepal recall -> correction -> recall flow. No hosted-agent migration, new memory vendor, model training, local LLM, knowledge-graph service, custom general agent framework, or dashboard rebuild is required for this delivery.

## 2. Permanent goals and evidence

| ID | Required outcome | How we establish it |
|---|---|---|
| G1 Capture | Original accepted eligible turns survive without a model-selected save call | Disable update proposals, record turns, reopen database and reconcile durable receipts |
| G2 Continuity | A project survives transport retirement, actual sleep and process restart | Stable project/thread IDs and connected answers across all three boundaries |
| G3 Separation | Different projects retain separate histories | Interleave Nepal/interview fixtures; inspect selected sources and actual provider payload |
| G4 Personal context | Relevant current personal facts can inform multiple projects | Use a source-supported shared vehicle fixture without copying unrelated project conversations |
| G5 Correctness | Corrections supersede older facts; suggestions, decisions and completion remain distinct | Current/historical queries, negative/question cases, verified tool outcomes and owner-reported status |
| G6 Visibility/control | Owner can inspect active project, sources, recording coverage, corrections and forgetting | Authenticated local inspection plus voice controls and deletion/restart checks |
| G7 Cost | Persistence needs no model call and memory adds no standalone extraction request by default | Count request types, continuations and input/output tokens per scenario |
| G8 Traceability | Every failure can be located in capture, selection, retrieval, dispatch or answer use | Correlated IDs and stage status; inspect evidence without asking the owner to reconstruct speech |

Storage, permission and source-accounting guarantees are distinct from probabilistic language-model quality. “Works perfectly” means meeting the acceptance contract below, not a claim of flawless recall for every possible utterance.

## 3. Current reality and retained evidence

- Remote candidate baseline: PR [#303](https://github.com/gkgajendra0/JARVIS_V1/pull/303), `7800e984780b36ee18dd5e4be61a85b899bc7def`. Corresponding local product commit `dc636b6` has the identical tree `41d22094bdf48c1f214e0950d5096340a1deb2a7`.
- Candidate uses optional `prepare_conversation_topic` proposals and stores title, goal, constraints and steps. It is not a full project conversation archive.
- Historical focused verification: 624 tests passed; Ruff/format checks passed. Exact-head hosted Code Quality `41015521562` and SQLCipher Windows verification `41015521598` succeeded. These results do not accept the proposed replacement.
- Owner's 30 October native trace: a request for Nepal vehicle/permit status returned the topic with empty constraints, no goal and no steps; Jarvis answered that those details were not saved. End-to-end acceptance FAILED. This does not identify the exact historical write failure for every missing field.
- The earlier full local suite was stopped by automatic approval review for outbound Microsoft telemetry with an unknown payload; no workaround/retry is authorized by this document. The unrelated isolated process-recovery regression is also not claimed fixed.
- `E:\Jarvis\App` remains unchanged by this documentation work. The lab and candidate feature are not normal-app activation or main-branch acceptance.
- Existing Hindsight, LangMem, embeddings and reranker experiments remain evidence for their original scopes. Do not repeat that vendor comparison or treat it as proof of complete conversation behavior.

## 4. Responsibilities: who decides what

| Concern | Owner | Rule |
|---|---|---|
| Physical database/key location | Jarvis configuration/runtime | Existing canonical SQLCipher workers; Gemini never supplies an arbitrary file path or SQL |
| Original conversation recording | Application recorder | Automatic for accepted eligible events; independent of model proposals |
| Active project | Application router, informed by current request/Gemini proposal | Stable validated ID; no silent ambiguous switch |
| Semantic interpretation | Existing Gemini model | Propose decisions, facts, tasks, queries and clarification; do not grant itself permission |
| What becomes a personal fact | Canonical learning admission/lifecycle | Source-supported proposal, existing eligibility/authority; rental consideration is not ownership |
| What to search | Gemini tool request; bounded recent selected-project context supplied automatically | Search words express intent; application imposes allowed project/personal scope |
| How matches are found | Existing local retrieval plus an archive adapter | Metadata filtering first; keyword/semantic ranking where available |
| Durable writes and corrections | Canonical store/lifecycle | Exact source and expected revision; a model's statement that it saved something is not a receipt |
| Answer generation and speech | Gemini plus existing protected response controller | Evidence must reach the generation path; stale/revoked scope cannot continue speaking |

The initial delivery uses the current configured provider/model. Do not change accounts, keys, paid-fallback limits or model defaults as an implicit memory fix.

## 5. Owner experience and project boundaries

1. “Let's plan my Nepal trip.” Create/select that project and acknowledge selection. Do not require a special keyword in every later sentence.
2. “We will take the Jimny.” Automatically preserve the turn in the selected thread; Gemini may also propose a project decision supported by that exact source.
3. “The permits are sorted.” Preserve it under the same thread. Record it as an owner report, not independent legal/world verification.
4. Protected response/session retirement keeps the logical thread selected. Actual sleep closes a listening segment, not the project.
5. “Switch to interview preparation.” Commit a validated selection change. The switch command/acknowledgement belongs to the destination; previous project identity is routing metadata only. Later/queued messages remain bound to their original request.
6. “What is the status of my Nepal trip?” Select that project, load current project context and retrieve evidence before the answer. Do not confuse retrieval failure with “you never told me.”
7. Restart preserves last selected IDs locally, not authority. After current-owner authorization, an unnamed continuation announces the resumed project; a named request selects its named project. Ask once when duplicate names/versions cannot be distinguished.
8. “New conversation in Nepal trip” opens another thread inside the same project. Otherwise resume its latest open thread.
9. “What project are we discussing?”, “What did you save?” and “Where did that come from?” report actual IDs/names, committed source evidence and coverage. “Forget this project” uses the canonical explicit deletion boundary.

General discussion has a visible General workspace. Small talk/side questions do not silently create or switch projects. General history is not automatically injected into named projects. Ask a narrow clarification for a substantive ambiguous transition. Normalize exact names and explicit aliases; do not use fuzzy similarity as permission to select another project.

## 6. What is stored locally

Keep distinct logical scopes in the same encrypted database:

- **Personal memory:** existing canonical assertions, source/validity/currentness and lifecycle. Do not create a duplicate personal-fact store.
- **Project/thread history:** original accepted user and assistant messages, actual tool intent/results, source IDs, timestamps, role, interruption/delivery status and project/thread IDs.
- **Selection:** active project/thread and revision, with no serialized authentication handle.
- **Derived current state:** optional project decisions/tasks and compact context, linked to source event IDs and covered sequence. This is rebuildable; it never replaces the original history.

Initial schema addition is deliberately small: `conversation_workspace`, `conversation_thread`, `conversation_event`, `conversation_selection` in migration `0005_project_conversations.sql` (revalidate next version at implementation time). Thread rows can hold optional source-linked state/coverage fields. Use UUID identity, immutable source-event identity and per-thread order; titles are labels. Keep transport session ID separate from thread ID. Do not deduplicate original turns only by text: two identical sentences at different times are distinct events.

Capture is scoped to the owner's enabled conversation-retention permission and existing excluded-content rules. Existing plan-only learning consent must not be repurposed to archive arbitrary dialogue. Add a scoped history authority using the existing permit owner if needed; no new parallel security framework. Explicit omissions/pause/failed writes are visible coverage states. No raw ambient audio/video archive is part of this feature.

At the archive boundary, a final eligible accepted event and its revision are durably committed before the application claims it was saved or dispatches the dependent answer. Retry with the same event ID. A pending RAM event is not promised to survive a hard crash. If storage fails, report unsaved status and block unsupported continuity claims. Do not wait until sleep to save everything.

Interrupted assistant text remains partial, not fully delivered. A planned action is not successful execution. An owner report of completion is distinct from a verified tool result.

## 7. Save, search, read and answer flow

**Save:** accepted canonical turn -> immutable project/request binding -> authorized encrypted append -> durable receipt. Best-effort synchronous observers cannot provide this guarantee; add an awaited required recorder separately.

**Interpret:** the existing Gemini response/tool turn may propose a grounded project update or request a search. There is no second always-on extraction model. Invalid or omitted proposals cannot erase the source conversation.

**Retrieve:** supply bounded recent selected-project context automatically, preserving each source's original thread ID. New threads retain access to the same project's prior discussion. Gemini requests older detail through a typed local tool, conceptually:

```json
{"tool":"search_conversation_memory","project_id":"validated-local-id","query":"latest vehicle decision and permit status"}
```

The tool resolves server-owned scope, performs authorized project-filtered search and returns bounded excerpts with source IDs/dates. `read_conversation_sources` can read selected permitted results, not arbitrary IDs or paths. Personal context uses the existing scoped canonical read path. Query text is not authorization; a project tag does not grant access. Avoid a separate cloud query-planning call.

**Answer:** create a context receipt containing request/activity generation, selected project/thread revision, committed source sequence, retrieved IDs, personal-memory version and coverage. Deliver it to the actual provider before the context-dependent generation. Recheck before dispatch and protected audio. New speech, switch, correction, forget or revoke invalidates the old receipt. Model output must not turn stored data into instructions or execution authority.

Search errors, missing sources, incomplete coverage and true no-match are distinct statuses. If no evidence is found, say it was not found in the saved context; never claim historical nonexistence from a failed search.

## 8. Voice ordering is a required integration contract

The pinned LiveKit/Gemini adapter owns native turn timing today. Final transcripts may arrive after initial generation, and `context_sync.py` documents model-specific history-update limitations. A database callback, buffered uninformed audio, or ignored `update_chat_ctx` is not a solution.

First implementation gate: prove `accepted transcript -> archive commit -> selected context delivered -> dependent generation -> authorized speech` on the pinned adapter. Include a new transport session and a project switch. Preserve existing qualified wake, fallback and audio protections.

If the current transport cannot satisfy the contract, record the exact unsupported capability and use an application-controlled speech-to-text -> existing Gemini -> existing TTS route for the isolated feature. Qualify available credentials/adapters; do not silently add a paid provider, upgrade dependencies or run two independent answering models. This is the only predeclared transport fallback, not permission to restart architecture research.

## 9. Cost and context bounds

- Local append, exact project lookup and local search require no paid model inference.
- Zero standalone cloud extraction, query-planning, background summarization or memory-classifier requests by default. Gemini's ordinary response/tool cycle handles interpretation.
- Tool continuations can still consume billed tokens; “same model turn” is not a zero-cost guarantee. Record every actual provider request, retry, continuation and input/output/audio usage.
- Initial external-memory packet ceiling: 6,000 estimated text tokens, covering recent/uncovered turns, project state, relevant personal facts and original excerpts. Use the provider's supported estimator; do not describe an arbitrary character count as exact tokens. This ceiling is an implementation default for review, not a measured optimum.
- At most one initial archive search and one deeper source-read step per request by default; return explicit budget/coverage status instead of unlimited retries. Existing stricter provider/authority limits still apply.
- A compact-state failure leaves original events available; the uncovered tail is included. Do not require paid background summaries to make short conversations work.
- Use existing local embeddings only where compatible vectors are available; no new embedding API, model download or GPU dependency is a prerequisite.
- Measure comparable scenarios against current usage. No savings percentage, new paid test budget or expanded fallback authorization is implied by this documentation.

## 10. Correct, forget, inspect and fail safely

Corrections append source history and supersede relevant current state; historical queries may intentionally report older values with dates. Any cached/derived packet must be invalidated by correction. Forget removes the selected retained content and derived/index copies through one lifecycle, advances its generation, and prevents delayed work from recreating it. Preserve personal facts with independent surviving sources; remove or mark unsupported those derived solely from deleted content. Never infer that deleting one project deletes all independently sourced personal facts.

Authenticated local inspection is sufficient for the first delivery: active project, chronological sources, state coverage, last committed sequence and pending/error status. Voice controls can invoke the same inspector. Do not add owner transcripts to the existing UI's general snapshot/events feed; its loopback Host check is not private-history authentication. Full UI expansion is deferred.

Observability reports request/event IDs and stages `accepted`, `committed`, `selected`, `retrieved`, `dispatched`, `answered`, or a concrete failure stage. Do not log unredacted personal transcripts by default. Explicit diagnostics may show policy-cleared excerpts. Logical deletion is not represented as forensic erasure of all backup/free-page copies.

## 11. Reuse boundaries and deliberately deferred alternatives

Reuse `conversation.py` and `voice/livekit_session.py` as canonical turn sources; `memory/runtime.py`, workers/migrations as database owners; `memory/retrieval.py` and scoped personal context as evidence retrieval; `personal_context.py` and provider/audio guards as protected release; existing learning and lifecycle as personal-fact mutation authority.

Add only the missing archive adapter, persistent routing and source-aware context integration. Research implementations remain component references, not automatic dependencies. MCP Memory Service offers local retrieval but its inspected backend is standard SQLite and preserves exact-content deduplication; Memori's documented Gemini interception is for text generation and advanced augmentation uses another API. Neither is a proven encrypted LiveKit drop-in. Existing tests are retained.

Local memory models (`mem-agent`, Qwen, FunctionGemma), fine-tuning, hosted OpenAI Agents, alternate memory services, autonomous consolidation, full entity graphs and private-history dashboards are NOT selected for initial delivery. The latest cost constraint supersedes earlier hosted-agent advice. Reopen only a specific component if measured evidence shows it cannot satisfy the contract; record why before changing direction. Keep model interpretation replaceable through an interface without installing an unused second model/runtime now.

## 12. Acceptance contract and completion definition

1. **Deterministic integrity:** 200 accepted eligible synthetic events across 10 projects and 30 transport segments, including duplicate callbacks/repeated text, shutdown/reopen and injected write failure. Every event must reconcile to its own committed receipt or explicit omission/failure. Zero silent loss or wrong-thread assignment.
2. **Critical boundaries:** zero wrong-project/private source releases, stale corrections used as current after invalidation, deleted-data resurrection, unsupported ownership promotion, unverified executed-action claims, or stale audio in the defined suite.
3. **Actual model behavior:** freeze 60 development and 40 held-out questions before inference; use English/Hindi/Hinglish, indirect references, multiple similar trips, unknowns and correction/time cases. Initial target >=95% source-supported correctness in each set and all critical cases passing. These are proposed acceptance thresholds, not historical pass results or a universal guarantee.
4. **Delivery evidence:** assert the exact model-facing context/source IDs and current revision, not merely a successful local function or `ready` log. Review actual answers against those sources.
5. **Latency/cost:** measure archive commit, context preparation, end-of-speech to first substantive audio, cold/warm runs, sample counts and all request/token/audio usage. Initial targets: archive p95 <=100 ms; local context p95 <=300 ms, excluding authentication/provider/STT; simple warm recall first audio p95 <=3 s. Unmet targets are open findings; changes require a recorded rationale, not quiet relabelling. Extra standalone memory-model calls remain zero by default.
6. **Native owner sequence:** Nepal discussion -> follow-up -> sleep -> follow-up -> interview switch -> full restart -> named Nepal status -> correction -> source inspection -> forget -> restart. Use the same isolated encrypted profile and inspect all stages; do not ask the owner to reconstruct missing transcript evidence.
7. **Release:** scoped appropriate automated checks, independent review and exact-head CI precede owner-machine acceptance. Do not bypass the previously rejected full-suite telemetry command. Keep PR draft and `E:\Jarvis\App` unchanged until accepted integration/activation is explicitly directed.

Completion requires recorded evidence for the actual implementation, including failed/unrun cases. Documentation and old component test counts never mark a goal complete. The [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md) owns tasks; [Project State](PROJECT_STATE.md) owns acceptance status; [Current Plan](CURRENT_PLAN.md) owns next work. Any later session starts by reading these three links.

## 13. Documentation and Git cleanup record

- Replaced the stale active-priority plan; preserved its complete prior text at [31 October plan snapshot](archive/operations/CURRENT_PLAN_SNAPSHOT_2026-10-31.md).
- Preserved earlier candidate code, tests, plans and research with explicit historical/deferred/superseded banners. No force-push, history rewrite, branch deletion or removal of another worktree's unique work is part of cleanup.
- Attached the isolated previously detached documentation worktree to `docs/workspace-memory-goals-20261031`. Existing feature branch/worktree is retained.
- The completed cleanup pass changed documentation only. The subsequent owner-authorized implementation adds the initial product foundation; no paid inference, account change, model download, main merge or owner-machine activation has occurred.

Historical documentation verification (before implementation): fresh builder review reported no important findings. Local checks verified the documentation-only scope, 96 relative links and byte-for-byte preservation of the previous Current Plan. Product tests were not rerun for this documentation-only change; no new runtime acceptance is claimed.
