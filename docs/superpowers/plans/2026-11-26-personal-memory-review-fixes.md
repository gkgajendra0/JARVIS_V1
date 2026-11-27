# Personal memory consolidated review fixes

> **For agentic workers:** Use test-driven development for every fix. Independent blocks own disjoint production files; review their results before the final whole-branch review.

**Goal:** Correct the confirmed learning, privacy and acceptance-safety defects without expanding personal-memory slice 1.

**Architecture:** Preserve the existing proposal/policy/reconciliation/storage and authority boundaries. Scope confirmation to a particular plan detail, retain plan identity on slot decisions, and include released provenance in currentness. Bind lab budgeting and recovery to their original identities and preserve per-attempt evidence.

**Tech stack:** Existing Python 3.11, pytest/asyncio, SQLite/SQLCipher and LiveKit interfaces; no new dependencies.

**Spec:** Approved behaviour in `docs/evals/personal-memory-acceptance-amendment-2.md`, evidence-retention policy, and the consolidated read-only review of product `420cf3c2` / lab `6dfc4181`.

## Global constraints

- Work only on this isolated Codex branch; installed App, live memory/key/settings and Claude branches stay unchanged.
- No real model calls, paid acceptance, microphone/UI operation, sealed held-out reads, merge or installation.
- No schema migration or new memory category; approved release limitations remain explicit.
- Preserve frozen acceptance files, both amendments and all historical lab results.
- Tests use fictional data and fake providers. Never infer live-provider qualification from them.

## Review focus

- Partial confirmation must not confirm/discard another pending detail.
- Two plans with the same detail/options must keep independent questions.
- A slot choice must not rename the plan; later named retrieval must still work.
- Forgetting can scrub another fact's provenance without changing its assertion; stale text/audio must be refused.
- New speech/turn/session close during asynchronous follow-up update must cancel stale generation.
- A ledger typo, process crash or cross-build recovery must not silently reset spending or repeat an unresolved operation.

## Task 1: Learning identity and independently scoped clarification (R2-R4)

**Files:** `memory/learning_clarification.py`, `learning_contracts.py` if needed, `learning_runtime.py`, `learning_reconciliation.py`, `learning_extractors.py` if needed; focused learning tests.

**Interfaces:** Existing `QuestionAnswer`, clarification board/note model, runtime confirmation handling and plan slot mutation. Keep existing single-detail callers working; expose independently addressed details rather than treating a grouped answer as blanket confirmation.

- [x] Add failing tests: vehicle-only confirmation/choice/dismissal leaves accommodation unconfirmed; Spiti/Goa questions independent; slot decision retains target plan identity.
- [x] Observe expected failures before modifying production code.
- [x] Implement minimal general identity/detail binding; no phrase-specific rules or evidence bypass.
- [x] Run focused suites including recorded plan decisions, cross-category rules and confirmation lifecycle; inspect actual stored/released state.

## Task 2: Provenance currentness and guarded voice follow-up (R1,R5)

**Files:** `memory/personal_context_projection.py`, `voice/learning_followup.py`, canonical follow-up wiring if necessary; focused session/paging and follow-up tests.

**Interfaces:** `context_scope_signature`, `only_additions_from_turn`, delivery's turn/session/activity guard. Preserve current four-fact read accounting and same-turn additive-learning exception for genuinely unchanged evidence.

- [x] Add failing real-temporary-database test: forgetting a plan scrubs a vehicle quote, invalidating a previously released vehicle-only answer, next-page and audio authorization.
- [x] Add deterministic failing async test: new owner activity/turn/close during `update_chat_ctx` prevents old clarification generation and removes its injected exchange.
- [x] Include relevant provenance in signatures and additive comparisons; carry/recheck the live delivery guard after awaits.
- [x] Verify existing authorization, revocation, paging, cumulative read and follow-up suites.

## Task 3: Lab lifetime budget, provenance and crash/recovery (R6-R9)

**Files:** `voice/project_memory_lab.py`, `personal_memory_acceptance.py`, `paid_acceptance_budget.py` only if needed, Windows launcher only if needed; fake-provider lab tests.

**Interfaces:** Paid lane marker binds canonical ledger identity, per-case/attempt summary provenance, resume step states, recovery product invariance.

- [x] Add failing tests for replacement-ledger resume, mixed-head summary metadata, and started-only crash state.
- [x] Reproduce crash ambiguity before changing behaviour; reconcile recorded committed side effects and never silently repeat model calls/consent/writes.
- [x] Reject changed ledger identity before clients/reservations; preserve designated shared ledger across new Paid labs.
- [x] Preserve source commit/evidence kind in every summarized attempt and clearly identify mixed-build summaries.
- [x] Enforce unchanged product code for the special consent-only cross-build recovery; refuse unrelated cross-build resumes.
- [x] Verify exact launcher/entry path with fake clients and consent, existing allowance/retry handling and completed-step skipping.

## Task 4: Integration, independent review and delivery

- [x] Run all affected offline suites and Ruff/format/diff checks.
- [x] Run the repository test command; investigate failures, compare baseline when needed, and report environment-only failures accurately.
- [x] Fresh whole-branch review of the combined diff; resolve important findings with failing regression tests.
- [x] Update a concise progress ledger with actual commands/results and any rulings. Commit only scoped product/test/docs changes.
- [ ] Report tested commit, changes, verification and unresolved release gates. No paid execution or activation.

## Execution record

- 2026-11-26: User explicitly switched implementation ownership from Claude to Codex and requested execution without repeated handoffs. Reused the existing clean isolated review worktree and created `codex/personal-memory-review-fixes-20261126` at `6dfc4181`.
- Ruling: parallel implementation blocks may touch only their declared files; parent owns integration and lab tooling. This avoids duplicated whole-repository contexts and source conflicts. No shared APIs between learning and voice/privacy blocks are changed without coordination.
- Baseline evidence: prior read-only review verified targeted date/migration/lifecycle, learning and authority suites; both exact-head hosted workflows passed. Known documented limitations are not permission to weaken tested guarantees.
- R1: Signatures and the same-turn-addition comparison now include released provenance. Real temporary-database regressions exercise a cross-category forget that scrubs a still-current fact's quote, plus cached reads, paging and audio authorization.
- R2-R4: Each pending plan detail has its own question ID, bound to the matched/created canonical plan predicate. Only answered details close; explicit multiple confirmations from the same proposal reconcile together. A slot decision keeps the plan's stored identity. Model labels and another plan's matching options cannot authorize a confirmation.
- R5: Delivery checks owner turn, activity epoch, session state and agent both before and after the asynchronous context update. Obsolete delivery removes only its injected local messages and does not generate a reply. Already-sent provider history cannot be recalled; this is not claimed as a provider-history erasure guarantee.
- R6: Paid acceptance is bound to the originally approved shared ledger path, also pinned before the first lab step. A missing or replacement ledger requires explicit recovery instead of silently creating a fresh budget. This is lab-specific approval enforcement, not a general production billing limit.
- R7: Summaries retain each case/attempt's source commit and evidence kind, including historical attempts. Mixed-build evidence is marked explicitly; old rows without metadata remain unspecified.
- R8: A crash leaving only a started row now refuses automatic continuation, even with RetryInterrupted. Actual side effects must be reconciled before a separately justified recovery; no generic crash-replay override was added.
- R9: Consent-only cross-build recovery compares actual committed product, policy and dependency trees. Only the four existing lab modules may differ. A hermetic Git repository test verifies that lab-only changes pass and product changes fail.
- Test-boundary correction: removed a test's direct read of the sealed held-out file. It still verifies the frozen hashes and the runner's sealed-file boundary; no held-out contents were inspected or executed in this work.
- RED evidence: the eight original acceptance-safety regressions failed before the lab changes; the per-detail/plan and provenance/voice regressions likewise failed on their original defects before their fixes. Added real-tree Git coverage then caught an inherited malformed GIT_CONFIG_COUNT in the test subprocess; the fixture now supplies its own Git configuration.
- Focused verification: 126 passed / 1 skipped across acceptance guards, Paid lane and harness; 77 passed across clarification, voice currentness, context runtime and explicit mutation target reads. Four Google Python-version dependency warnings in the latter run. No provider request was made.
- Independent combined read-only review: no actionable findings across R1-R9. Review did not execute tests or qualify a live provider.
- Final local verification: `python -m pytest -o addopts= -o faulthandler_timeout=60 -q -p no:cacheprovider --tb=short` completed with **5,401 passed, 20 skipped, 4 dependency warnings**, exit 0, in 493.01 seconds. The machine profile was isolated, provider API credentials removed, and source PYTHONPATH pointed to this worktree. No new failures and no baseline comparison were needed. An earlier buffered collection run was stopped for diagnostic visibility; it is not counted as a completed result.
- Repository-wide `python -m ruff check .`, scoped `ruff format --check`, and `git diff --check` pass. Frozen acceptance/amendment files have no diff against the base. No current-head hosted CI result is claimed until it actually completes.

## D13 follow-up after the completed review-fix phase

- The R1-R9 implementation phase completed at `7e787c53d125e5413d67e5dd214751d8fffe8eb9`; its full local Windows result was 5,401 passed / 20 skipped and hosted CI passed all six checks on the first run (draft PR #337). Those results apply to that head, not later changes.
- On the owner's request to continue, one Paid development run used the existing approved USD1 lifetime ledger in a new fictional lab, `E:\Jarvis\Temp\slice1-acceptance-codex-7e787c53`. The implementation-phase prohibition on model calls did not authorize spending; the separate earlier owner approval for Paid development acceptance did. No held-out, voice or production work was started.
- The run stopped automatically at D13. Ledger cost increased from USD0.207608 to USD0.246734: this run USD0.039126, remaining USD0.753266. No retry or new Paid run followed. Original case/step/event/summary files remain unchanged; separate manual grades and raw hashes are in `profile/codex-manual-review.json`.
- Correction to the initial verbal diagnosis: the Rishikesh plan was released, and answering the generic question "What's coming up?" with Spiti was not itself a false answer. The actual D13 failure was missing `passed_outcome_unknown` metadata. The exact recorded extraction held `October 2026` in confirmed `slots.when`, but omitted the optional duplicate `time_expression`; calendar handling used only the latter.
- Ruling: a supplied, admitted plan schedule is the canonical plan time. Reuse the existing grounded-slot rules and calendar parser, retain legacy top-level-only proposals, and never derive a decided calendar from pending/tentative schedule options. Keep the existing precision and original quoted-turn anchor. This is one representation-consistency rule, not a destination- or wording-specific repair.
- The exact recorded extraction is preserved in the regression fixture. Before the fix, 12 of 14 focused tests failed, including the real-database/harness D13 replay. After the initial fix, all 14 passed. Further negative tests caught stale calendars after accepted undecided schedules; those were fixed without weakening the frozen cases.
- Independent delta review found one related expression-only correction guard: repeating "next month" on a later turn retained the old calendar. Two tests reproduced it first; the guard now compares expression, precision and bounds. Date/correction tests then passed 31/31, and the reviewer closed the finding with no new issues.
- A broad offline run passed 1,827 tests and skipped nine, with three Git-command failures caused by inherited `GIT_CONFIG_COUNT` lacking its value. Their exact traces confirm an environment error, not a memory regression. The final rerun with `GIT_CONFIG_COUNT=0` passed **1,832 tests, nine skipped, four dependency warnings**, exit 0, in 189.77 seconds. It covers all learning tests, calendar tests, personal-context runtime and explicit mutation target reads, including the two review regressions added after the first run. Repository-wide Ruff and scoped formatting/diff checks pass.
- No failed lab resume, consent bypass, frozen-case edit, schema change, installation or further Paid evaluation is authorized by this fix record.
- 2026-11-27 boundary follow-up: default-empty `when={}` means unspecified and must retain a valid legacy plan date. A legacy time-only update must also update an existing schedule slot instead of leaving two contradictory dates. Three offline tests reproduced these gaps first; the date/correction/harness suite then passed 109 tests with one skip.
- Independent review caught the distinction between default-empty and explicitly uncertain/tentative empty schedules. Six create/change/correction cases failed first. Both normalization and legacy synchronization now share the same unspecified-schedule predicate, so explicit uncertainty suppresses the legacy fallback. The reviewer closed this finding and found no additional issue; no provider calls were made for these checks.
- Final follow-up verification: all affected learning, calendar, personal-context runtime and explicit-target-read tests passed **1,841 tests, nine skipped, four dependency warnings**, exit 0, in 190.56 seconds. The run used an isolated machine profile, provider credentials removed and `GIT_CONFIG_COUNT=0`; durable output is under `.superpowers/verification/final-plan-time-subset.*`. Ruff, formatting and diff checks pass. Hosted CI on the preceding `e15b9b0dc` head passed; it is not claimed as verification of this later follow-up.
- Fresh read-only verification: all four raw stopped-lab file hashes still match the separate manual-review record. Shared ledger: 255 settled requests, USD0.246734 charged, zero held reservations, USD0.753266 remaining. Installed App remains clean on main `29714335`.

## D28 and D18 follow-up from owner-run acceptance

- The owner now runs PC acceptance manually and shares reports. No further model execution is part of this repair. Historical laboratory files and their raw grades are not rewritten.
- On product `7b580710`, the owner-run remaining-groups report records D3, D19, D20 and D24 as REVIEW, D1-R as PASS, then stops at D28 FAIL. D19 and D20 explicitly disclose partial results; D24 asks which trip. Their supplied answers satisfy manual review. D3's exact one-Hello observation remains unconfirmed. D29, D30 and D25 were not reached.
- D28's recorded extraction chose Jimny correctly and answered the open vehicle question, but composed both plan label and value as `trip to Spiti`, a phrase not stated in either cited owner turn. Literal eligibility rejected it before resolution. The fictional extraction is preserved unmodified in `tests/learning/fixtures/codex_7b580710_d28.json`; only turn IDs are rebound by the offline replay. That replay first failed with no stored vehicle.
- Repair: an answered alternatives question may supply its own original grounded display identity only when both proposed identity fields are unsupported. The selected option must be confirmed, belong to that question, and occur in the latest cited owner words. The original statement must still be cited and available, the session must match, and precisely one canonical plan predicate must be identified. The normal eligibility and reconciliation gates still run, with that canonical target required. Already-grounded identities are never redirected. This adds no sentence or destination rule and does not broaden literal grounding generally.
- The recorded D28 replay now selects Jimny on the same plan, retains January, and closes the vehicle question. A resolver calling it new still resolves the exact known identity rather than creating another plan. Guard tests cover missing/expired evidence, no answer, unbound and other-session questions, unsaid/tentative choices, already-grounded different identities, different predicates and unclear questions.
- Separate D18 grader defect: the frozen case explicitly allows a truthful partial list OR paging. The owner received `11 saved; here are 8` and an offer to continue, with tool total 11 and first-page complete=false. The old grader nevertheless required a second page. It now records whether pagination ran, permits the partial branch and retains mandatory manual answer review. Attempted incomplete pagination still fails. D25's actual multi-page requirement is unchanged and remains outstanding. The earlier raw D18 FAIL is historical evidence of this grader defect, not a failed pagination test or an automatic current-head pass.
- Latest owner-supplied budget snapshot: USD0.343500 committed, USD0.656500 remaining of the shared USD1 ceiling. This is the supplied run's snapshot, not a fresh ledger audit. No new Paid calls were made for this repair. D13's earlier wording review, D3's consent-count observation, remaining development checks, held-out and quiet-room voice acceptance are not waived; nothing is merged or installed.
- Verification: affected learning, calendar, personal-context runtime and explicit target-read suite: **1,856 passed, nine skipped, four dependency warnings**, exit 0, in 192.22 seconds (`.superpowers/verification/d28-d18-affected.*`). The final focused set, including the added resolver-new variant, passed **51 tests**. Repository-wide Ruff, scoped formatting and diff checks passed. A separate reviewer found no actionable code issue; its own test attempt lacked pytest, so these executed test results are the implementer's evidence. Regrading the supplied D18 tool/answer report offline returns four structural PASS checks and answer REVIEW, with pagination_exercised=false; manual review accepts the truthful partial answer. No provider or laboratory data was mutated.

## Clarification-to-memory handoff (consolidated review, 2026-11-27)

- Lab `E:\Jarvis\Temp\slice1-acceptance-codex-ef0c9340-final` (preserved unchanged; events sha256 `1ff740a9…d017`) stopped at D28. The extractor read "We'll take the Jimny." correctly as `chosen` with vehicle Jimny, but it proposed the plan as "trip to Spiti" (paraphrase, kind `vehicle`), cited only the answer turn and restated destination/January. `ground_chosen_plan` required the question's turn to be cited, so the proposal stayed ungrounded and nothing was saved. Product handoff defect; not a provider or grading defect. The 7b580710 replay passed only because that recording happened to cite both turns.
- Reproduced offline first: `tests/learning/fixtures/codex_ef0c9340_d28.json` (recorded extractions, unmodified apart from turn-id rebinding) fails on ef0c9340 through the real runtime and through the lab runner.
- General repair (no wording rules): an answer becomes one proposal per plan built from the trusted question (identity; the owner's original words still in the learning window; the current turn cited in full; only the answered details; no restated time/place/status). The chosen value remains the extractor's reading and is accepted only when decided, said as a whole word in a statement of the current turn (owner's spelling), and attributable to one question. Unchecked, contradictory, tentative, ambiguous, unbound or expired answers store nothing and leave the question open (`answer_not_used` with a reason). The extractor's overlapping proposal is replaced; other decided details said in the same answer go with it, never an asked or already-known detail. A question back is never an answer. Reconciliation binds the answer to the question's canonical predicate (always supplied in the catalog), keeps the stored kind/status/certainty, refuses an ended plan; a plan ending closes its questions. Unclear-detail questions use the same path. Replaces `ground_chosen_plan`.
- Trade-offs: adding a `value` field to the provider answer schema was rejected (provider contract change, recordings lack it); the value is read from the extractor's proposed slot instead. A choice not said in the current turn ("the second one") is not stored. A changed known detail said inside an answer is not applied with it.
- Reply: "Understood" on alt-01 ignored the learning note; the instruction now says a brief acknowledgement alone does not answer a learning note. Unverified live. alt-02's "Jimny it is" is a conversational acknowledgement, not a storage claim; replies still never receive storage results.
- D13 wording ("The Rishikesh trip was in October 2026") stays REVIEW, not passed: metadata passes, wording may imply it occurred and does not say the outcome is unknown. D18 grader unchanged since the correction; D25 still requires four pages and 32 items.
