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
