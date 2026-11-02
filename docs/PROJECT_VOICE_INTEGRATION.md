# Project memory in native voice — milestone 1 (isolated, opt-in)

Status: **lab only, disabled by default.** Normal `jarvis.voice.production_runtime`
never enables it; only `jarvis.voice.project_voice_lab` does, against an isolated
lab profile. Built on PR #305 (`92b93c4b`).

## 1. Boundary

Gemini Live generates replies directly from audio, so Jarvis cannot run the text
path's "capture → context → answer" sequence in front of the model. The only
synchronous point before the answer is a **blocking tool call**. This is the
pattern the existing `prepare_conversation_topic` already uses.

| Step | Where | What happens |
| --- | --- | --- |
| 1 | `LiveKitConversationBridge` (unchanged) | Final transcript → canonical USER turn (deduplicated by item id/generation). |
| 2 | `prepare_project_turn` tool (`project_voice.VoiceProjectTurns.prepare`) | Gemini calls it first. **No arguments.** It waits (≤3 s) for the USER turn of the current activity epoch, then runs the tested `ProjectConversationCoordinator.prepare_reply`: routing, history recording, provenance and context packet. It returns the packet, the committed action's announcement or a clarification. |
| 3 | Gemini Live | Speaks the answer from the tool result. |
| 4 | Bridge accepted ASSISTANT turn → `observe_turn` | Recorded with the packet's source IDs as evidence (same provenance as text), only if it follows the prepared USER turn with no newer USER turn in between. |

Nothing in this module produces an answer, so it cannot race the model or create
duplicate answers. The accepted-turn observer only schedules the recording of a
reply that Gemini has already committed.

Reused unchanged: SQLCipher/DPAPI store, `ConversationHistoryAuthority` (Windows
Hello grant), source clearance (`standard_history_source`), retention pause,
forget with provenance, routing (questions never switch or create projects).

## 2. Failure handling

| Situation | Behaviour |
| --- | --- |
| Tool called before the transcript | Waits for the committed transcript; never uses the model's wording. |
| Owner speaks again (barge-in) before the transcript | Tool returns `unavailable` at once; nothing recorded. |
| Interrupted reply | Recorded as `partial` with the transcribed prefix. |
| Tool cancelled by Gemini | No packet; next turn works. |
| Duplicate tool call / duplicate item events | Same result returned; one record. |
| Gemini fails to answer | User turn kept; no reply recorded; next turn normal. |
| Gemini answers without calling the tool | Nothing recorded for that turn; counted as `unprepared_user_turns`. |
| Excluded content (e.g. salary) | `not_saved`; no context; omission marker only. |
| Clarification ("switch to tokyo") | Question returned verbatim; nothing created; reply not attributed. |
| Wake session ends | Request invalidated; selection persists. |
| Shutdown | Pending reply recordings finish before memory closes; grant revoked. |
| Restart | New Hello grant; first turn says "Resuming X." |

## 3. Measurements

The lab writes `voice-usage.jsonl` (content-free), with one row per wake session:

- `latency_ms`: end of owner speech → Jarvis starts speaking
- `responses`: Gemini response count
- `tokens`: Gemini Live realtime usage (input/output/total, audio/text input)
- `tool_calls`: tool calls by name

On shutdown, `voice-lab.jsonl` also records `Voice project memory summary`:
prepared/clarified/not-saved counts, unprepared turns, `prepare_ms`,
`context_tokens`, and recorded/skipped replies. Run the same script with
`-Baseline` (project memory off, identical runtime) to compare.

## 4. Windows acceptance (isolated; production untouched)

Use fictional details only. The voice and text labs share one lab root at the
same commit. Only one of them runs at a time, because both take the lab lock.

```powershell
git -C E:\Jarvis\App fetch origin feat/voice-project-memory-integration
$Commit = "<commit under test>"
$Lab = "$env:TEMP\jarvis-voice-project-1"   # must not exist yet
git -C E:\Jarvis\App show "${Commit}:tools/windows/Start-JarvisProjectVoiceLab.ps1" | Set-Content "$env:TEMP\Start-VoiceLab.ps1"
git -C E:\Jarvis\App show "${Commit}:tools/windows/Start-JarvisProjectMemoryLab.ps1" | Set-Content "$env:TEMP\Start-TextLab.ps1"
```

Script used in steps A and B (wake Jarvis, say each line, and wait for the reply):

1. "Create project called Nepal trip."
2. "We will take the Jimny and the permits are sorted."
3. "Create project called interview preparation."
4. "My interview topic is SQL window functions."
5. "What's the status of my Nepal trip?"

**A. Baseline (project memory off).**
`& "$env:TEMP\Start-VoiceLab.ps1" -Commit $Commit -LabRoot $Lab -Baseline`.
The startup line shows `Isolated memory: …\profile\memory.db` inside `$Lab`.
Say the script, then press Ctrl+C. No Hello prompt for project history is
expected.

**B. Project memory.** `& "$env:TEMP\Start-VoiceLab.ps1" -Commit $Commit -LabRoot $Lab -ResumeLab`.
Approve Hello. Say the script. Expect:
- Lines 1 and 3: "Created project Nepal trip." / "Created project interview preparation."
- Line 5: the Jimny and permits, attributed to Nepal trip, with no "switched" or "created" claim.
- "Switch to Tokyo": Jarvis says there is no such project and creates nothing.
- Barge-in: interrupt a long answer by speaking. Jarvis stops, and your next question is answered normally.

Press Ctrl+C.

**C. Restart.** Run the step B command again. Approve Hello. "Where were we?" → "Resuming interview preparation."
"Switch to Nepal trip" → "Switched to Nepal trip." "Which vehicle are we taking?" → Jimny.
Ctrl+C.

**D. Check and forget in the text lab.**
`& "$env:TEMP\Start-TextLab.ps1" -Commit $Commit -Model "gemini-3.5-flash-lite" -LabRoot $Lab -ResumeLab`.
`/projects` lists exactly **two** projects: Nepal trip and interview preparation.
`switch to interview preparation` → `/forget` (approve Hello) → `/quit`.

**E. Voice after forget.** Run the step B command again. "What is my interview topic?" → Jarvis does not know it.
"Which vehicle are we taking?" → Jimny. Ctrl+C.

**F. Compare.** Report from `$Lab\profile\voice-usage.jsonl`, for the baseline row and the project rows:
- median and max latency
- tokens
- `tool_calls.prepare_project_turn` against `user_turns` (tool compliance)

From `voice-lab.jsonl`, report the `Voice project memory summary` line, especially `unprepared_user_turns`.

## 5. Known limitations (milestone 1)

- **Tool compliance is model-dependent.** If Gemini answers without calling the
  tool, that turn is neither answered from project memory nor recorded. It is
  counted, not enforced. An audio gate, holding speech until the tool ran, is
  the next step if compliance is poor.
- **No project controls by voice yet.** /projects, /inspect, /pause, /forget and
  /repair work only in the text lab, between voice runs.
- **Personal facts are not combined with project memory in voice.** The lab runs
  with personal context off.
- **Stored replies are Gemini's output transcription**, not the audio itself.
- **Paid fallback and Gemini handoff are disabled in the lab**, so the tool is
  not yet qualified across a mid-session model handoff.
- **Each prepared turn adds one tool round trip** plus up to the project
  context budget in tokens. Step F measures this.
