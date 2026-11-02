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

Tests discover every `function_tool` declared in `jarvis/voice` from source (50
today) and check that only the allowlisted ids survive. This was the regression
at `757ea68e`: in baseline mode "Create project called Nepal trip" reached
Hands, which tried `make_directory`.

## 4. Measurements

The lab writes `voice-usage.jsonl` (content-free), with one row per wake session:

- `latency_ms`: end of owner speech → Jarvis starts speaking
- `responses`: Gemini response count
- `tokens`: Gemini Live realtime usage (input/output/total, audio/text input)
- `tool_calls`: tool calls by name
- `disallowed_tool_calls`: must be 0

On shutdown, `voice-lab.jsonl` also records `Voice project memory summary`:
prepared/clarified/not-saved counts, unprepared turns, `prepare_ms`,
`context_tokens`, and recorded/skipped replies. Each session also logs
`Session tools restricted | exposed=[…]`.

## 5. Windows acceptance (isolated; production untouched)

Use a **new** lab root; existing lab folders are not reused or changed. Use
fictional details only. The voice and text labs share this one lab root at the
same commit. Only one of them runs at a time, because both take the lab lock.

```powershell
git -C E:\Jarvis\App fetch origin feat/voice-project-memory-integration
$Commit = "<commit under test>"
$Lab = "$env:TEMP\jarvis-voice-project-2"   # must not exist yet
git -C E:\Jarvis\App show "${Commit}:tools/windows/Start-JarvisProjectVoiceLab.ps1" | Set-Content "$env:TEMP\Start-VoiceLab.ps1"
git -C E:\Jarvis\App show "${Commit}:tools/windows/Start-JarvisProjectMemoryLab.ps1" | Set-Content "$env:TEMP\Start-TextLab.ps1"
$Log = "$Lab\profile\voice-lab.jsonl"; $Usage = "$Lab\profile\voice-usage.jsonl"
```

**Neutral script N.** Used in both modes for the latency and token comparison.
It has no project or action words. Wake Jarvis, say each line and wait for the
reply:

1. "What is the capital of Nepal?"
2. "Explain what a monsoon is in one sentence."
3. "Suggest a name for a pet goldfish."
4. "What is seven times eight?"
5. "Tell me one short fact about mountains."

**Project script P.** Project memory mode only:

1. "Create project called Nepal trip."
2. "We will take the Jimny and the permits are sorted."
3. "Create project called interview preparation."
4. "My interview topic is SQL window functions."
5. "What's the status of my Nepal trip?"

**A. Baseline (project memory off).**
`& "$env:TEMP\Start-VoiceLab.ps1" -Commit $Commit -LabRoot $Lab -Baseline`.

At startup, expect:
- `Isolated memory: …\profile\memory.db` inside `$Lab`
- `Tools Gemini can call: enter_standby`
- no Hello prompt for project history

Say script N, then press Ctrl+C. Check:

```powershell
Select-String $Log -Pattern "Session tools restricted" | Select-Object -Last 1   # exposed=['enter_standby']
Select-String $Log -Pattern "use_computer|computer_action|Hands|make_directory"  # expect no output
Get-Content $Usage | Select-Object -Last 1   # disallowed_tool_calls 0; tool_calls {} (or enter_standby only)
```

**B. Project memory.** `& "$env:TEMP\Start-VoiceLab.ps1" -Commit $Commit -LabRoot $Lab -ResumeLab`.
Expect `Tools Gemini can call: enter_standby, prepare_project_turn`. Approve
Hello. Say script N, then script P. Expect:
- N1: "Created project General." Ordinary conversation goes to the default General workspace (the #305 rule). N2–N5 add no announcement.
- P1 and P3: "Created project Nepal trip." and "Created project interview preparation."
- P5: the Jimny and permits, attributed to Nepal trip, with no "switched" or "created" claim
- "Switch to Tokyo": Jarvis says there is no such project and creates nothing
- Barge-in: interrupt a long answer by speaking. Jarvis stops, and your next question is answered normally.

Press Ctrl+C, then check:

```powershell
Select-String $Log -Pattern "Session tools restricted" | Select-Object -Last 1   # enter_standby, prepare_project_turn
Select-String $Log -Pattern "use_computer|computer_action|Hands|make_directory"  # expect no output
Get-Content $Usage | Select-Object -Last 1   # tool_calls.prepare_project_turn close to user_turns; disallowed_tool_calls 0
Select-String $Log -Pattern "Voice project memory summary" | Select-Object -Last 1   # unprepared_user_turns, prepared
```

**C. Restart.** Run the step B command again. Approve Hello.
- "Where were we?" → "Resuming interview preparation."
- "Switch to Nepal trip" → "Switched to Nepal trip."
- "Which vehicle are we taking?" → Jimny

Ctrl+C.

**D. Check and forget in the text lab.**
`& "$env:TEMP\Start-TextLab.ps1" -Commit $Commit -Model "gemini-3.5-flash-lite" -LabRoot $Lab -ResumeLab`.
`/projects` lists exactly **three** projects: General (script N), Nepal trip and interview preparation. There is no duplicate, such as a second "nepal trip".
`switch to interview preparation` → `/forget` (approve Hello) → `/quit`.

**E. Voice after forget.** Run the step B command again.
- "What is my interview topic?" → Jarvis does not know it.
- "Which vehicle are we taking?" → Jimny.

Ctrl+C.

**F. Compare and report.** From `voice-usage.jsonl`, compare the baseline row with
the script-N part of step B. Report:
- median and max latency, and tokens
- `prepare_project_turn` calls against `user_turns`
- `disallowed_tool_calls` (must be 0)
- the `unprepared_user_turns` value from the summary line

Also confirm that the Hands search returned nothing in every step.

## 6. Known limitations (milestone 1)

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
