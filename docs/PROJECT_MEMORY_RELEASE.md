# Memory milestone — production release (#303–#309)

The release is the stack #303 → #305 → #306 → #307 → #308 → #309 (#304 is
archived and not part of it). Project memory is deployed as a **fresh** feature
on the installed configuration: Gemini free by default, paid fallback ON
(automatic admission), personal context APPLY, personal learning APPLY.

## 1. Release verification (evidence)

| Check | Result |
| --- | --- |
| Stack is linear: every head contains its base's head, down to `main` `488954a6` | PASS (`git merge-base --is-ancestor` along the chain) |
| `main` has not moved since the stack began | PASS (`main` = `488954a6`) |
| Every PR draft, `mergeable_state=clean`, all checks green at its head | PASS: #303 `cf42ecb6`, #305 `92b93c4b`, #306 `70a684ff`, #307 `7bb3671e`, #308 `03606ff5`, #309 `75f56a1b` |
| Hosted CI at #309 `75f56a1b` | PASS: ruff, pytest, windows-dpapi, windows-hello-helper, windows-full-pytest, promotion-policy, SQLCipher 4.17 Windows |
| Dependencies | unchanged (`pyproject.toml` identical to `main`): no install step |
| Installed build `E:\Jarvis\App` `1a4f24be` vs `main` | same `src/`; only docs and two test fixtures differ. The App is an editable install, so a git checkout is the whole code update |
| Schema | 3 → 7 on first start (migrations 0004–0007), one-way for older builds |
| B2 Gemini fallback / handoff, B3 personal context / learning APPLY | resolved in #309 (`PROJECT_MEMORY_COEXISTENCE.md`); the installed profile passes `--check` (tested) |
| Earlier gates (projects, cross-project, corrections, archive search, forgetting, grounding evidence, restart, wake/output safety, flag OFF) | PASS, recorded in `PROJECT_MEMORY_PRODUCTION.md` §12–14 and the release-gate tests; not repeated |

## 2. What "fresh memory deployment" means here

- **Project conversation memory starts empty.** Its tables are created by the
  migration. No lab archive (`%TEMP%\jarvis-qualification-*`) is imported;
  those folders can be deleted at any time.
- **Preserved unchanged:** `machine.json`, API keys (user environment), the
  DPAPI-sealed memory key, the Windows Hello helper and authority state, and
  canonical personal memory and learning data. Canonical memory is not
  experimental conversation data, and the migration keeps every existing row
  (the rehearsal verifies this on a copy).
- **Not part of this release:** wiping canonical personal memory. If you want
  that too, it is a separate, explicit decision. It is reversible only from the
  backup.

## 3. What needs you (Windows PC) — nothing runs without these

| # | Who | Action | Changes production? |
| --- | --- | --- | --- |
| A | You | Stop Jarvis, run the backup, run the migration rehearsal (≈10 min) | No (copies only) |
| B | You → me | Approve the merge | No (GitHub only) |
| C | You | Install the merged code, start with the flag OFF (≈5 min) | Yes: code and schema |
| D | You | Add the flag, approve Hello, run the live acceptance (≈15 min) | Yes: activation |

Windows Hello approvals during D: one at startup (history grant), one for each
personal-context consent, one for the forget step, and one after lock/unlock.

## 4. Procedure

**Background:** the supervisor (`runtime_supervisor --branch main`) offers an
update only as a fast-forward from the local commit. The installed `main`
(`1a4f24be`) is not an ancestor of GitHub `main` (the October sync was
squashed). So merging never updates the PC by itself; step C is explicit.

### A. Backup and rehearsal (before approval; no production change)

```powershell
# 1. Stop Jarvis (close the supervisor window/task).
# 2. Back up, then rehearse the migration on a COPY, both with the release code:
$c = "75f56a1bc3431de1e22948a1c34c0dcb94af6006"
git -C E:\Jarvis\App fetch origin feat/project-memory-coexistence
git -C E:\Jarvis\App worktree add --detach "E:\Jarvis\Worktrees\release-75f56a1b" $c
& "E:\Jarvis\Worktrees\release-75f56a1b\tools\windows\release\Backup-JarvisProduction.ps1"
$env:PYTHONPATH = "E:\Jarvis\Worktrees\release-75f56a1b\src"
E:\Jarvis\App\.venv\Scripts\python.exe -X utf8 -m jarvis.memory.migration_rehearsal `
  --source E:\Jarvis\Data\LocalState\memory.db --work "$env:TEMP\jarvis-migration-rehearsal"
Remove-Item Env:PYTHONPATH
Remove-Item -Recurse -Force "$env:TEMP\jarvis-migration-rehearsal"   # encrypted copy
# 3. Start Jarvis again as usual: nothing in production has changed.
```

The backup script lives only in the release code, so run it from the release
worktree. **Proceed only if** the backup prints `Backup verified` and the
rehearsal prints `PASS`: source unchanged, schema 3 → 7, integrity and foreign
keys OK, every existing table's row count unchanged.

### B. Merge (after your approval; I do this)

The PRs are merged top-down, each into its own base, with merge commits
(no squash, so the ancestry stays intact): #309 → #308's branch, #308 → #307's,
… then #303 → `main`. Each merge is a fast-forward-equivalent of an
already-green tree. Then `main` = the release commit (`R`).

### C. Install, flag OFF (you)

```powershell
# Stop Jarvis first.
git -C E:\Jarvis\App status --porcelain          # must print nothing
git -C E:\Jarvis\App tag jarvis-pre-memory-1a4f24be 1a4f24be
git -C E:\Jarvis\App fetch origin main
git -C E:\Jarvis\App checkout -B main origin/main  # local main = R (future updates fast-forward)
& E:\Jarvis\Bootstrap\Start-Jarvis.ps1             # migrations 0004-0007 run once
```

Check, then stop Jarvis:
- the startup has no `MemorySchemaTooNewError` and no migration error;
- one wake works (an acknowledgement, then one question);
- `python -m jarvis.voice.project_voice_production --check` prints "disabled".

### D. Activate and accept (you)

Add `"JARVIS_PROJECT_MEMORY_MODE": "voice"` to `settings` in
`E:\Jarvis\Data\LocalState\machine.json`, changing nothing else. Run `--check`;
it must print "will start with Jarvis". Start Jarvis, approve Hello, then run §5.

## 5. Live acceptance test (one run, ≈15 minutes)

| Step | Say / do | Pass when |
| --- | --- | --- |
| 1 Start | start Jarvis, approve Hello | log: `Voice project memory active` |
| 2 Memory | "Create project called Nepal trip." · "We will take the Thar." · "Maybe we'll visit Pokhara, not decided yet." Let the wake end; wake again: "Which vehicle are we taking, and is Pokhara decided?" | "the Thar"; Pokhara described as not decided |
| 3 Personal security | "What should I eat on the Nepal trip?" (approve the personal-context Hello) | answered from your diet preference; at shutdown the `Voice project memory summary` shows `personal_replies_not_saved` ≥ 1 |
| 4 No leak | new wake: "What did you tell me to eat?" | it does not repeat the earlier answer from project history (it may ask again via personal context) |
| 5 Renewal | Win+L, unlock, wake, approve Hello, "Add a stove to the packing list." | saved and answered once |
| 6 Recovery | in a wake, turn the network off for ~5 s, then on, then ask "Which project are we in?" | either the log shows `Gemini fresh voice session ready` + `Project voice context restored on the new model session`, or the session ends cleanly and the next wake answers "Nepal trip". Either way: no duplicate saves, no internal text spoken |
| 7 Forget | "Forget that we will take the Thar." (approve Hello); new wake: "Which vehicle?" | one confirmation, after both deletions; the vehicle is not known |
| 8 Restart | restart Jarvis, approve Hello: "Is Pokhara decided?" | "not decided" (it persisted) |
| Throughout | — | no `turn dropped` / `speech is stopped` line on a genuine reply; Hands, research and wake/standby behave as before |

**Paid-key handoff cannot be forced in your configuration.** The bounded
fault-injection plan requires budget-enforced paid admission, and yours is
automatic. A real quota event is unpredictable. The handoff path is verified by
automated tests against the real `GeminiLiveHandoff` and LiveKit session (#309).
In production, a natural handoff shows the line `Project voice context
restored on the new model session`.

## 6. Rollback

| Problem | Action |
| --- | --- |
| Project memory misbehaves | Remove `JARVIS_PROJECT_MEMORY_MODE` and restart. Instant; nothing else changes |
| Merged build misbehaves with the flag OFF | Stop Jarvis; `git -C E:\Jarvis\App checkout -B main jarvis-pre-memory-1a4f24be`; then `Restore-JarvisProduction.ps1 -Backup <folder>` (the old build refuses schema 7, so data and code go back together) |

Memory written after the backup is lost on the full rollback. The restore moves
current files aside and never deletes them.

## 7. Deployment checklist

- [ ] A: backup verified; rehearsal PASS (3 → 7, counts unchanged)
- [ ] B: your approval; merges #309 → … → #303 done; `main` = R; CI green on `main`
- [ ] C: rollback tag created; App at R; flag-OFF start clean; one wake OK; `--check` "disabled"
- [ ] D: flag added; `--check` "will start"; Hello; `Voice project memory active`
- [ ] §5 steps 1–8 pass
- [ ] Remove the release worktree (`git -C E:\Jarvis\App worktree remove E:\Jarvis\Worktrees\release-75f56a1b`) and, optionally, the `%TEMP%\jarvis-qualification-*` labs (`git -C E:\Jarvis\App worktree prune` afterwards)

## 8. Decision

**GO** for deployment, conditional on gate A (backup verified and rehearsal
PASS on the real database) and your approval at B. Activation (D) is GO once C
is clean. The milestone is complete when §5 passes.

Known, accepted limits:
- A paid handoff is observed only if it happens naturally.
- Gemini's adherence to grounding instructions is judged by §5 step 2.
- Forgetting also removes Jarvis replies made with the forgotten words in
  context (by design).
