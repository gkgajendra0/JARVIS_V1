# Project memory in native voice — milestone 1 (isolated, opt-in)

Status: **lab only, disabled by default.** Normal `jarvis.voice.production_runtime`
never enables it; only `jarvis.voice.project_voice_lab` does, against an isolated
lab profile. Built on PR #305 (`92b93c4b`).

## 1. Boundary

Gemini Live generates replies directly from audio and cannot be forced to call
a tool: the plugin maps any `tool_choice` other than auto/none to auto. So the
integration enforces "capture → context → answer" itself:

| Step | Where | What happens |
| --- | --- | --- |
| 1 | `LiveKitConversationBridge` (unchanged) | Final transcript → canonical USER turn (deduplicated by item id/generation). |
| 2 | `VoiceProjectTurns.observe_turn` → application task | **Every accepted USER turn is routed and durably saved at once**, serialized across sessions, whether or not Gemini ever calls the tool. It is not cancelled by a newer utterance or by the wake session ending. Uses the tested `ProjectConversationCoordinator`. |
| 3 | `prepare_project_turn` (no arguments; BLOCKING) | Gemini calls it first. It waits ≤3 s for the committed transcript and returns step 2's result as compact, new-only history plus `action`, `announcement` and `previous_project`. The realtime model is set to **BLOCKING** tool behaviour: LiveKit otherwise declares Gemini 3.8 Live tools NON_BLOCKING, so the model could answer before the result arrived. |
| 4 | `ProjectAudioGate` (session audio output) | Decided once per response segment. A segment plays only if Gemini received this utterance's result. Otherwise it is interrupted before any audio is heard, and Gemini is asked once to call the tool. If that also fails, one fixed fallback is spoken: "couldn't load the project memory; please say it again". Each utterance gets exactly one spoken answer. |
| 5 | Bridge accepted ASSISTANT turn → `observe_turn` | Recorded only for a delivered request. Its evidence is **every source delivered in this Gemini session**, since the model may restate any of them; forget therefore removes it too. |

Nothing here produces an answer in parallel with the model. The only model
request the integration makes is the bounded re-request or fallback for a
withheld response.

Reused unchanged: SQLCipher/DPAPI store, `ConversationHistoryAuthority` (Windows
Hello grant), source clearance (`standard_history_source`), retention pause,
forget with provenance, routing (questions never switch or create projects).

## 2. Failure handling

| Situation | Behaviour |
| --- | --- |
| Gemini answers without calling the tool | The turn is already saved. The answer is withheld unheard; one re-request; then one fallback. Counted as `unprepared_responses_blocked`, `repairs`, `fallbacks`. |
| Consecutive utterances, tool called once | Both utterances are saved, in order. The tool returns the latest. |
| Local VAD misses an utterance's start | Gated per utterance, not only per activity epoch. |
| Tool called before the transcript | Waits for the committed transcript; never uses the model's wording. |
| Owner speaks again (barge-in) | Pending tool or re-request is dropped; the new utterance is handled normally. |
| Interrupted reply | Recorded as `partial` with the transcribed prefix. |
| No transcript at all | Answer withheld; "Sorry, I didn't catch that." Nothing saved. |
| Tool cancelled by Gemini | Turn still saved; next call works. |
| Duplicate tool call / item events | Same result; one record. |
| Gemini fails to answer | User turn saved; no reply recorded; next turn normal. |
| Excluded content (e.g. salary) | `not_saved`; omission marker only; no history given. |
| Clarification ("switch to tokyo") | Question returned verbatim; nothing created; reply not attributed. |
| Project switch | Result says `action: switched` and `previous_project`, so the model cannot claim the owner was already there. |
| Command after a lead-in ("Okay. Create a project called …", "Hey Jarvis, switch to …") | A closed set of lead-ins is removed at the start only, then the normal anchored command rules apply. |
| Command after real content ("It went well. Create a project called Goa.") | Clarification: nothing changes until the owner says the command alone. |
| Reply claims a create or switch the application did not commit | Detected on the committed reply. It is not saved, and a fixed correction is spoken ("Correction: no project was created or switched. You are in X."). Every result also carries `project_changed` and, if false, a "nothing changed" note. Audio already played cannot be withdrawn; the correction follows immediately. |
| Wake session ends / shutdown | In-flight saves and committed replies finish before memory closes; grant revoked. |
| Restart | New Hello grant; first turn says "Resuming X."; everything saved is available. |

## 3. Tool isolation (enforced in code)

Both lab modes expose an exact tool allowlist to Gemini. `restrict_tools`
enforces it in `VoiceRuntimeController`, at the single point where a session's
tools are handed to the realtime agent; the Gemini handoff copies that agent's
tools. A withheld tool is never declared to the model, so it cannot be called,
whatever the prompt says.

| Mode | Tools Gemini can call |
| --- | --- |
| `-Baseline` | `enter_standby` |
| project memory | `enter_standby`, `prepare_project_turn` |

Withheld in both modes:
- Hands, desktop and file control (`use_computer`, `computer_action`, `control_computer`)
- local reads and self-awareness
- capability acquisition, engineering and background work
- web research and vision
- canonical-memory tools (`remember_memory` and the rest)
- personal context and topic tools

The internal authority services keep running, because SQLCipher and Windows
Hello need them. Normal Jarvis passes no allowlist and is unchanged.

Tests discover every `function_tool` declared in `jarvis/voice` from source and
check that only the allowlisted ids survive.

## 4. Measurements and token usage

`voice-usage.jsonl` (content-free) has one row per wake session:
- `latency_ms`: end of owner speech → Jarvis starts speaking
- `responses`: Gemini response count
- `tool_calls`: by name
- `disallowed_tool_calls`: must be 0
- `tokens`: `input`, `input_audio`, `input_text`, `input_cached`, `output`, `output_audio`
- `input_per_response`: `values`, `first`, `peak`

Token figures now come from LiveKit's `session_usage_updated`. `metrics_collected`
is deprecated in LiveKit 1.8 and is no longer used.

**How to read the totals.** Gemini Live reports each response's prompt as the
whole session context so far: audio, transcripts and tool results. So the summed
`input` grows roughly quadratically with the number of turns in one wake
session. The earlier 90,848 figure was such a sum. It is input processed across
responses, not unique text, and not a statement of billed text tokens.
`input_per_response` shows the growth directly, and `input_audio` against
`input_text` shows what dominates.

**Inefficiency fixed.** Each tool result used to resend the full project packet,
about 5.4 KB of JSON including IDs, revisions and an omitted-ID list. Every
copy then stayed in Gemini's context. Results now carry only history rows not
yet delivered in this Gemini session, without machine fields. In a ten-turn
project, five questions in a fresh wake session send 5.9 KB instead of 27.0 KB
of tool results, 78% less, and every later prompt shrinks with it.

`voice-lab.jsonl` → `Voice project memory summary` (on shutdown) reports:
- `user_turns`, `saved_user_turns`, `delivered`, `undelivered_user_turns`
- `unprepared_responses_blocked`, `repairs`, `fallbacks`
- `clarifications`, `not_saved`, `failed`
- `assistant_recorded`, `assistant_skipped`
- `prepare_ms`, `packet_bytes`, `delivered_bytes`

## 5. Voice diagnostics (lab only, explicitly enabled)

`-RecordDiagnostics` on the voice lab launcher records each owner utterance end
to end, so acceptance no longer depends on remembering what was said. Without
the switch nothing extra is recorded, and normal Jarvis has no path to it.

| Per utterance (one correlation ID `run/session/utterance`) | Source |
| --- | --- |
| Microphone audio, replayable: what Jarvis forwarded to Gemini after the wake word, plus 0.5 s pre-roll | the session audio tap (`ObservedSessionAudioInput`) |
| Speech start and end, including speech that never became a transcript | LiveKit local VAD `user_state_changed` |
| Raw recognition, partial and final | Gemini `user_input_transcribed` |
| Accepted canonical transcript, matched by activity epoch | `LiveKitConversationBridge` accepted USER turn |
| Routing: status, action, project, previous project, references, announcement, clarification | `VoiceProjectTurns` |
| Saved text, read back from the encrypted store, and its receipt (event, sequence, revision) | `ProjectArchiveAccess.snapshot` |
| Delivery to the model, played or withheld answer, repair, fallback | `VoiceProjectTurns` and the audio gate |
| Jarvis's reply text, complete or interrupted; tool calls; latency; errors | bridge and session events |

**Flags** in the report:
- `no_accepted_transcript` (speech without a transcript)
- `final_recognition_differs_from_accepted`
- `SAVED_TEXT_DIFFERS`
- `duplicate_recognition_event` and `duplicate_turn_event`
- `several_transcripts_for_one_utterance`
- `project_created: X` and `project_switched: X`
- `audio_not_kept_run_limit`

Events that cannot be tied to an utterance are kept as "unmatched" and counted.

**Utterances, not VAD segments.** LiveKit's local VAD ends a segment after
about 0.55 s of silence, while Gemini ends a user turn only after 800 ms. A
short pause mid-request ("Okay. … Create a project called …") therefore gave
two VAD segments but one transcript. At `73b1b4d6` that transcript attached to
the second segment only: the first looked like a dropped request, and the
recording missed the beginning. That is the likely cause of the
15-segments / 11-turns gap in run `3edaf5`, to be confirmed against that
report with this build.

Now a segment starting within **1.2 s** of the previous one ends, with no Jarvis
reply in between, belongs to the same **utterance**. Its audio is recorded
continuously across the pause, plus a short tail, and a transcript matches
any of the utterance's activity epochs. The report shows
"N speech segments, one utterance".

Speech that still has no transcript is classified from evidence and never
called "dropped":
- `recognised_but_not_accepted`: Gemini produced text, but no turn was accepted
- `during_jarvis_reply_echo_or_barge_in`
- `very_short_segment`: under 0.4 s
- `no_recognition_listen_to_audio`

**Automated acceptance.** `-DiagnosticsReport` also writes `acceptance.json`
(schema `jarvis-voice-acceptance-v1`) and prints the overall verdict and any
FAIL rows.

| Verdict | Codes |
| --- | --- |
| **FAIL** (deterministic contradiction) | `command_misrouted` (a project command routed elsewhere); `unexpected_project_change` (created or switched without a command); `false_project_claim` (the reply claims a change that wasn't committed); `save_mismatch`, `save_failed`, `save_read_back_failed`, `accepted_turn_not_prepared`; `withheld_answer_not_recovered` |
| **REVIEW** (listen to the audio) | `unmatched_speech:<reason>`; `context_gate_recovered`, `context_gate_fallback`; `correction_spoken`; `clarification_asked`; `embedded_project_command`; `not_saved:<reason>`; `recognition_differs_from_accepted`; `duplicate_events`; `several_transcripts_for_one_utterance` |
| **Run checks** | `interruption_not_exercised`, `interruption_not_followed_by_answer`, `uncorrelated_events:N` |

The run verdict is FAIL if any utterance fails, REVIEW if anything needs review,
otherwise PASS.

**Recognition is not ground truth.** The report labels recognised and accepted
text as Gemini's recognition. The audio next to it is the reference.

**Privacy and storage**
- Every file is DPAPI-sealed for the current Windows user (purpose
  `jarvis-voice-diagnostics-v1`). They are stored inside the isolated lab, under
  `profile\voice-diagnostics\runs\<run>`.
- No new provider: the audio is what Gemini Live already receives, and nothing
  is uploaded.
- Retention: runs older than 7 days, and all but the last 5, are deleted at
  each lab start.
- Bounds: 30 s of audio per utterance, 150 MB per run, 300 utterances per run.
- `-DiagnosticsReport` decrypts the latest run into a local `report.html` and
  opens it. The audio is embedded in the page. This plaintext copy is deleted at
  the next lab start.
- `-CleanupDiagnostics` deletes all diagnostics and reports for the lab.
- The memory database, its key and the history authority are unchanged.

## 6. Windows acceptance (isolated; production untouched)

Use a **new** lab root. Existing lab folders, including your owner test lab
and its saved history, are not reused or changed. Use fictional details only.
The voice and text labs share this one lab root at the same commit. Only one of
them runs at a time, because both take the lab lock.

```powershell
git -C E:\Jarvis\App fetch origin feat/voice-project-memory-integration
$Commit = "<commit under test>"
$Lab = "$env:TEMP\jarvis-voice-project-5"   # must not exist yet
git -C E:\Jarvis\App show "${Commit}:tools/windows/Start-JarvisProjectVoiceLab.ps1" | Set-Content "$env:TEMP\Start-VoiceLab.ps1"
git -C E:\Jarvis\App show "${Commit}:tools/windows/Start-JarvisProjectMemoryLab.ps1" | Set-Content "$env:TEMP\Start-TextLab.ps1"
$Log = "$Lab\profile\voice-lab.jsonl"; $Usage = "$Lab\profile\voice-usage.jsonl"
function Summary { (Select-String $Log -Pattern "Voice project memory summary" | Select-Object -Last 1).Line }
function Voice([switch]$Baseline, [switch]$Fresh) {
  $a = @{ Commit = $Commit; LabRoot = $Lab; RecordDiagnostics = $true }
  if ($Baseline) { $a.Baseline = $true }; if (-not $Fresh) { $a.ResumeLab = $true }
  & "$env:TEMP\Start-VoiceLab.ps1" @a
}
function Report { & "$env:TEMP\Start-VoiceLab.ps1" -Commit $Commit -LabRoot $Lab -DiagnosticsReport }
```

After **every** voice run below, run `Report`. It prints the acceptance verdict
and any FAIL rows, writes `acceptance.json`, and opens that run's report:
one row per utterance, with the audio player, recognised text, accepted
transcript, routing, saved text and receipt, Jarvis's reply, tools, latency and
flags. Check each row by listening, rather than from memory.

**Neutral script N** (both modes; for the latency and token comparison):

1. "What is the capital of Nepal?"
2. "Explain what a monsoon is in one sentence."
3. "Suggest a name for a pet goldfish."
4. "What is seven times eight?"
5. "Tell me one short fact about mountains."

**Project script P** (project memory only):

1. "Okay. Create project called Nepal trip." (deliberate lead-in)
2. "We will take the Jimny." — then **immediately**, without waiting for the reply: "And the permits are sorted." (consecutive turns)
3. "So, create project called interview preparation." Pause briefly after "So," to exercise a two-segment utterance.
4. "My interview topic is SQL window functions."
5. "What's the status of my Nepal trip?"
6. "Switch to Nepal trip."
7. Ask "Tell me everything we planned for the trip", and interrupt the answer by speaking: "Stop. Which vehicle?"

**A. Baseline.** `Voice -Baseline -Fresh`.

At startup, expect:
- `Isolated memory: …\profile\memory.db` inside `$Lab`
- `Tools Gemini can call: enter_standby`
- no project-history Hello
- `DIAGNOSTICS ON: …`

Say script N, then press Ctrl+C, then run `Report`. Each row's audio should match
its recognised text, and there are no project columns. Then check:

```powershell
Select-String $Log -Pattern "use_computer|computer_action|Hands|make_directory"   # expect no output
Get-Content $Usage | Select-Object -Last 1   # disallowed_tool_calls 0
```

**B. Project memory.** `Voice`.
Expect `Tools Gemini can call: enter_standby, prepare_project_turn`. Approve
Hello. Say script N, then script P. Expect:
- **N1:** "Created project General." This is the default workspace for ordinary conversation. No other N line has an announcement.
- **P1 / P3:** "Created project Nepal trip." / "Created project interview preparation."
- **P2:** both sentences are saved, even though they came back to back.
- **P5:** the Jimny and permits, attributed to Nepal trip. No switched or created claim, and you stay in interview preparation.
- **P6:** "Switched to Nepal trip." Jarvis must not say you were already in it.
- **P7:** Jarvis stops at once and answers "Jimny".
- **Throughout:** one spoken answer per utterance, and never a silent turn. If Jarvis says "couldn't load the project memory", note it: that is the fallback.

Press Ctrl+C, then run `Report`. **Expected acceptance:** no FAIL rows, and the
run verdict PASS or REVIEW. REVIEW is expected for any unmatched-speech or
recovered-gate rows; listen to each. Then for each utterance:
- **Audio against recognised text:** a misheard project name, for example
  "Naples" for "Nepal", is visible here.
- **Accepted against saved text:** they must match. `SAVED_TEXT_DIFFERS` must
  never appear.
- **P1 and P3:** despite "Okay." and "So, …", show `project_created`; P3 may show
  "2 speech segments, one utterance". P4 is saved under interview preparation.
- **Routing:**
  - only P1, P3 and P6 carry `project_created` or `project_switched`
  - P5 shows `continued · interview preparation · refs ['Nepal trip']`
  - P6 shows `(from interview preparation)`
- **P2:** two utterances, each with its own saved text.
- **P7:** the reply is marked `[interrupted]`, then the next row answers "Jimny".
- **Withheld or fallback:** rows show `withheld, played` and `repair_requested`
  or `fallback` if Gemini skipped the tool.
- **No transcript:** rows flagged `no_accepted_transcript` show speech that never
  became a transcript. Listen to them.

Then:

```powershell
Select-String $Log -Pattern "use_computer|computer_action|Hands|make_directory"   # expect no output
Summary   # saved_user_turns == user_turns minus clarifications/not_saved;
          # unprepared_responses_blocked, repairs, fallbacks: report the values
Get-Content $Usage | Select-Object -Last 1   # disallowed_tool_calls 0; input_per_response; tool_calls
```

**C. Restart.** `Voice`. Approve Hello.
- "Where were we?" → "Resuming Nepal trip."
- "Which vehicle are we taking, and are the permits sorted?" → Jimny; sorted. This confirms the step-P2 turns survived the restart.
- "What is my interview topic?" → SQL window functions, attributed to interview preparation.

Press Ctrl+C.

**D. Check and forget in the text lab.**
`& "$env:TEMP\Start-TextLab.ps1" -Commit $Commit -Model "gemini-3.5-flash-lite" -LabRoot $Lab -ResumeLab`.
- `/projects` lists exactly three projects: General, Nepal trip and interview preparation.
- Optionally `/inspect` in Nepal trip, to see both P2 sentences.
- `switch to interview preparation` → `/forget` (approve Hello). The preview names derived Nepal trip replies, including the step C answer that mentioned it.
- `/quit`.

**E. Voice after forget.** `Voice`.
- "What is my interview topic?" → Jarvis does not know it.
- "Which vehicle are we taking?" → Jimny.

Press Ctrl+C. Run `Report` after each of C and E as well.

**F. Report.**
- **Baseline against step B, script N:** median and max latency; per-response input (`input_per_response.first` and `peak`); `input_audio` against `input_text`.
- **The step B summary:** `user_turns`, `saved_user_turns`, `delivered`, `unprepared_responses_blocked`, `repairs`, `fallbacks`.
- **Whether any utterance:**
  - got two spoken answers
  - got no answer
  - got the fallback
- **The Hands search:** confirm it returned nothing in every step.
- **From the diagnostics reports:**
  - the printed acceptance verdict and `acceptance.json` for each run
  - any FAIL row, with its codes
  - each REVIEW reason, especially `unmatched_speech:*`
  - whether "speech segments" and "utterances" now differ only where pauses were grouped
  - any row whose audio and recognised text disagree
  - any `no_accepted_transcript` or `SAVED_TEXT_DIFFERS` row
  - any unexpected `project_created` or `project_switched`
- **When finished:** `& "$env:TEMP\Start-VoiceLab.ps1" -Commit $Commit -LabRoot $Lab -CleanupDiagnostics`
  deletes the recordings, or leave them to expire after 7 days.

## 7. Known limitations (milestone 1)

- **The answer's content is still the model's.** The integration guarantees that
  every eligible turn is saved, and that no answer is heard without that turn's
  context. It cannot make Gemini call the tool; when Gemini refuses twice, the
  owner hears the fallback.
- **A withheld answer costs latency.** It is generated, interrupted unheard and
  then re-requested, so expect roughly one extra response time. Step F measures
  this.
- **Clarification commands are not saved**, as in the text lab: for example
  "switch to tokyo" when no such project exists.
- **No project controls by voice yet.** /projects, /inspect, /pause, /forget and
  /repair work only in the text lab, between voice runs.
- **A false claim cannot be unspoken.** If Gemini claims a project change that
  wasn't committed, the claim is heard; it is corrected immediately, never
  saved, and reported as FAIL `false_project_claim`.
- **Diagnostics grouping is heuristic.** It groups segments separated by up to
  1.2 s with no Jarvis reply in between. Two separate requests spoken within
  1.2 s of each other appear as one utterance with two transcripts
  (`several_transcripts_for_one_utterance`, REVIEW).
- **Personal facts are not combined with project memory in voice.** The lab runs
  with personal context off.
- **Stored replies are Gemini's output transcription**, not the audio itself.
- **Paid fallback and Gemini handoff are disabled in the lab**, so the tool is
  not yet qualified across a mid-session model handoff.
