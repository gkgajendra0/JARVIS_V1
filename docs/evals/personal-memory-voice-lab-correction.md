# Personal memory voice lab correction (2026-11-27)

Base: `eaed348f3ec5b50f506afe9265bfa715afba803c`, branch
`claude/slice1-review-20261127` (PR #338). This change is lab tool exposure only.
It does not reopen the recorded Paid evaluation or authorize activation.

## Exposure and authority

| Lab mode | Additional personal tools |
| --- | --- |
| Baseline | None; `enter_standby` only |
| Project memory | None |
| PersonalContext | Existing personal read/topic tools only; automatic learning off |
| PersonalContext + PersonalLearning | Existing read/topic tools plus `memory_status`, `remember_memory`, `correct_memory`, `forget_memory`; automatic learning on |

The four ids are the production `MemoryAgentTools` function tools, assembled
by `_SessionToolBundle` in `canonical_active_speaker_runtime.py`. The allowlist
filters those original objects; there are no lab wrappers or alternate writes.
`inspect_memory` and `recall_memory` remain withheld. The usage meter and startup
listing receive the same mode-specific allowlist as the runtime.

Explicit mutations retain canonical latest-user intent, target/value grounding,
request-bound target resolution, fresh Windows Hello for the concrete mutation,
and authority validation inside the serial writer transaction. A learning-session
grant does not authorize an explicit write. The existing speaker book still
requires positive owner evidence for automatic learning with enforcement on.
`memory_status` reads recent in-process receipts, not arbitrary stored facts;
it waits for pending learning and returns the code-composed `say` sentence.
It does not itself perform speaker verification or fresh Hello.

## Isolated voice rerun

Stop the old voice/text lab with Ctrl+C first. Keep its entire root, marker,
source checkout, databases, console logs, diagnostics, and all Paid acceptance
files unchanged. A marker is commit-bound: do not resume the old `eaed348f` lab
on the correction, rewrite its marker, or use D17 recovery for this voice fix.
Use a fresh root and both launchers from the correction commit.

Run the following manually in PowerShell after publication. Replace the commit
placeholder with the full correction SHA reported in the handoff. Fetch changes
refs only; it does not switch or reset the installed checkout. `RepoRoot` uses
its existing `.venv` and machine configuration, while the launchers create an
exact-commit detached source checkout and isolated memory profile under the new
lab root.

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'E:\Jarvis\App'
$c = '<full-correction-commit-sha>'
git -C $repo fetch origin claude/slice1-review-20261127
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed' }
git -C $repo cat-file -e ($c + '^{commit}')
if ($LASTEXITCODE -ne 0) { throw 'Correction commit unavailable' }

$runId = $c.Substring(0, 8) + '-' + [guid]::NewGuid().ToString('N')
$scripts = Join-Path $env:TEMP ('jarvis-voice-launchers-' + $runId)
New-Item -ItemType Directory -Path $scripts -ErrorAction Stop | Out-Null
foreach ($name in @('Start-JarvisProjectMemoryLab.ps1', 'Start-JarvisProjectVoiceLab.ps1')) {
    $content = git -C $repo show ($c + ':tools/windows/' + $name)
    if ($LASTEXITCODE -ne 0) { throw "Cannot read pinned launcher $name" }
    $content | Set-Content -LiteralPath (Join-Path $scripts $name) -Encoding utf8
}
$lab = Join-Path 'E:\Jarvis\Temp' ('memory-v1-voice-gate-' + $runId)

& (Join-Path $scripts 'Start-JarvisProjectMemoryLab.ps1') `
    -RepoRoot $repo -Commit $c -Model gemini-3.5-flash-lite `
    -LabRoot $lab -SeedVoiceEval
# Seeding is fictional, needs Hello, and makes no model call.
# Continue only after successful seeding; keep the same $c and $lab.

& (Join-Path $scripts 'Start-JarvisProjectVoiceLab.ps1') `
    -RepoRoot $repo -Commit $c -LabRoot $lab -ResumeLab `
    -PersonalContext -PersonalLearning -SpeakerEvidence
```

The lab disables Paid fallback in code. Do not add `-Qualification` (it exposes
normal production tools), `-SpeakerEvidenceObserve` (no enforcement), or any
Paid acceptance flags. No live rerun is performed by this correction.

Check that startup lists all four added tools. Approve the startup history and
learning grants only in this isolated lab. Use fictional facts in a quiet room:

1. State a new fictional item naturally; wait for the owner score and learning
   completion. Ask whether it was saved: require a `memory_status` call and its
   exact `say` receipt, supported by a committed operation in the log.
2. Explicitly remember, correct, and forget a uniquely named fictional fact.
   Require a fresh concrete Hello approval for each mutation and the exact
   returned receipt; do not substitute an ordinary acknowledgement for proof.
3. Deny one concrete mutation approval; verify no committed change or success
   receipt. Check correction/forget residual state in the text lab only after
   stopping voice, using the same commit/root with `-ResumeLab`.
4. Test background/unknown/non-owner speech and personal/history read attempts
   separately. Record tool calls, speaker status, receipt/result, and the actual
   answer. A rejection by automatic learning alone is not a read-safety pass.

Retain `$lab\profile\voice-lab.jsonl`, `voice-usage.jsonl`, console output, and
owner grades as new evidence. Keep previous acceptance outcomes distinct.

## Separate authorization findings (unchanged)

These are confirmed source-level limitations, not proof that a particular live
background utterance disclosed data:

- `SpeakerTurnEvidenceBook.withholds` rejects only positively scored non-owner
  **later** turns. Unknown turns and the opening turn are admitted to project
  history under the existing history grant. `_prepare_turn` uses that predicate;
  the existing speaker regression explicitly asserts an unscorable command is
  saved. Owner-scored-only automatic learning therefore does not establish
  owner-only project-history admission.
- Project history is preloaded into the model session under its history grant
  without a positive speaker check. `search_history` also continues to archive
  access after a turn outcome is `not_saved` (including `speaker_not_owner`):
  it uses the outcome only to choose an excluded request id. This leaves a
  history-read risk inside an open granted wake.
- `PersonalContextSession` explicitly uses no speaker score. Reads use the
  existing session/question authority; receipt status reads recent session
  labels without a separate speaker/Hello check. An open session is not proof
  that the current speaker is the owner. Explicit mutations still require
  fresh Hello, and automatic learning retains its owner-evidence gate.

Do not certify unauthorized-read or background-history acceptance from this
allowlist fix. Resolving those limitations needs a separately approved change;
no authorization policy is redesigned here.

## Repairs after the aeb987b2 live acceptance (2026-11-28)

Live evidence (retained, unmodified):
`E:\Jarvis\Temp\memory-v1-voice-gate-aeb987b2-560b094b6e0749b2baea2b064b1c5cbe`.
Each issue below is accepted separately; local tests and CI are not live
acceptance.

### 1. A refused explicit correction committed through automatic learning

Recorded: session `48c472e1…`, turn `d6e0274b…`, "Okay. Correction. My diet
preference is vegetarian." `correct_memory` consent was refused at
17:48:14.295Z; automatic learning committed the same correction from the same
turn at 17:48:15.187Z.

Root cause: the explicit path (personal-context reservation, consent, commit
guard) and automatic learning (learning grant, child permit, writer
transaction) had no shared notion of "this request". The learning permit is
bound to the source turn but never consulted the explicit outcome, so a
refusal blocked only the explicit write.

Repair: before anything can fail, an explicit remember/correct/forget claims
its owner turn at the shared write boundary
(`MemoryService.claim_explicit_request` → `PersonalLearningAuthority`). From
then on, whether the explicit request is granted, denied, cancelled, expired
or fails, the learning authority refuses any learning child for a source whose
turn is, or whose context quotes, the claimed turn: on issue, before, and
inside the write transaction (under the broker lock, so a claim cannot land
between check and commit). The learning runtime also drops that turn's queued
or in-flight sources. To cover the opposite ordering (learning ready before the
tool is called), the voice runtime makes learning hold its write until the
reply to that turn is over (`ReplySettlement`: an assistant turn accepted
after it while the agent is back to listening, so a spoken "let me check"
before a tool step does not count; or a newer owner turn; or the end of the
session). An unsettled reply within the source budget writes nothing. Claiming
one turn never cancels learning in flight for another turn. Normal
owner-authorized learning commits after the reply.

Request binding (owner review of ad87660a): an explicit change acts for its
originating request, the owner turn bound by the first tool call of the reply
(target resolution), not whichever turn is latest when the mutation tool runs.
The binding holds until the agent is back to listening. If another utterance
is accepted between target resolution and the mutation call, the original
request is claimed (excluded from learning) and the change is refused before
any consent prompt; the owner repeats it. A newer owner turn no longer settles
an earlier one while its reply is still running.

Limit: a plain-text record left by the earlier
behaviour (for example `home_city` in the retained lab) stays outside the
learning read scope; a new explicit save creates the readable personal_fact
beside it.

### 2. Explicit save of "home city" could not be read back

Recorded: "Remember that my home city is Jaipur." → consent, commit, receipt
"Saved: home_city."; "What is my saved home city?" → "Nothing was saved from
that." (memory_status used as a fact answer); "What is my home city?" → "I don't
have a record".

Root cause: the explicit write stored a plain-text `home_city` record. In a
learning session, owner-memory reads see only registered personal-learning
records (`personal_learning_scope.record_scope`); a plain `home_city` record has
no registered scope, so it was invisible to reads and could not be targeted for
correction or deletion. memory_status receipts were also used to answer a
fact question.

Repair: in a session whose reads are learning-scoped, an explicit standard fact
outside the registered facets is stored as a `personal_fact` in the registered
shape (`MemoryService.remember_personal_fact`), with owner-explicit
provenance. It is in read scope, appears in the facet catalog, correction keeps
its shape (`correct_text` no longer flattens a registered record to plain
text), forgetting removes it, and the personal_fact suppression applies.
Sensitive facts and registered facets keep their existing paths; nothing is
added to an allowlist. Receipts name the fact in words ("Saved: home city.").
memory_status and its rule now say it reports recent changes only and never
answers what a stored fact is.

### 3. Owner-only admission and private reads (speaker enforcement on)

Repair: only positive owner evidence for the exact request turn acts for the
owner (`SpeakerTurnEvidenceBook.authorizes_owner` / `owner_verified`).
Unknown (short, unscored, timed out, session closed), non-owner, missing, stale
or another turn's evidence never does, opening turn or not. With enforcement on
but no speaker scores, an evidence object that authorizes nothing is used
(fail closed).

| Path | Now |
| --- | --- |
| Project history admission | Owner-scored turns only (opening included); others `not_saved` (`speaker_not_owner` / `speaker_unverified`) |
| Project history preload | Only after speech in this wake was scored as the owner; never on the wake word alone |
| `search_history`, `forget_history` | Denied (`speaker_not_verified`) before any archive access unless the request turn is owner-verified |
| Personal-context reads | Denied unless the bound request turn is owner-verified and still current |
| `memory_status` | An unverified speaker gets a fixed sentence that names no fact |
| `inspect_memory`, `recall_memory` | Denied for an unverified speaker |
| Automatic learning | Unchanged: owner-scored only; category controls wait for evidence |
| Explicit mutations | Unchanged: fresh Windows Hello for each concrete change |

Provider-preloaded data versus new reads: every new tool read is authorized
per request. What was already given to the live model in this wake (the
preload, history from a tool result, released personal facts, or a memory
receipt naming facts) cannot be withdrawn from that context, so (owner
decision 2026-11-28) once any of it was given, a request that cannot be
positively verified as the owner (non-owner, unknown or too short, evidence
timeout, or someone else barging in) ends and clears the wake: speech in
flight is interrupted and the session, with its model context, is closed
("Private wake ended | reason=speaker_not_verified" in the log). Private
context is given again only after fresh owner verification in a new wake. A
wake that released nothing private is not affected. Remaining window: speech
that already played between the start of a reply and the speaker verdict
(evidence is scored at the end of the utterance, normally before or around
the reply's start; at most the evidence wait of 1.5 s).

Changed behaviour the owner will notice: with enforcement on, very short
commands that cannot be scored (for example "Go back to sleep, Jarvis.") are
answered but not saved to project history, and give no private context; after
private context was given in a wake, such a command ends the wake.

### Fresh-lab acceptance checklist (each issue recorded separately)

1. Refused correction: save "My diet preference is vegan" (approve Hello);
   say "Okay. Correction. My diet preference is vegetarian." and refuse
   Hello; ask "What is my diet preference?" Pass: vegan; no learning commit
   for that turn in the log. Then one approved correction stores the new
   value.
2. Interloper between resolution and change: say the correction, and while
   Jarvis is still working, say "hmm" (or have another sound accepted).
   Pass: nothing changes, Jarvis asks to repeat; no learning commit for the
   correction turn.
3. Readback: "Remember that my home city is Jaipur." (approve) → "What is my
   home city?" answers Jaipur (not the save-status sentence).
4. Approved deletion: "Forget my home city." (approve Hello) → "What is my
   home city?" says no record.
5. Denied deletion: save it again, "Forget my home city." and refuse Hello →
   it is still Jaipur; no learning change for that turn.
6. Restart persistence: close the lab, start it again with -ResumeLab on the
   same lab root; ask the diet preference and home city: the approved values
   are still there, refused changes are not.
7. Speaker gating: another person or a phone clip asks "What vehicles do I
   have?" and "Which hotel did we book?" in a fresh wake → reads denied
   (speaker_not_verified), no facts spoken; the owner gets answers.
8. Same-wake speaker switch: the owner asks a private question and gets the
   answer; then another person asks a private follow-up in the same wake.
   Pass: speech stops, "Private wake ended | reason=speaker_not_verified"
   is logged, nothing private is spoken to them; the owner must wake Jarvis
   again and is verified before private context is given again. Repeat with
   the other person barging in while Jarvis is answering, and with a very
   short unscored command after a private answer.
9. Ordinary conversation: in a wake with nothing private, another person's
   general question ("What's the capital of Nepal?") is answered and the wake
   continues.
