# Topic Continuity Implementation Plan

**HISTORICAL implemented candidate; native acceptance FAILED.** The old field-checkpoint path below remains code/test evidence. Two exact-head hosted runs passed at `7800e984780b36ee18dd5e4be61a85b899bc7def`, but the 30 October owner trace returned empty Nepal details. It does not preserve complete conversations. The [31 October contract](../../PROJECT_CONVERSATION_MEMORY.md) and [current build plan](2026-10-31-project-conversation-memory.md) own the replacement. Historical checklist/status wording below is not replacement completion.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect accepted topic updates, encrypted persistence and model-visible tool results across sleep and restart.

**Architecture:** A process-owned coordinator survives wake sessions, while canonical USER turns, source-bound learning permits and SQLCipher remain authoritative. The realtime model proposes grounded updates through a blocking function tool; the application returns the selected topic before the model answers, avoiding an additional extraction-model call. A short owner-bound continuation lease can select the recent topic across sleep; restart or expiry requires naming the topic. The existing protected response retires after playback and rechecks revisions before audio.

**Tech Stack:** Python 3.11, LiveKit, Gemini Live, canonical SQLCipher workers and personal-learning authority.

**Spec:** The user-approved save / restore / reply design in the conversation, recorded above. Main Windows installation stays unchanged until isolated native acceptance.

## Global Constraints

- No plaintext memory, new database or serialized authority handles.
- Save each validated update; sleep never waits for a new model request.
- Ordinary runtime remains unchanged unless continuity is explicitly configured.
- Bind writes to canonical source, exact payload and current plan generation.
- Read and audio require current owner permission; forget/suppression invalidates continuity.
- Do not replace Jimny/Gemini using an alias. Ask to clarify uncertain entity recognition.
- Restore before using a checkpoint; never manufacture current provenance for stored fields.

## Review Focus

- Lock/revoke during storage or provider result: no facts escape.
- New speech during a tool call: old response cannot use newer source.
- A forgotten or suppressed topic cannot be selected by a cached continuation.
- Restart/lease expiry never silently guesses the topic.
- Provider tool arguments do not substitute for the canonical transcript.

### Task 1: Safe restored-state and continuation storage contracts

Files: `conversation_semantics.py`, `conversation_checkpoint.py`, relevant tests.

- [x] Test restoration followed by grounded correction; test authorized short continuation read and denied stale lease.
- [x] Run tests RED, implement explicit snapshot restoration and a separately guarded continuation-read entry point, run GREEN.
- [x] Add optional transaction scope for exact delegated checkpoint writes; existing named reads stay strict.

### Task 2: Process-owned coordinator

Files: new `memory/topic_continuity.py`, new `tests/learning/test_topic_continuity.py`.

- [x] RED: real storage/authority Nepal → Jimny → new wake → permits; restart named restore; correction; forget; revoke; uncertainty.
- [x] Implement bounded selection, source registration, payload-bound write child, transactional commit guard and revision-stamped result.
- [x] GREEN targeted tests. No extra model client or raw transcript replay.

### Task 3: Response-path integration

Files: `personal_context.py`, `canonical_active_speaker_runtime.py`, `production_runtime.py`, `agent.py`, tests.

- [x] RED: tool result contains restored Nepal/Jimny; stale source/permission yields no context; revision invalidates audio.
- [x] Expose blocking grounded topic tool only with a coordinator factory; reuse delegated read consent and protected response lifecycle.
- [x] Wait boundedly for the current canonical transcript when realtime tool dispatch precedes transcript delivery.
- [x] GREEN controller/tool and authority regressions.

### Task 4: Isolated native continuity entry point

Files: `semantic_smoke_lab.py`, new continuity launcher module, smoke tests and guide.

- [x] RED: continuity installs the real coordinator with canonical store and grant; profile can reopen for restart acceptance without copying production memory.
- [x] Implement explicit continuity mode, honest startup text and retained isolated profile. No script-only admission or separate extraction request in this mode.
- [x] GREEN launcher tests. Keep old extraction smoke available.

### Task 5: Verification and publication

- [ ] Ruff, focused memory/voice/provider regressions and full pytest attempt; record host limitations by name.
- [ ] Fresh whole-change reviewer; fix important findings with failing regression tests first.
- [ ] Commit and publish draft branch with expected-head lease; check hosted CI.
- [ ] Native acceptance remains pending until actual Windows speech results are supplied.

## Execution ledger

- Existing isolated worktree confirmed; clean baseline at local `6f312a2`, matching remote `dbd75b0b` tree. Prior hosted CI passed; local full suite has established spawned-PID visibility failures.
- User explicitly authorized implementation after approving the proposed solution; execute inline without another confirmation loop.
- Interfaces: store restoration → coordinator → protected personal-context tool → native launcher. Same issuer/grant and store must reach all four boundaries.


## Completion evidence — 30 October

- Tasks 1–4 complete. Final combined memory/learning/semantic/voice/provider-guard suite: **624 passed in 27.35 seconds**. Repository Ruff check passes; format check reports 1182 files already formatted.
- Storage and authority tests use real canonical workers and issuer. SQLite is a test fixture, not a runtime plaintext fallback. The isolated Windows runtime continues to require SQLCipher/DPAPI/Hello.
- The actual model-facing function result contains Nepal and Jimny together after separate wakes. A real transport guard forwards that result only while the current permit/revision is valid; lock/revoke blocks subsequent provider/context/audio release in the automated boundary test. This is not a live Gemini answer-quality claim.
- Fresh independent review found three Important issues, all reproduced RED and fixed GREEN: queued tool rebinding (`test_queued_old_tool_does_not_rebind_to_new_canonical_request`), quote-selected question laundering (`test_model_quote_cannot_hide_that_canonical_source_is_a_question`), and negated confirmation (`test_negated_or_interrogative_confirmation_never_saves_gemini`). No Critical or deferred Minor findings were reported.
- Additional RED→GREEN regressions cover concurrent lost updates, post-commit revision replacement, stale transcript selection, pre-suppression accepted-source generations, grant rotation, profile symlink escape, article-based uncertainty bypass and negative memory-control source admission.
- Source epochs are now captured synchronously in the accepted-turn observer. Canonical source records are grant-bound, leased for 30 seconds and bounded to 128 live records / 4096 observed inputs; they cannot be re-admitted after expiry with a newer generation.
- Full local pytest was attempted and reached the final portion of the suite, but **automatic approval review stopped it** because a test attempted outbound Microsoft telemetry with an unknown payload. The full command was not retried or bypassed. Restricted memory/voice tests remain the verified alternative.
- An existing unrelated routing process-recovery test is still red in isolation: `tests/gemini_fallback/test_review_repairs.py::test_recovery_owner_survives_ttl_but_dead_process_does_not_strand_free` fails at `assert recovered is not None`. No routing process-identity code was changed or weakened. This run is not claimed as a fully green local suite.
- Exact-head hosted CI and real Windows speech, restart, correction, completion, forgetting and lock acceptance remain required before merge or installed-runtime activation.

### Implementation decisions

- Ruling: use the realtime model's blocking function tool rather than a second extraction request — puts restored context in the response path and removes the separate extractor call — native tool-round-trip latency still needs measurement.
- Ruling: recent continuation selection lasts 600 seconds and belongs to the exact in-process grant/revision; restart, rotation or expiry requires naming a topic — avoids silently selecting stale private work — may require one additional clarification.
- Ruling: retain a conservative plan-only admission policy and existing negative-memory-control/secret gates — this is not a universal privacy classifier — some unsupported natural formulations can be denied; broad arbitrary-memory activation is not claimed.
- Ruling: keep ordinary production startup unchanged and qualify via a distinct isolated continuity entry point — follows the user's testing-before-activation requirement — installed Jarvis does not receive this feature until qualification and integration are accepted.
