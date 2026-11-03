# Project memory (#303–#308) — final release gate

Gate run against `feat/project-memory-forget-recall-renewal` (PR #308, which
contains #303 → #305 → #306 → #307 → #308; #304 is archived and not part of
the release). `main` has not moved since the stack branched (`488954a6`). The
installed build (`E:\Jarvis\App` at `1a4f24be`) has the same `src/` as `main`:
it differs only in docs and two test fixtures, checked file by file.

## Decision

| Question | Answer |
| --- | --- |
| Merge with project memory **OFF**? | **Merge-ready after the owner's approval**, subject to the procedure below: backup, migration rehearsal, then merge in stack order. |
| Activate project memory in production? | **With the coexistence PR (stacked on #308): technically ready, pending owner approval and the first live activation smoke.** B2/B3 are resolved without disabling paid fallback or personal context/learning APPLY (`PROJECT_MEMORY_COEXISTENCE.md`). Without that PR, activation stays blocked. |

## What merging changes even with the flag OFF

These parts of the stack are active in ordinary voice. Every other project-memory
code path returns early when the flag is off.

1. **Schema migrations 4–7** run on the first start of the merged build. They
   add the topic-checkpoint, project-conversation, search (FTS5) and provenance
   tables, and they are one-way for older builds (B5). Rehearse first (below).
2. **Wake-acknowledgement safety** (#308): owner speech before the ack produced
   audio cancels only the ack. An ack is not logged as played without audio.
3. **Output safety** (#308): Jarvis's own instruction text, internal markers,
   reasoning and meta-narration never become an assistant turn, a log line or
   history. A generation that turns into internal text has its speech stopped
   while streaming. The near-silent replay refuses such text.
4. **Topic continuity** code (#303) is present but disabled (no factory).

Items 2 and 3 apply to the owner's real configuration (personal context APPLY
plus paid fallback). In that configuration they are covered only by automated
tests; the live runs used the isolated lab. See "Physical check" below.

## Gate evidence

`tests/learning/test_project_memory_release_gate.py` runs on the real archive
(schema 7, FTS5, provenance), the real history authority and routing, and the
Hello/Windows-session fakes; only Gemini is simulated:

| Gate | Test | Result |
| --- | --- | --- |
| Separate Nepal / Interview projects | `test_g1_projects_are_separate` | PASS |
| Cross-project retrieval, labelled | `test_g2_cross_project_retrieval_is_labelled` | PASS |
| Correction precedence | `test_g3_the_newer_correction_wins` + `test_newer_correction_comes_last_and_is_marked_current` | PASS |
| Archive search beyond the preload | `test_g4_…`, `test_project_voice_archive_qualification.py` (graded from real diagnostics) | PASS |
| Selective forgetting, no unrelated loss, restart | `test_g5_selective_forgetting_keeps_everything_else` | PASS (see note) |
| Grounding evidence: owner vs Jarvis, tentative vs decided | `test_g6_grounding_evidence_keeps_who_said_it_and_how_sure` | PASS (evidence and instructions; see limits) |
| Restart persistence, both projects | `test_g7_both_projects_survive_restart` | PASS |
| Installed profile can activate (coexistence PR) | `test_the_installed_profile_can_activate_project_memory` | PASS (no blockers) |
| Wake-output safety regressions | `test_voice_output_safety.py`, `test_voice_runtime.py` (ack races, transcript paths) | PASS |
| Flag OFF unchanged | `test_project_voice_production.py` (`test_flag_off_builds_no_project_memory`, `test_no_project_memory_leaves_sessions_untouched`) | PASS |
| Migration rehearsal tool | `tests/test_memory_migration_rehearsal.py` | PASS |
| Encryption / Windows | hosted CI: windows-dpapi, windows-hello-helper, windows-full-pytest, SQLCipher 4.17 Windows | see PR #308 |

**Forgetting note (owner decision, not a defect).** Owner rows are removed only
when they contain all the words; every other owner row survives, in every
project. Jarvis replies generated in a session whose model context held a
forgotten row are removed too, even in another project, because they may
restate it. A reply made without that row in its context is kept (tested).

**Grounding.** The model receives `owner:` / `Jarvis:` labels, dates and the
owner's exact wording (including hedges such as "maybe … not decided yet").
Its instructions now state that a tentative plan is not a decision, and that
Jarvis's replies and suggestions are not owner decisions unless the owner
accepted them. Whether Gemini follows the instructions cannot be tested without
a model call. That remains B7, and the first production smoke covers it.

## Must remain disabled

Only the release flag, until activation is approved: `JARVIS_PROJECT_MEMORY_MODE`
stays absent (off). The installed settings stay as they are: paid fallback ON,
personal context and learning APPLY, memory enabled, Gemini provider. B2 and B3
are resolved in the coexistence PR (`PROJECT_MEMORY_COEXISTENCE.md`), and
`--check` with the installed profile reports "will start with Jarvis" (tested).

## Release procedure (owner-run; nothing here has been executed)

**A. Backup and rehearsal (no change to production).**
1. Stop Jarvis (supervisor task and `jarvis-voice`).
2. Run `tools\windows\release\Backup-JarvisProduction.ps1`. It refuses while
   Jarvis runs. It copies `memory.db*`, `memory.key.dpapi`, `machine.json` and
   `authority\`, then verifies every copy by SHA-256 and writes `manifest.json`
   with the installed commit (expected `1a4f24be`).
3. Rehearse the migration on a copy, using the merged code from a separate
   worktree (not the installed App):

   ```powershell
   $c = "<final #308 SHA>"
   git -C E:\Jarvis\App fetch origin feat/project-memory-forget-recall-renewal
   git -C E:\Jarvis\App worktree add --detach E:\Jarvis\Worktrees\release-$($c.Substring(0,8)) $c
   $env:PYTHONPATH = "E:\Jarvis\Worktrees\release-$($c.Substring(0,8))\src"
   E:\Jarvis\App\.venv\Scripts\python.exe -X utf8 -m jarvis.memory.migration_rehearsal `
     --source E:\Jarvis\Data\LocalState\memory.db --work "$env:TEMP\jarvis-migration-rehearsal"
   Remove-Item Env:PYTHONPATH
   ```

   PASS requires all of these: the source is unchanged, the copy migrated to
   version 7, integrity and foreign keys are OK, and every existing table keeps
   its row count. Then delete the work folder, which holds an encrypted copy.
4. Start Jarvis again. Nothing has changed yet.

**B. Merge (after approval).** Mark #303 → #305 → #306 → #307 → #308 ready and
merge them in order (each base is the previous branch), or merge #308's branch
into `main` once. Keep `JARVIS_PROJECT_MEMORY_MODE` absent.

**C. Install with the flag OFF.**
1. Stop Jarvis.
2. Update `E:\Jarvis\App` to the merged `main`. No dependency changes:
   `pyproject.toml` is identical.
3. Start Jarvis normally. Migrations 4–7 run once.
4. Run `python -m jarvis.voice.project_voice_production --check`; it must say
   "disabled".

**D. Physical check (needed once, about 5 minutes, real hardware).** This uses
the owner's real configuration (personal APPLY, paid fallback, flag OFF), which
the lab never ran. Do:
- one wake with silence (hear one short acknowledgement);
- one wake speaking immediately;
- one personal-memory question;
- one Hands command;
- one research question.

Then check the log has no "turn dropped" or "speech is stopped" line for a
genuine reply. This is the only manual step; the gate cannot simulate Gemini
audio.

**E. Rollback.**
- **Code-only problem:** stop Jarvis, then
  `git -C E:\Jarvis\App checkout 1a4f24be`. The old build refuses the schema-7
  database (`MemorySchemaTooNewError`), so also restore the data (next point).
- **Data:** run `tools\windows\release\Restore-JarvisProduction.ps1 -Backup
  <folder>`. It verifies the manifest, moves current files aside (never
  deletes them), copies the backup back and prints the code checkout. Memory
  written after the backup is lost on this path.

## Activation (after the coexistence PR is merged and approved)

1. Add `"JARVIS_PROJECT_MEMORY_MODE": "voice"` to `machine.json`. Change no
   other setting.
2. Run `--check`; it must say "will start with Jarvis".
3. Start Jarvis and approve Hello. The log must show `Voice project memory
   active`.
4. Smoke test, about 10 minutes:
   - the `PROJECT_MEMORY_PRODUCTION.md` §6 step 7 items;
   - one personal question inside a project ("what should I eat on the Nepal
     trip?"): it is answered, it is not saved as project history, and the next
     question still works;
   - if a quota or recovery handoff happens, confirm the log line `Project
     voice context restored on the new model session`.
5. Any problem: remove the key and restart (instant rollback).

## Remaining blockers

| Id | Blocks | Status |
| --- | --- | --- |
| Owner approval | merge | required (PRs remain draft) |
| B5 | merge | handled by the backup and rehearsal (A) |
| Physical check D | confidence after merge | 5 minutes, flag OFF |
| B2 paid fallback | activation | resolved in the coexistence PR; a live handoff is observed opportunistically |
| B3 personal context / learning | activation | resolved in the coexistence PR; the activation smoke includes a personal question |
| B6 all tools blocking, B7 live grounding | activation | first activation smoke |
| Forget redacts Jarvis replies made with the words in context | none (design) | owner may ask to narrow it |
