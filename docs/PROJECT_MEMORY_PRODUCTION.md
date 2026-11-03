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

### Windows Hello renewal (owner decisions D1–D3 applied)

The first wake after a lock, unlock or user switch (revised in section 12):

1. Revokes the lapsed grant; a revoked grant is never reused.
2. Requests a fresh grant, which shows the Hello prompt.
3. **Starts the realtime session at once**, so speech during the Hello prompt
   is captured. The wake's turns wait **at most 20 s** after the wake
   (`RENEWAL_WAIT_SECONDS`) for the approval before anything is saved,
   preloaded or answered with project context. The inactivity timeout is held
   open for that bounded wait only.
   - **Approved in time:** this same wake saves its turns and answers.
   - **Denied, timed out or failing:** this wake continues as ordinary voice,
     says once: "Project memory is paused, so I won't remember this
     conversation. It resumes after Windows Hello approval.", and saves
     nothing, even if the approval arrives later.
   - **Too slow:** a renewal still running after 20 s may finish in the
     background; the next wake then has memory.

After a failure, nobody is asked again for 5 minutes (D2,
`RENEWAL_COOLDOWN_SECONDS`): those wakes are ordinary, with no wait and no
repeated notice. Counters: `renewals`, `renewal_failures`, `paused_sessions`.
Diagnostics runtime events: `renewal_requested`, `renewal_succeeded`,
`renewal_failed`, `renewal_ready_for_wake` (also recorded in that wake's own
session) and `paused_notice_spoken`.

Forgetting keeps explicit-word matching, cross-project scope, the deletion
preview and a fresh Hello approval. There is no semantic deletion (D3).

### Remaining limits

- Canonical `forget_memory` keeps its legacy exact-command rules. With
  personal context off, the owner must name the fact's key.
- Older replies saved before provenance tracking (migration 0007) have no
  evidence edges. They are removed only if they contain the words.
- Gemini still chooses whether to call search; recall of old facts depends on
  that choice.
- The live model effect of search and forget wording is untested; no model
  calls were made.

## 9. Live qualification (one focused owner run)

This run uses an isolated lab profile only; it never touches the real
database. It exposes the normal tool set with project memory, as the
production flag would. Hands actions are real, so use a safe one.

```powershell
$c = "<final 40-char commit>"; $lab = "E:\Jarvis\Labs\qual-$(Get-Date -f yyyyMMdd-HHmm)"
& "$env:TEMP\Start-VoiceLab.ps1" -Commit $c -LabRoot $lab -Qualification
```

Approve Windows Hello. Then, in one run:

1. **Setup** (not graded): seed one old fact and push it out of the preload.
   - Say "Remember that my car is a Jimny."
   - Say "Our hotel in Kathmandu is Yak and Yeti."
   - Say 13+ short filler notes ("Packing note one: socks", and so on).
   - Stop talking, let the wake end, then wake again.
2. **Q1 recall:** "Which hotel did we book in Kathmandu?" Expect
   `search_project_history`.
3. **Q2 forget:** "Forget that my car is a Jimny." Expect `forget_memory`,
   then `forget_saved_history`, then the Hello prompt. Approve it, let the wake
   end, wake again, and ask "What car do I have?" It must not be known.
4. **Q3 tools:**
   - "Open Notepad." (Hands, then close it yourself.)
   - "What's the weather in Kathmandu today?" (research)
5. **Q4 renewal:** lock Windows (Win+L), unlock, wake Jarvis, and approve Hello
   within 20 s. Then say "Add a stove to the packing list."
6. Ctrl+C. Grade with `-GradeQualification` (no model call); see the
   `-DiagnosticsReport` page for audio and transcripts.

The grader writes `qualification.json` next to the sealed run, with PASS, FAIL,
NOT_RUN or REVIEW per step. Its rules were revised after the run at 8155df0d
(section 12); the module docstring of `project_voice_qualification.py` is the
authoritative list. Listen to the audio before accepting the transcripts.

## 10. First-turn fix (live -Qualification at 3938b428)

**Symptom.** In a fresh lab, the first utterance "Remember that my car is a
Jimny" ran `remember_memory`, and both canonical memory and project history
committed. Routing silently opened General. Then:
- the audio gate withheld the reply;
- the tool re-request produced nothing audible;
- the session timed out in silence (`unprepared_responses_blocked=1`,
  `repairs=1`, `undelivered_user_turns=1`).

**Root cause: the gate rejected a valid answer.** The session preload ran with
no project, so the fast path recorded Gemini's context as "no project". The
first turn's routing then committed the new General workspace. From then on
the gate saw "routing moved since the preload" and treated Gemini's context as
stale. That was wrong: a silently opened, empty workspace has no history to
give. A second defect turned the block into silence: the repair depended on
Gemini calling `prepare_project_turn`, and nothing covered the case where it
answered nothing at all.

**Fix (the gate is unchanged in what it requires):**
1. A silently created empty project, i.e. the default General workspace on a
   first ordinary turn, keeps the fast path current (`fast_context_synced`).
   A silent switch to an existing project is preloaded again. Announced
   changes still go through the context path.
2. **Repair by delivery:** when an answer is withheld, the application itself
   adds the prepared context to Gemini's conversation. It is exactly what
   `prepare_project_turn` would have returned. The application then
   re-requests the answer, and tells Gemini not to repeat a tool call that
   already ran. The old tool re-request is kept only when no running agent is
   available.
3. **Watchdog:** if a re-request yields no audible reply within 8 s
   (`REPAIR_RESPONSE_SECONDS`), the fixed fallback is spoken
   (`repair_unanswered`, counted in `repair_timeouts`). The owner is never left
   in silence until the session times out.

The turn is still saved exactly once by the application; the canonical write
happens once, in `remember_memory`. New counters: `fast_context_syncs`,
`repair_deliveries` and `repair_timeouts`.

## 11. Transcribed-but-unvoiced replies (live lab at c55898fb)

**Evidence.** The owner said "Remember that my car is a Suzuki Jimny."
`remember_memory` committed once and the turn was saved. Gemini's tool
follow-up "Understood, I've noted that." was committed as a transcript, but:
- output audio tokens were 0;
- no playback segment started (no started or finished event);
- the response gate withheld nothing;
- silent-audio recovery logged "could not correlate … with completed playback
  quality".

The session then timed out in silence.

**Root cause.** No PCM for that follow-up ever reached the output: Gemini
returned the turn as transcript only. Jarvis had no recovery for that case.
`SilentRealtimeAudioRecovery` only replays completed near-silent segments, and
it deliberately gives up when no segment exists. So any transcript-only reply
ended in silence. The project context gate was not involved.

Checked and ruled out:
- the provider "input_speech_started" that Gemini's automatic follow-up emits
  cannot start a new user activity (Jarvis runs explicit local VAD);
- the plugin opens a fresh generation for the follow-up.

Why Gemini voiced nothing is not visible from Jarvis.

Latent defect found alongside: an unplayed reply could be attributed to the
previous utterance (stale `response_epoch`). Fixed.

**Fix (only when project memory is active; flag-off behaviour unchanged):**
- **Detecting it:** a committed, uninterrupted assistant turn with no playback
  segment started within 1.5 s (`started_segment_sequence`) counts as unvoiced.
- **Replay:** its exact text is replayed **once** through the existing scripted
  TTS lane, but only if the project response gate approves it, using the same
  decision as for audio. A reply the gate withheld, or one made stale because
  the owner spoke again, is never replayed.
- **Saving:** the replayed reply is saved once.
- **Nothing repeated:** Gemini is never asked again, so no tool runs twice and
  nothing is spoken twice.
- **TTS failure:** if scripted TTS fails, one generated "say exactly" fallback
  is used.
- **Diagnostics:** they now record every `speech_created` event (source,
  user-initiated), so an unvoiced follow-up is visible per utterance. The
  `unplayed_replays` counter counts replays.

**Remaining:** a Gemini-side cause for transcript-only tool follow-ups is
outside Jarvis. The replay uses the TTS voice, not Gemini's.

## 12. Live qualification failures at 8155df0d (run 20261103T100642Z-20dd6e)

Graded result was Q1 PASS, Q2 FAIL (`partial_forget:history_only`), Q3 PASS,
Q4 FAIL (`renewed_wake_saved_nothing`), Q5 PASS. Two of those verdicts were
wrong, and the run exposed two runtime defects. Root causes come from the lab
log, the sealed diagnostics and the LiveKit 1.8.3 / Gemini plugin source.

### FIX 1 — internal Gemini text reached scripted TTS

**Evidence.** In the first wake after the Hello renewal (10:16:12Z) the wake
acknowledgement came back as a text-only transcript: "Neither claim that a
greeting is required nor describe its purpose. Thinking Process: 1.
**Analyze the context:** The user's prompt is a "[Project memory from Jarvis
...]" block ...". No audio played; recovery logged `replay=scripted_tts`.
At 09:55Z another acknowledgement was transcribed as "Do not offer help or ask
a question." (a paraphrase of Jarvis's own prompt).

**Root causes.**
1. *Open context turn.* The session preload was injected as a lone user-role
   chat item; LiveKit syncs it with `turn_complete=False`. The acknowledgement's
   `generate_reply` then made Gemini treat the memory block as the owner's
   prompt, and it reasoned about it in text.
2. *Instructions are MODEL-role text.* The Gemini plugin sends
   `generate_reply(instructions=...)` as a `role="model"` content turn, so
   Gemini can continue or paraphrase it as if it were its own reply.
3. *No ownership check before replay.* `allow_unplayed_reply` allowed epoch 0
   (no owner speech yet), so a system generation was treated as an unvoiced
   reply. A transcript alone was taken as evidence that replay was safe.

**Fix.**
- Context (preload and repair delivery) is injected as a **completed
  exchange**: the labelled memory message plus a Jarvis "Noted." item, both
  registered with the bridge so neither becomes a turn. Context is never put in
  `generate_reply` instructions.
- **Ownership/lifecycle** (`VoiceProjectTurns.allow_unplayed_reply`): a text-only
  turn is replayed only if it answers an accepted owner utterance of the
  current activity epoch (never epoch 0), that utterance has not already been
  answered audibly, it is not a forget confirmation, the context gate would
  have allowed it, and its text is user-facing. Each rejection is a
  diagnostics event with its reason.
- **Content boundary** (`voice_output_safety.py`), applied to both recovery
  paths (also with project memory OFF) and to saving assistant turns:
  registered prompt/instruction text echoed (shingle overlap or a dozen
  quoted words), internal markers, reasoning-trace structure (a labelled
  section or several bold analysis steps) and over-long text are never spoken
  or saved. It is a second line, not the primary protection.

### FIX 2 — wake acknowledgement race

**Root cause.** When owner speech began right after the acknowledgement was
requested, its `generate_reply` was still pending; the plugin binds the next
generation to a pending future, so the owner's own response could be consumed
by it ("generate_reply timed out waiting for generation_created"). The runtime
also logged "finished playing" for an acknowledgement that produced no audio.

**Fix** (`runtime._run_one_session_owned`): if owner speech arrives before the
acknowledgement produced audio, only the acknowledgement's own SpeechHandle is
interrupted (LiveKit cancels its pending generation; the plugin's interrupt is
a guarded `activity_start`, a no-op while the owner speaks). Once its audio
plays, provider-native barge-in still owns interruption (no session
interrupt). Playback is logged as played only when a new output segment
started; otherwise "produced no audio; not reported as played". Recovery never
replays it (FIX 1).

### FIX 3 — Q2 forgetting grader, and forget ordering

- The grader took the **first** `forget_memory` attempt (a failed predicate
  guess) and ignored the committed third. It now grades all attempts within the
  latest forget utterance; earlier requests never count as evidence. It
  requires both stores, checks that no confirmation played before both were
  done, checks later sessions' context for the words, and checks later replies
  only for forgotten words the owner did not say in that session (the live
  "car" was the owner's own question word).
- **Why three attempts.** With personal context off (lab), canonical forget
  keeps the legacy exact-predicate rule: Gemini must name the stored key and
  guessed `car` and `suzuki_jimny` first. Each miss is a side-effect-free
  ToolError. This is the canonical memory's own security boundary and is not
  changed here; production APPLY selects the target from the catalog instead.
- **Premature confirmation.** After a canonical forget, no confirmation audio
  may play until the saved conversation is also forgotten (the response is
  interrupted and Gemini is asked once to call `forget_saved_history`). If it
  is not done within 12 s (`FORGET_HISTORY_SECONDS`) Jarvis says honestly: "I
  removed the saved fact, but I could not remove it from our saved
  conversation yet. Please ask me to forget it again." The two deletions are
  not atomic and are never reported as one success when only one happened.
- **2 owner / 13 Jarvis rows.** Owner rows are removed only if they contain
  all the words (the fact and the forget request). Every Jarvis reply generated
  with a removed row in its context is removed too, by design, since it may
  paraphrase it. Because the preload puts recent rows in every reply's
  context, this includes Jarvis replies on other topics (hotel, packing). The
  owner's own hotel/packing statements are kept (test
  `test_forget_keeps_unrelated_owner_history_and_says_what_else_went`).
  Narrowing this is an owner decision (it trades privacy for retention).

### FIX 4 — Hands `open_app` unavailable; Q3 false PASS

- **Cause.** Hands resolves the Microsoft `winapp` CLI from `PATH`. Production
  starts through `Set-JarvisStorage.ps1`, which puts `<state>\tools\winapp` on
  PATH; the lab process never did, so `open_app` returned
  `status=unavailable` (ok=False, verified=False). The lab now prepends the
  installed profile's managed winapp directory to its own PATH when `winapp`
  is not already resolvable (`project_voice_lab.managed_tool_path`). Policy,
  tool selection and execution are unchanged.
- **Grader.** LiveKit hands the tool result to observers as `str(dict)`, not
  JSON, so diagnostics never parsed it and the grader saw only `is_error=False`.
  Diagnostics now parse it (`ast.literal_eval`, never evaluated as code) and
  record `ok`, `status` and Hands' `verified` postcondition. Q3 reports
  invocation, execution and verification separately: Hands passes only with
  `ok`, `succeeded` and `verified=True`; research only when a search ran and
  returned evidence.

### FIX 5 — renewal, then the first command

**Evidence.** The renewal was approved after 2.9 s, before the session started;
then the session ran 8 s with no owner speech at all (no VAD activity,
`canonical_user_turns=0`) and ended on inactivity. So no command was lost
there: none was spoken in that wake. The design still could lose one: the old
`prepare_wake` blocked the session until approval, so speech during the Hello
prompt was never captured, and the 8 s inactivity timeout could end the wake
while the owner was still approving.

**Fix.** Section 8 (revised): the session starts at once, turns wait (bounded)
for the approval, the inactivity timeout is held only for that bounded wait,
and a denied/late approval pauses that wake with one notice and nothing saved.
Hello security is unchanged: a fresh grant per continuity change, never
extended or reused.

**Grader.** Q4 now finds the wake whose turns waited and reports: no speech
(NOT_RUN, incomplete), speech without transcript (REVIEW), recognised but not
accepted / captured but not saved / saved twice / no audible reply (FAIL),
paused notice with nothing saved (REVIEW).

### FIX 6 — whole grader review

Q1 now requires the audible reply to use a distinctive word of a row found
outside the preload. Q5 fails when internal text may have been spoken or an
accepted request got no audible reply, and asks for review when speech had no
transcript. The full rules are in the grader's module docstring.

### FIX 7 — preserved

Flag OFF: unchanged except that the existing near-silent replay refuses
non-user-facing text. Canonical personal memory, learning APPLY, Gemini paid
fallback/handoff, Exa research, Hello, wake word, standby and barge-in paths
are not modified. Full coexistence of project memory with personal-context
APPLY remains a separate integration requirement and is not claimed here.

### Still needs a physical Windows run

Native audio of the acknowledgement race, the Hello prompt timing with real
speech, Hands actually opening Notepad/Brave with the managed winapp, and
whether Gemini still produces text-only system generations after the
closed-context change. Automated tests cannot show these.


## 13. Qualification at 1b13dfb8 (run 20261103T115032Z-bc3e16)

Grades: Q1 FAIL `search_found_nothing`, Q2 FAIL
`resurfaced_in_context:hotel,kathmandu`, Q3 NOT_RUN (Hands not attempted;
research PASS), Q4 NOT_RUN (no lock/unlock), Q5 PASS.

- **Q2 was a false FAIL.** Both stores committed (`forget_memory` once,
  `forget_saved_history` with 2 owner and 6 Jarvis rows). The next wake's
  search found nothing and the reply said it had no hotel. The forget words
  were `and, hotel, kathmandu, yak, yeti`. The grader called ANY one of them in
  later context a leak, but the surviving owner rows legitimately say "hotel"
  and "Kathmandu" (the earlier question and the weather request). Now a leak
  is a later row holding all the words, or any *distinctive* word. Words are
  generic if they are function words or appear in the owner's other
  utterances of the run that do not restate the fact. A real resurfacing
  ("Yeti lodge", or a reply saying "Yak and Yeti" unprompted) still fails.
- **Q1 did not test the archive.** Only six owner rows were saved before the
  question, so the hotel fact was inside the session preload (≤12 rows). The
  answer came from the preload, and search, which never resends rows the model
  already has, correctly found nothing new. Search works as designed; the setup
  needs 13+ newer owner rows. The grader now reports this as NOT_RUN
  `fact_was_in_the_preload_not_an_archive_search`. A new end-to-end test
  pushes a distinctive fact out of the preload, searches the real archive, and
  grades the real diagnostics record PASS
  (`test_project_voice_archive_qualification.py`).
- **Wake acknowledgement transcript.** The ack's transcript was the wake-ack
  instructions verbatim followed by "Standing by.". The audio was 1.17 s,
  which is "Standing by." only: the instruction text (about 60 words) was
  never spoken. Gemini transcribes the generate_reply instructions, which
  LiveKit sends as model-role text, as the start of its own turn. The bridge
  now removes any registered instruction text quoted verbatim in an assistant
  transcript before it becomes a turn, log line, diagnostics record or saved
  history; a transcript that is only instruction text is dropped. Q5 now fails
  if a wake acknowledgement's transcript still holds internal text. The prompt
  registry loads itself, so the standalone grader checks the same texts.
