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
| History grant lapses (Windows lock or user switch) | same | that wake runs as ordinary voice; a fresh Windows Hello approval is requested in the background; later wakes use the new grant (§8) |

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
| Canonical forget / correct | Before #308, `forget_memory` removed a canonical fact but not the archived turn where the owner said it, so it could resurface. | **Resolved in #308** (§8): voice forgetting also removes the matching saved conversation. |
| Retention pause | Honoured: a paused project saves only an omission marker and releases no history (preload included). | OK |
| Windows Hello | One approval at Jarvis startup (grant per runtime). A WTS session change (lock, unlock, user switch) revokes it, by design. | **Resolved in #308** (§8): renewal at the next wake, without a restart. |
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
| B1 | **Resolved in #308.** The first wake after a lock/unlock runs as ordinary voice (its turns are not saved) while Hello renews in the background. | Owner decisions D1/D2 (§8). |
| B2 | Gemini fallback / transport handoff is unsupported. | Run with fallback off, or implement handoff re-preload plus blocking tools on the new model. |
| B3 | Personal context / learning APPLY is unsupported together with project memory. | Run with them off, or qualify the combined gates. |
| B4 | **Resolved in #308.** Matching uses all the owner's words (§8). | Owner decision D3 (§8). |
| B5 | Schema migrations 4–7 are one-way for older builds. | Back up the database before the first run of the merged build. |
| B6 | All tools become BLOCKING with the flag on. | Check Hands/research/work replies in the step 7 smoke run. |
| B7 | Grounding and answer quality are unmeasured live in production voice. | Step 7 smoke run. |
| — | No voice controls for `/projects`, `/inspect` or `/pause`. Whole-project `/forget` is text lab only; forgetting what was said about something works by voice (#308). | Use the text lab for the others (accepted limitation). |

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

## 8. Forgetting, long-term recall and Hello renewal (#308)

### Forgetting by voice

"Forget that we're taking the Jimny" now covers both stores:

1. **Canonical memory:** `forget_memory`, unchanged, with its existing rules.
2. **Saved conversation:** `forget_saved_history(words)`. It refuses unless all
   of these hold:
   - the latest owner utterance is a forget request;
   - every word passed was said by the owner;
   - there are 1–6 distinctive words (the verb itself does not count).
3. The owner's request is saved first, so it is forgotten along with
   everything else.
4. **What is found (preview):** every live row in any project that contains
   **all** the words (FTS5 candidates, then an exact case-insensitive check).
   It also finds every Jarvis reply or tool result generated with one of those
   rows in its context, by following evidence edges transitively. Matching more
   than 64 rows refuses with `too_broad`, and nothing is deleted.
5. **Fresh Windows Hello approval:** the prompt shows the words, the counts and
   the affected projects. If it is denied, times out, or anything covered
   changed since the preview, nothing changes.
6. **What is removed:** the rows are redacted in one transaction to immutable
   tombstones (as project forget does), along with their evidence links,
   quarantine entries and derived thread state. The FTS index is then
   rewritten, so the words leave its segments. Owner turns that don't contain
   the words are kept, and so is everything else.
7. **Afterwards:**
   - the confirmation reply is never saved;
   - the wake session ends after it, because the live Gemini context still
     held the words; the next wake starts from the cleaned archive;
   - it works across restarts: tombstones are durable, and preload, search and
     packets never return them.
8. **Coupling:** if Gemini forgets only the canonical fact, Jarvis then asks
   it, deterministically, to also call `forget_saved_history`. A failed
   canonical forget triggers nothing.
9. **Audit:** the history authority records the approval, and a
   content-free log line gives the counts.

### Long-term recall

`search_project_history(query)` reuses the authorized FTS5 search from #305:

- **Scope:** the current project first, then other projects only on no match.
  Hits keep their project label.
- **Bounds:** 8 hits and 2,400 characters of whole rows per search, and two
  searches per utterance. Rows already in the conversation are not resent, and
  the question itself is excluded.
- **Order and corrections:** rows are dated and oldest-first. The guidance says
  the newest owner statement is current and that the reply should mention a
  change.
- **Evidence:** returned rows become reply evidence, so forgetting them removes
  the reply.

Cost: one extra tool round trip, only when Gemini decides an older detail is
needed. Ordinary fast-path turns are unchanged. Local cost is measured as
`search_ms` / `search_bytes` (tests assert under 500 ms on CI). The added fixed
prompt is about 70 tokens of instructions plus two short tool schemas.

### Windows Hello renewal

A wake whose grant lapsed (Windows lock, unlock or user switch) does three things:

1. It runs as ordinary voice.
2. It revokes the old grant; a revoked grant is never reused.
3. It requests a fresh grant in the background, which shows a Hello prompt.

After approval, later wakes use project memory again without a restart. After a
denial or timeout, voice stays ordinary and Jarvis does not ask again for 5
minutes (`RENEWAL_COOLDOWN_SECONDS`). New counters: `renewals` and
`renewal_failures`.

### Decisions for the owner

- **D1:** the renewing wake itself is ordinary voice, so its turns are not
  saved. The alternative is to hold the wake until Hello is answered, which
  delays the first reply.
- **D2:** the renewal cooldown after a denial or timeout is 5 minutes.
- **D3:** forget matches rows containing **all** the given words, across all
  projects, and removes replies generated from them, even ones that never
  repeated the words (conservative provenance). Paraphrases without the words
  (for example "the Suzuki" for "the Jimny") are not found; say them
  separately.

### Remaining limits

- Canonical `forget_memory` keeps its legacy exact-command rules. With
  personal context off, the owner must name the fact's key.
- Older replies saved before provenance tracking (migration 0007) have no
  evidence edges. They are removed only if they contain the words.
- Gemini still chooses whether to call search; recall of old facts depends on
  that choice.
- The live model effect of search and forget wording is untested; no model
  calls were made.

