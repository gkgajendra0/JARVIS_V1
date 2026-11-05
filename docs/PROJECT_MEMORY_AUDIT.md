# Project memory: end-to-end audit, test matrix and acceptance framework

Date: 2026-11-04. Base: `main` `e4a59784` (#303, #305–#311 merged). The fixes
are in PR #312.

## 1. Why defects reached production with green CI

| Defect found in deployment | Root cause | Why CI missed it |
| --- | --- | --- |
| Hello helper blocked by Smart App Control (#310) | A locally compiled, unsigned helper; Smart App Control allows only signed or cloud-known files | CI runners do not enforce Smart App Control |
| Startup killed at 120 s (#311) | One deadline for the whole build; a cold LR-ASD CUDA load took 80 s | Tests used fast fakes; no timing variance |
| "Create a project. Called Nepal trip." created nothing (#312) | Parser required "project called" with no punctuation between | The failing speech-to-text split was absent from regression fixtures |
| That failed command was learned as a plan "Nepal trip" (#312) | Personal learning had no notion of project-control commands | Learning and project routing were tested separately |

Coverage gap: **the failing speech-to-text forms were absent from the tested
journeys**, despite existing component and archive tests. The audit
below therefore drives the real voice pipeline with transcripts as
speech-to-text writes them, and asserts on database rows.

## 2. Production path, traced

```text
microphone → wake (openWakeWord + bounded verifier) → LiveKit VAD → Gemini Live
  transcription → LiveKitConversationBridge (canonical USER/ASSISTANT turns)
  → VoiceProjectTurns.observe_turn → ProjectConversationCoordinator
  → ProjectRouter.resolve (create / switch / clarify / continue)
  → ProjectArchiveAccess (history grant, Windows Hello at startup)
  → ProjectConversationStore (SQLCipher schema 7, FTS5, provenance edges)
  → preload / prepare_project_turn / search_history → Gemini reply
  → ProjectAudioGate + PersonalContextAudioOutput → speech
  → session end → new wake → preload of the current project
  → restart → new grant → catalog + current selection restored
side paths: personal learning (canonical memory), forget (Hello-approved
  delete of matching rows and derived replies), Gemini handoff (context
  re-given), Hello renewal after lock/unlock
```

## 3. Findings, ranked

| # | Severity | Finding | Evidence | Status |
| --- | --- | --- | --- | --- |
| F1 | **High: data integrity** | Common spoken switches were not commands: "Can you switch to Nepal trip?", "Let's switch to …", "Switch back/over to …", "Go to …", "Open the … project", "Switch to. Nepal trip." Routing silently **continued in the current project**, so the next statements were **saved into the wrong project** | `test_spoken_switch_moves_later_turns_to_that_project`: 7 of 12 variants failed before the fix (rows stored under "Interview prep") | Fixed (#312) |
| F2 | **High: data integrity** | Project names kept speech-to-text artifacts: "Nepal trip," (from "…, please"), "called, Nepal trip", '"Nepal trip"', "Nepal. Trip". A project with the wrong name was created, and later switches by name missed it | `test_spoken_creation_writes_one_clean_project` | Fixed (#312): `clean_project_name` |
| F3 | High: production | Punctuation or fillers between "project" and "called" ("Create a project. Called Nepal trip.", "…, um, called …") were not recognised | Production log 2026-11-04 12:44:44 and 12:45:02 UTC | Fixed (#312) |
| F4 | High: memory integrity | Personal learning stored the project command as a confirmed plan "Nepal trip" (`c19a81f9-…`) | Production log 12:44:47 UTC (storage committed) | Fixed (#312): create and switch commands are not learning sources. **The existing fact is left for your review** |
| F5 | Medium | "Switch to Hindi" / "Switch to English" became a project clarification instead of a language change | Parser review; you speak Hindi/English/Hinglish | Fixed (#312): a language is a project only if such a project exists |
| F6 | Medium | Polite, natural verbs could catch ordinary speech ("Go back to sleep", "open the window") if made commands | Design risk of the F1 fix | Guarded: those verbs switch only to an **existing** project. Tests cover "Go back to sleep", "Open the window", "We should go to Nepal in spring" |
| F7 | Low | The first ordinary utterance creates a "General" project ("What time is it?" → action=created) | Production log 12:44:25 | By design; documented |
| F8 | Low | Standby and control phrases ("Go back to sleep.") are saved into project history | Production log 12:45:41; existing test asserts it | By design; harmless, forgettable |
| F9 | Low | `test_local_preparation_and_preload_are_fast` (500 ms bound) flakes on hosted Windows runners | CI rerun on #310 | Known flake; not a product defect |
| F10 | Limit | Whether Gemini *uses* the context correctly (corrections, tentative plans, not leaking across projects in its wording) is model behaviour | Only measurable live | Live acceptance (§5 level E) |
| F11 | Limit | The test harness feeds final transcripts; LiveKit partial→final segmentation is tested in the bridge tests, not in these journeys | Test design | Live acceptance covers it |

No issue was found in: forget authorization (Hello denied, cancelled, error,
timeout, or wrong words → nothing deleted), restart persistence, preload
isolation, duplicate-creation prevention, handoff context (#309), personal
context gating (#309), Hello renewal (#308) or fail-closed Hello (#310). Each
is covered by the tests in §4.

## 4. Coverage matrix

Levels: **A** unit · **B** integration with production components (real
router, archive store on SQLite schema 7 + FTS5, history authority, voice
pipeline; Gemini simulated) · **C** Windows (hosted Windows CI: SQLCipher
4.17, DPAPI, WinRT Hello calls) · **D** real Gemini Live lab · **E** real
microphone + Windows Hello on your PC · **F** restart/persistence · **G**
failure injection.

| Journey | A | B | C | D | E | F | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Create (spoken variants, clean names, no duplicate) | `test_project_command_punctuation` | `test_project_memory_spoken_journeys` (12 variants, DB titles) | windows-full-pytest | qualification Q-steps | **pending** | — | unreadable command asks, writes nothing |
| Switch / isolation (spoken variants, rows land in the right project) | ✓ | `…spoken_journeys` (12 variants + ordinary-speech negatives, DB rows) | ✓ | ✓ | **pending** | — | unknown project changes nothing |
| Recall across wakes (preload) | ✓ | `…spoken_journeys`, release gate G1/G4 | ✓ | ✓ | **pending** | — | — |
| Correction precedence | ✓ | `…spoken_journeys`, G3 | ✓ | ✓ | **pending** | — | — |
| Forgetting (only intended rows, FTS index too) | ✓ | `…spoken_journeys` (4 variants), `test_project_voice_forget_recall`, G5 | ✓ | ✓ | **pending** | G5 restart | Hello cancelled/error/retries, words not said: nothing deleted |
| Cross-project retrieval (labelled) | ✓ | G2 | ✓ | ✓ | **pending** | — | — |
| Restart persistence | — | `…spoken_journeys`, G7 | ✓ | — | **pending** | ✓ | — |
| Personal learning vs project commands | `test_project_command_punctuation` (commands excluded; travel/work/plan statements still eligible) | — | ✓ | — | DB check in recorder | — | — |
| Gemini free→paid handoff | — | `test_project_memory_coexistence` (real handoff + LiveKit session) | ✓ | — | natural only | — | 1011/1008 recovery, unconfigurable model aborts |
| Windows Hello (startup grant, forget, renewal) | `test_windows_hello_builtin` | `#308` renewal tests | real WinRT calls on CI | — | **approve + cancel PASSED on your PC** | — | timeout/error/blocked helper fail closed |
| Startup readiness | `test_startup_progress` (real processes) | — | ✓ | — | **PASSED on your PC** | — | hang detected, exit reported |
| Output safety (no internal text spoken) | `test_voice_output_safety` (verbatim production transcripts) | bridge tests | ✓ | ✓ | **pending** | — | — |

Production failure transcripts kept as fixtures: the two 2026-11-04 create
transcripts (#312), the wake-acknowledgement leaks from 2026-11-03
(`test_voice_output_safety`), and the qualification failures at 8155df0d and
1b13dfb8 (release-gate and qualification tests).

## 5. Acceptance framework

| Level | How it runs | Recorded as |
| --- | --- | --- |
| A, B, C, G | GitHub CI on every PR (ruff, pytest, windows-dpapi, windows-hello-helper, windows-full-pytest, SQLCipher 4.17) | CI run link |
| D | `Start-JarvisProjectVoiceLab.ps1 -Qualification` (isolated lab, real Gemini Live), graded by `project_voice_qualification` | sealed lab report |
| E, F | You speak the scenario to the installed Jarvis, then run the recorder | `E:\Jarvis\Data\LocalState\acceptance\project-memory-<time>.md` and `.json` |

**The recorder** is `python -m jarvis.voice.project_memory_production_acceptance --since <UTC start>`.
- **What it reads:**
  - the production log: transcripts, replies and project receipts;
  - the existing production database, through SQLCipher/DPAPI with URI
    `mode=ro` and `PRAGMA query_only`; it never initialises or migrates it. It checks projects and row counts,
    expected facts present, forgotten facts absent, duplicate titles, and
    possible plans learned from commands. Surviving scenario turns must match
    their canonical log turn IDs, exact text and expected project. The hotel
    statement and forget command are intentionally removed, so their evidence
    comes from the transcript, deletion receipt, absence checks and review.
- **What it records per step:** PASS, FAIL or NOT TESTED, with the expected
  reply, the actual transcript, the actual reply, the receipt and the
  database result.
- **Key handling:** the protected SQLCipher key is unsealed internally via
  DPAPI, never included in the report. No provider credentials are needed.
- **Release verdict:** missing receipts, missing replies, wrong project rows,
  or reuse of the previous wake session fail the relevant step. Receipts must
  contain the exact canonical turn ID and session ID; legacy anonymous
  receipts cannot qualify a run. Replies are matched within their wake, and
  multiple unanswered user turns are flagged as ambiguous. Any unresolved
  REVIEW keeps the overall result INCOMPLETE. Keyword checks are smoke checks;
  they cannot certify response meaning, audible output or process restart.
- **Explicit review:** the recorder writes a `.review.json` template with
  NOT TESTED entries. A named reviewer must assess each answer, record restart
  evidence (shutdown/startup timestamps or process IDs) and audible output.
  Supply the completed file with `--review <file>`, using the same run start.
  The review is bound to a SHA256 of the collected timeline, database evidence
  and scenario. Changed evidence invalidates it; review cannot override a
  failed automatic check. A review file is an observation record, not a
  cryptographic identity or an independent semantic evaluator. The logs do
  not carry exact response-to-user metadata for same-session continuations;
  the reviewer must inspect the full conversation and audible output, wait
  for each reply before the next scenario statement, and reject uncertain
  attribution rather than infer success.

**The scenario** is in `SCENARIO` in the recorder module:
1. **Create, using the production phrasing:** "Create a project. Called Nepal
   trip."
2. **Three facts:** a vehicle, a hotel, and a tentative plan.
3. **Recall** in a new wake.
4. **Correction.**
5. **Second project and isolation.**
6. **Spoken switch:** "Can you switch to Nepal trip?"
7. **Forget the hotel** (Windows Hello).
8. **Recall the forgotten fact.**
9. **Restart, then recall** in both projects.

## 6. Release gates

| Gate | Status |
| --- | --- |
| Jarvis starts reliably | One observed start after #311; cold-start venv worker qualification pending |
| Normal wake and voice responses | PASS (2026-11-04 12:44 UTC: greeting, time, IST answer) |
| Projects created and stored correctly | Fixed in #312; **E pending** |
| Memory survives new wake sessions | B pass; **E pending** |
| Corrections supersede | B pass; **E pending** (model behaviour) |
| Projects isolated | Fixed in #312 (F1); **E pending** |
| Forgetting exact | B pass; **E pending** |
| Survives restart | B pass; **E pending** |
| Authentication and failures fail closed | PASS (A–C, plus Hello approve/cancel on your PC) |
| Automated regression gate | Require checks on the exact amended PR head; live acceptance remains separate |
| Real-machine evidence recorded | **Pending:** recorder run |

## 7. Decision

**NO-GO until the E/F run and explicit evidence review pass.** Green code
checks do not establish real-machine acceptance.
Production-ready means:
1. you approve merging #312;
2. I deploy it to your PC;
3. you speak the scenario once (about 15 minutes, with two Hello approvals and
   one restart);
4. the recorder and evidence-bound review report PASS, with any existing
   questionable personal fact resolved explicitly without automatic deletion.

Outstanding risks:
- **Model behaviour** (F10): Gemini may still word an answer badly; the
  keyword checks catch some obvious failures; a reviewer must judge meaning.
- **Paid handoff:** observed only if it happens naturally.
- **The learned plan `c19a81f9`** stays until you decide.


## 8. Codex handover: validation limits and safe next steps

The saved local Hello acceptance artifact records approval and cancellation
PASS, but also a failed Smart App Control policy check and no completed
no-answer/timeout step. Those results do not establish that all original
Hello acceptance steps passed. Investigate the policy-query failure before
attributing it to the actual enforced policy or changing Windows settings.
Do not disable Smart App Control to get a test to pass.

The original recorder's normal database opener could configure WAL and apply
migrations before query_only was enabled. The inspection opener now requires
existing database/key files, opens mode=ro, verifies SQLCipher, and skips all
creation/migration paths. Encrypted fixtures test write denial even if
query_only is disabled, missing-file preservation, wrong keys, older schema
markers and committed WAL visibility.

Before a deployment: record the installed Git SHA and clean-tree status;
confirm Jarvis is stopped; preserve an encrypted database/key/config backup
and verify hashes. If WAL/SHM files exist or a writer remains active, use an
appropriate consistent backup rather than assuming copying memory.db alone
captures it. Keep the current environment and dependencies intact.

The scenario uses fictional facts in real project history. The owner should
know that these statements will be saved. If Nepal trip or Interview prep
already exists, the create receipt may correctly be 'continued' rather than
'created'; do not delete or reset existing projects to satisfy this script.
Choose an isolated acceptance profile or agree on distinct scenario names
before running it. This fixed-name recorder cannot qualify a renamed scenario
without matching changes to SCENARIO and its expectations.

For this installation the recorder shell must explicitly select the E-drive
machine config and log. From the tested source/environment after approval:

```powershell
$env:JARVIS_MACHINE_CONFIG = 'E:\Jarvis\Data\LocalState\machine.json'
& E:\Jarvis\App\.venv\Scripts\python.exe -m jarvis.voice.project_memory_production_acceptance --since <UTC-start> --log E:\Jarvis\Data\LocalState\logs\jarvis.jsonl --out <private-report-directory>
```

Do not run a recorder from an unverified source path. Preserve the original
log and reports locally; they contain conversation text. Review the full
JSON and log, because the Markdown reply column is abbreviated. No API-key
handoff or paid-provider test is authorised by this acceptance procedure.


### Additional startup finding during full-suite handover validation

The full suite found two repeatable failures in test_startup_progress, also
reproduced in isolation. On this Windows installation, the venv python.exe
redirector's Popen PID differs from the base-Python worker writing the heartbeat.
The existing PID check rejected real progress. A warm start can still connect
before the old timeout; this does not prove a cold progressing start is protected.

The separate proposed supervisor fix accepts the exact watched PID, or on
Windows its OS-verified live direct worker with matching Python executable
images. Unrelated/stale processes remain rejected. Real child tests cover the
steady start, stall, exit, overall cap, and unrelated Python heartbeat writer.
This fix is not deployed; actual cold-start qualification remains pending.


### Local verification of the proposed amendments (2026-11-05)

The final standard-CLI full suite completed with **4499 passed, 19 skipped**
and exit code 0 in 384.14 seconds. Ruff and formatting checks passed.
The skips include real OPA (required separately in Linux CI), unavailable
symlink privileges, platform-specific negative controls and real Hello prompts.
Four dependency future warnings were reported. Independent code review found
no remaining Critical or Important findings in the amendments.

A previous run exposed the Windows venv startup identity defect described
above. Another interrupted run used overly long diagnostic temp paths; the
mapped incident-repair tests passed with short paths and reproduced Git's
"Filename too long" under the long paths. The completed verification used a
short task-local temp root. No incident-repair code was changed.

The pinned Windows SQLCipher workflow now runs the read-only encrypted-memory
tests explicitly, with test-file path triggers. Hosted checks for the exact
amended head, real microphone/audio, Hello timeout and process restart remain
pending. These local results do not grant production acceptance.
