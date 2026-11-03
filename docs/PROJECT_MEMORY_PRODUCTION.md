# Project memory in normal Jarvis voice — production readiness

Status: **integration prepared, disabled by default, NOT activated.** The stack is
#303 (text project memory) → #305 (search, soft scope, one Hello per session) →
#306 (native voice, lab only) → this integration. Nothing here merges a PR or
changes the installed Jarvis. Activation needs the owner's approval.

Functional memory, cross-project recall, correction, persistence and latency
were accepted manually and are not repeated here.

## 1. Feature flag

| Setting | Values | Default | Effect |
| --- | --- | --- | --- |
| `JARVIS_PROJECT_MEMORY_MODE` (machine profile or environment) | `off`, `voice` | `off` | `voice` adds project memory to owner wake conversations in `jarvis-voice` |

**With the flag off** (the default):
- `build_production_voice_runtime` passes no project memory.
- Every branch it guards returns early.
- Tools, instructions, the audio path, Hello prompts and database writes are
  identical to before.
- Tests cover this: `test_flag_off_builds_no_project_memory` and
  `test_no_project_memory_leaves_sessions_untouched`.

**With the flag on**, the voice-lab path is used, with these production differences:

| | Voice lab | Production (`voice`) |
| --- | --- | --- |
| Tools | allowlist `enter_standby` + `prepare_project_turn` | the normal tool set + `prepare_project_turn` |
| Hello denied or timed out at startup | lab stops | Jarvis runs as ordinary voice; ERROR in the log |
| Unqualified configuration (§4) | n/a | Jarvis runs as ordinary voice; the reasons are logged at ERROR before any Hello prompt |
| Sessions that use project memory | every session | owner wake and proactive conversations only. System sessions get none: startup greeting, status, work delivery, update approval. |
| History grant lapses (Windows lock or user switch) | — | later wakes run as ordinary voice until restart; logged once; counted in `paused_sessions` |

`python -m jarvis.voice.project_voice_production --check` prints whether the
configured flag would activate, and why not, without starting Jarvis.

**No new database migration.** The integration adds none. No turn is written
twice: each accepted owner turn is saved once to the project archive. Canonical
memory (explicit remember/forget, candidate extraction) is unchanged. The two
stores hold different things: conversation history versus facts.

## 2. Answer grounding (#303 open items)

| Item | Where | Classification |
| --- | --- | --- |
| Nepal answer linked "rental consideration" to the Jimny with no source stating that link (`p0-q0`, repeated live) | text lab answer prompt | Model grounding weakness, not a deterministic defect. Not on the production path: native voice does not use `ProjectAnswerProvider`. Accepted lab limitation. |
| Interview answer said "sorted" without "you reported" (`p1-q1`) | same | same |
| Eight search hits can omit older evidence, including corrections | text search | Lab limitation. Voice has no archive search: it sees recent history (preload ≤12 rows, tool packet ≤32 rows). Older facts are unreachable by voice and are reported as unknown, never guessed. |
| Voice instructions lacked the text prompt's grounding rules | **production path** | **Fixed here.** Voice instructions now say: saved history is past conversation, not verified fact; Jarvis's replies are not owner decisions; a newer owner statement wins; memory tools are authoritative for the owner's own facts; connect facts only when a row states the link; present owner reports as such. |

The grounding rules are model instructions, so they lower the risk but do not
guarantee behaviour. Their live effect is unmeasured: no model calls were made
for this work. The release gate for grounding is a short live check on the
owner machine (§6, step 7).

## 3. Interaction review

| System | Finding | Disposition |
| --- | --- | --- |
| Canonical memory | Separate tables in the same SQLCipher/DPAPI database, under the same history authority. Voice packets carry no canonical personal facts; the memory tools still answer those. | OK. Instructions route personal facts to the memory tools. |
| Canonical forget / correct | `forget_memory` removes a canonical fact but **not** the archived turn where the owner said it. Project history can keep resurfacing it. Only whole-project `/forget` (text lab) removes archive rows. | **Activation blocker B4** (owner decision). |
| Retention pause | Honoured: a paused project saves only an omission marker and releases no history (preload included). | OK |
| Windows Hello | One approval at Jarvis startup (grant per runtime). A WTS session change (lock, unlock, user switch) revokes it, by design. | **B1** usability decision. Fails safe (ordinary voice). |
| Voice sessions | Before this change, every session the factory made got project memory, including system utterances and update approval. The owner's "yes" to an update would have been saved as project history, and history preloaded into a greeting session. | **Fixed:** `VoiceRuntimeController._system_session`; tests cover it. |
| Gemini fallback / handoff | A handoff builds a new agent from canonical turns only. It drops the preload and tool results, and its new model keeps the default NON_BLOCKING tools. The gate would then believe context was delivered. | **B2:** refused while `gemini_fallback.enabled`. |
| OpenAI provider | Blocking Gemini tool behaviour is required. | Refused unless `JARVIS_AI_PROVIDER=gemini`. |
| Personal context APPLY / learning | It has its own audio gate and session retirement around tool-follow-up handles. The combination has not been qualified with project memory. | **B3:** refused while enabled. |
| Model routing (tools) | `require_blocking_realtime_tools` is model-wide. With the flag on, **every** tool is BLOCKING, including Hands, research and work: Gemini waits silently for a result instead of speaking over it. | **B6** qualification item. |
| Database migrations | Migrations 0004–0007 come from #303/#305. They run on the first start of the merged build **even with the flag off**. Main refuses a newer schema (`MemorySchemaTooNewError`). | **B5:** merge-time rollback hazard; back up first (§6). |
| Machine profile | Older builds reject unknown keys in `machine.json`. A build without `JARVIS_PROJECT_MEMORY_MODE` in its allowlist will not start while the key is present. | Rollback order in §7. |

## 4. Blockers

Merging with the flag off is blocked only by the PRs' own status (draft, owner
approval) and B5's backup requirement. Activation is blocked as follows.

| Id | Blocker | What clears it |
| --- | --- | --- |
| B1 | After any Windows lock or unlock, project memory pauses until Jarvis restarts and Hello is approved again. Turns spoken meanwhile are not saved (ordinary voice). | Owner choice: accept restart-to-resume (as personal learning does today), or a separate task that re-prompts Hello at the next wake. |
| B2 | Gemini fallback / transport handoff is unsupported. | Run with fallback off, or implement handoff re-preload plus blocking tools on the new model. |
| B3 | Personal context / learning APPLY is unsupported together with project memory. | Run with them off, or qualify the combined gates. |
| B4 | Fact-level forget does not reach project history. | Owner accepts and is told; or add per-turn archive forget. |
| B5 | Schema migrations 4–7 are one-way for older builds. | Back up the database before the first run of the merged build. |
| B6 | All tools become BLOCKING with the flag on. | Check Hands/research/work replies in the step 7 smoke run. |
| B7 | Grounding and answer quality are unmeasured live in production voice. | Step 7 smoke run. |
| — | No voice controls for `/projects`, `/inspect`, `/pause` or `/forget`. | Use the text lab between runs (accepted limitation). |

## 5. Rollback

1. **Flag rollback (instant, preferred):** set `JARVIS_PROJECT_MEMORY_MODE=off`
   (or delete the key) and restart Jarvis. History stays encrypted and unused.
   Nothing else changes.
2. **Code rollback to a pre-merge build:** stop Jarvis and remove the
   `JARVIS_PROJECT_MEMORY_MODE` key from `machine.json` first. Then restore the
   database backup from §6 step 2. The older build refuses a schema-7 database
   and rejects the unknown key. Canonical memory written after the backup is
   lost in this path.

## 6. Activation procedure (owner only, after approval)

Paths are the installed defaults: app `E:\Jarvis\App`, data
`E:\Jarvis\Data\LocalState` (junction `%LOCALAPPDATA%\JARVIS`).

1. Stop Jarvis (close `jarvis-voice` / the supervisor task) and confirm that no
   `jarvis-voice.exe` process remains.
2. Back up `memory.db`, `memory.db-wal`, `memory.db-shm` (if present),
   `memory.key.dpapi` and `machine.json` from the data folder into a dated
   folder.
3. Install the approved merged build into `E:\Jarvis\App` as usual. Leave the
   flag **off** and start Jarvis once: migrations 4–7 run. Confirm normal voice
   works, then stop Jarvis.
4. Clear B2/B3 if needed: `JARVIS_GEMINI_PAID_FALLBACK_ENABLED` off,
   `JARVIS_PERSONAL_CONTEXT_MODE=off`, `JARVIS_PERSONAL_LEARNING_MODE=off`.
   Also required: `JARVIS_MEMORY_ENABLED=true`, `JARVIS_AI_PROVIDER=gemini`.
5. Add `"JARVIS_PROJECT_MEMORY_MODE": "voice"` to `settings` in
   `machine.json`, then run
   `E:\Jarvis\App\.venv\Scripts\python.exe -m jarvis.voice.project_voice_production --check`.
   It must print "will start with Jarvis".
6. Start Jarvis and approve Windows Hello. The log must show `Voice project
   memory active`; `Project memory NOT active` means a blocker remains.
7. Smoke run, about 10 minutes, then judge B6/B7:
   - an ordinary question, a project command and a cross-project question
   - one Hands command and one research question (they speak after their tool finishes)
   - one lock/unlock, confirming the logged pause (B1)
8. On any problem: §5 step 1.
