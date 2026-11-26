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
