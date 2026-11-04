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

## 2. Fresh memory deployment (owner decision, 2026-11-04)

Existing memory records and experimental conversations are **not** preserved.
No backup or migration rehearsal is required.

`memory.db` is the single canonical memory store. Starting it fresh therefore
also empties the remembered personal facts (for example, diet preference),
learned preferences and project history. The personal-context and learning
*capabilities* stay on (APPLY) and refill the new database as you use Jarvis.
The DPAPI key in `memory.key.dpapi` is used only by `memory.db`.

| Kept unchanged | Started fresh |
| --- | --- |
| `machine.json` (all settings: fallback, APPLY, devices, models) | `memory.db` (+ `-wal`, `-shm`): a new SQLCipher database at schema 7, empty |
| API keys (user environment variables) | `memory.key.dpapi`: a new random key, DPAPI-sealed for your Windows user |
| Windows Hello helper, `authority\`, `identity\` (speaker/face), `work\`, `secrets\`, `operations\`, models, logs, deployment and releases | — |

- **Safest clean initialization: retire, then create through the production
  path.** `python -m jarvis.memory.fresh_initialization initialize`:
  1. refuses while any Jarvis process runs;
  2. moves exactly the four memory files, all or nothing, to
     `E:\Jarvis\Data\Retired\memory-retired-<time>` (outside the data folder,
     so nothing loads them);
  3. creates the new database the way Jarvis does: SQLCipher 4.17 verified, a
     new DPAPI-sealed key, WAL, migrations 1–7;
  4. verifies it, counting rows only: schema 7, ledger 1–7, integrity and
     foreign keys OK, project-memory tables present, every data table empty.

  Nothing is deleted. You may delete the retired folder whenever you like;
  until then it makes a code rollback possible.
- **Why not reuse the old database:** a fresh file has no historical rows, no
  learning suppressions and no partial migration history, and its new key
  shares no material with the experimental data.
- **Why not delete:** deletion gains nothing at this point and would remove
  the only rollback path.
- **Evidence:**
  - `tests/test_memory_fresh_initialization.py`: everything else in the data
    folder is byte-identical, a new key is created, Jarvis-running refusal, a
    file in use moves nothing, restore works;
  - the Windows SQLCipher workflow now runs `initialize` twice and then
    `verify --expect-empty` with real SQLCipher 4.17 and DPAPI.

## 3. What needs you (Windows PC)

| # | Who | Action | Changes production? |
| --- | --- | --- | --- |
| 1 | You → me | Approve the merge | No (GitHub only) |
| 2 | You | Install the code, initialize memory, start with the flag OFF (≈5 min) | Yes |
| 3 | You | Add the flag, approve Hello, run the live acceptance (≈15 min) | Yes: activation |

Windows Hello approvals: at startup (as today), one for each personal-context
consent, one for the forget step, and one after lock/unlock.

## 4. Procedure

**Background:** the supervisor (`runtime_supervisor --branch main`) offers an
update only as a fast-forward from the local commit. The installed `main`
(`1a4f24be`) is not an ancestor of GitHub `main` (the October sync was
squashed). So merging never updates the PC by itself; step 2 is explicit.

### Step 1. Merge (after your approval; I do this)

The PRs are merged top-down, each into its own base, with merge commits (no
squash, so the ancestry stays intact): #309 → #308's branch, #308 → #307's, …,
#303 → `main`. Then `main` = the release commit `R`, and CI runs on `main`.

### Step 2. Install, initialize, start with the flag OFF (you)

```powershell
# Stop Jarvis (close the supervisor window/task) first.
git -C E:\Jarvis\App status --porcelain               # must print nothing
git -C E:\Jarvis\App tag jarvis-pre-memory-1a4f24be 1a4f24be
git -C E:\Jarvis\App fetch origin main
git -C E:\Jarvis\App checkout -B main origin/main       # code = R (editable install: no pip step)
E:\Jarvis\App\.venv\Scripts\python.exe -X utf8 -m jarvis.memory.fresh_initialization initialize `
  --data E:\Jarvis\Data\LocalState --retire-to E:\Jarvis\Data\Retired
& E:\Jarvis\Bootstrap\Start-Jarvis.ps1 -CheckOnly       # startup preflight only
& E:\Jarvis\Bootstrap\Start-Jarvis.ps1                  # normal start
```

Pass when:
- `initialize` prints `Memory database: PASS`;
- the preflight succeeds;
- startup reaches wake mode with your usual Hello approval;
- one wake works (an acknowledgement, then one question);
- `E:\Jarvis\App\.venv\Scripts\python.exe -m jarvis.voice.project_voice_production --check`
  prints "disabled".

Then stop Jarvis.

### Step 3. Activate and accept (you)

Add `"JARVIS_PROJECT_MEMORY_MODE": "voice"` to `settings` in
`E:\Jarvis\Data\LocalState\machine.json`, changing nothing else. Run `--check`;
it must print "will start with Jarvis". Start Jarvis, approve Hello, then run §5.

## 5. Live acceptance test (one run, ≈15 minutes)

Memory starts empty, so the test seeds what it checks.

| Step | Say / do | Pass when |
| --- | --- | --- |
| 1 Start | start Jarvis, approve Hello | log: `Voice project memory active` |
| 2 Memory | "Create project called Nepal trip." · "We will take the Thar." · "Maybe we'll visit Pokhara, not decided yet." Let the wake end; wake again: "Which vehicle are we taking, and is Pokhara decided?" | "the Thar"; Pokhara described as not decided |
| 3 Personal security | "Remember that my diet preference is vegetarian." Then: "What should I eat on the Nepal trip?" (approve the personal-context Hello) | answered as vegetarian; at shutdown the `Voice project memory summary` shows `personal_replies_not_saved` ≥ 1 |
| 4 No leak | new wake: "What did you tell me to eat?" | it does not repeat that answer from project history (it may ask again via personal context) |
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
| Project memory misbehaves | Remove `JARVIS_PROJECT_MEMORY_MODE` and restart. Instant |
| Merged build misbehaves | Stop Jarvis, **then, while the new code is still checked out**: `E:\Jarvis\App\.venv\Scripts\python.exe -m jarvis.memory.fresh_initialization restore --data E:\Jarvis\Data\LocalState --retire-to E:\Jarvis\Data\Retired --from E:\Jarvis\Data\Retired\memory-retired-<time>`. Then `git -C E:\Jarvis\App checkout -B main jarvis-pre-memory-1a4f24be` and start Jarvis. The old build needs its old schema-3 files, which the restore puts back; the new files are moved aside, not deleted |

## 7. Deployment checklist

- [ ] 1: your approval; merges #309 → … → #303 done; `main` = R; CI green on `main`
- [ ] 2: rollback tag created; App at R; `initialize` PASS; preflight OK; flag-OFF start and one wake OK; `--check` "disabled"
- [ ] 3: flag added; `--check` "will start"; Hello; `Voice project memory active`
- [ ] §5 steps 1–8 pass
- [ ] Optional cleanup:
  - delete `E:\Jarvis\Data\Retired\memory-retired-*` (this ends the code-rollback option);
  - delete the `%TEMP%\jarvis-qualification-*` labs, then run `git -C E:\Jarvis\App worktree prune`

## 8. Decision

**GO.** Merge on your approval, then steps 2–3. The milestone is complete when
§5 passes.

Known, accepted limits:
- A paid handoff is observed only if it happens naturally.
- Gemini's adherence to grounding instructions is judged by §5 step 2.
- Forgetting also removes Jarvis replies made with the forgotten words in
  context (by design).
