# Project conversation memory acceptance

Status: controlled **text** implementation; owner-machine and real-model acceptance
OPEN. The first Windows text run at `7b6c6ede` FAILED during routing. At
`d8504526`, routing/capture and recall after sleep passed on the owner machine,
but one status request FAILED during generation with `ValueError`.
This is not a normal-app activation or a native voice pass.

The [contract](PROJECT_CONVERSATION_MEMORY.md) owns G1–G8 and acceptance targets.
The [plan](superpowers/plans/2026-10-31-project-conversation-memory.md) owns work.

## What the candidate connects

Accepted eligible canonical turn → persisted selection → encrypted event receipt →
bounded selected-thread context → existing Gemini answer/tool cycle → final release
validation → actual delivered assistant event. Model-selected save proposals are
not required. Original history is authoritative even without a compact-state update.

Projects survive source-transport replacement and profile reopen. New conversations
get new thread IDs inside the project; searches and explicit source reads span
that project's threads. Names/aliases are exact. A named question can select an
existing project; vague/fuzzy matches do not. `Select project <owned-id> thread
<owned-thread-id>` resolves duplicate names using IDs shown by `/projects`.

Existing personal facts use `PersonalContextSession` and exact current-owner read
consent. The new read-only question-query opt-in does not enable learning writes.
The isolated profile starts with its own empty personal memory; production facts
are not copied implicitly. Software tests seed fictional canonical facts.

Local tools get one archive search and one deeper source read per request; one
personal query is allowed. The answer/tool loop has at most four provider steps.
All requests use the existing routed client. The lab restricts targets to the
configured Free credential lane: it cannot reset/expand the cumulative Paid
fallback allowance. A lane name is not a promise about the account's actual bill.
Actual request/usage observation is printed with each response; unavailable usage
is marked unobserved. No standalone extraction, summary or query-planning call.

The 6,000 external-context ceiling uses a deliberately conservative UTF-8 wire-byte
upper estimate, following the existing routing exposure bound. It is **not** a
calibrated tokenizer or measured usage. This reduces usable context capacity;
provider usage calibration remains open. Oversized/uncovered sources and excluded
turns produce explicit coverage metadata. Retrieval no-match, partial, unavailable
and not-requested states are distinct. History never proves a real-world action
executed merely because an assistant suggested it.

## Local software evidence

- Required recorder, transactional store, migration-4→5 reopen, duplicate callback,
  repeated-text, original roles, source/permit binding, storage failure and
  revocation tests run on real SQLite transactions with fake OS/Hello boundaries.
- The replay freezes 200 original events / 10 projects / 30 segments. All 200
  commit and reconcile after reopen; 200 repeated callbacks add no events.
- Delivery tests assert selected source IDs, scope and context at the production
  Gemini adapter's serialized request boundary. No real provider is contacted.
- Real canonical personal-fact fixtures exercise the existing owner-consent path;
  revocation immediately before the async provider-dispatch guard blocks disclosure.
- Inspection, pause, omission coverage, current-request invalidation, all-thread
  deletion approval, immutable redacted deletion identities and late-callback
  source routing have regression coverage. Private history is not added to UI feeds.
- Independent review found four Important gaps: lab personal reads disabled;
  older threads inaccessible; assistant omission coverage absent; stale personal
  facts passing the dispatch guard. Each was reproduced RED→GREEN. The review's
  status-reporting minor was treated as Important and fixed with a payload test.
- The old Windows smoke gate hardcoded schema 4. Its actual Windows logs showed
  encryption/reopen/FTS/DPAPI/plaintext-block/leak checks passing, but schema and
  ledger checks failing after migration 5. The gate now checks packaged migrations;
  a local regression fails against the old assumptions and passes the new gate.

None of these is an actual-model quality score or Windows spoken acceptance.
The earlier rejected full-local-suite telemetry command was not rerun/bypassed.

Prior connected-candidate local scoped run: **484 passed**; repository Ruff check passed. A synthetic
Linux SQLite/fake-OS run measured archive p95 **3.63 ms** (200 samples) and local
snapshot/context p95 **1.48 ms** (10 samples), with zero model requests. These are
not SQLCipher/Windows, real-authentication, provider or speech latency measurements.

## Windows routing failure and policy repair (31 October)

The owner launched exact commit `7b6c6ede` successfully, but the first Nepal turn
failed during routing before project selection, capture or Gemini dispatch. Python
recognized `memory:conversation_history` delegation; production Rego recognized
only `memory:personal_learning`. The history catalog read therefore hit the generic
SYSTEM private-read rule and its attention/actor requirements. The initial strong
owner grant could not authorize that child read.

The repair adds a dedicated history-delegation policy branch for read/admit/suppress.
It requires SYSTEM origin, delegated-policy approval and a nonempty string parent
ID. Python still verifies the registered live grant, exact source/payload/scope,
revocation and one-use permits. Unrelated private reads keep their existing rules.
The isolated lab pins the reviewed source policy for its process and restores any
inherited override on exit; installed policy/settings are not edited.

Earlier tests used a simplified policy fixture, so their green results missed this
production-policy mismatch. Fixture descriptions are corrected. A real OPA + real
authority/store integration regression reproduces the routing denial and exercises
capture/recall with a fake provider. Linux CI now provisions checksum-pinned OPA
and requires that regression, including malformed/missing delegation and unrelated
private-read controls. Fake provider answers remain software evidence only.

Unaffected scoped verification after this repair: **375 passed**, excluding the
real-OPA module. A broader local run was stopped by automatic approval review for
possible external OPA telemetry with unknown payload; it was not retried. Hosted
CI must qualify the final policy/test matrix separately. Independent review found
no Critical/Important issue. Actual owner-machine/Gemini acceptance remains OPEN.

Exit the old lab with `/quit`. Keep its profile for diagnosis. Its failed first
turn was not captured. Start a new isolated profile with the repaired exact commit;
do not resume the old profile with a different pinned source revision.

## Owner rerun at d8504526: partial pass, generation failure unresolved

The owner machine committed the first Nepal user/assistant pair and the Jimny /
permit-pending pair. The first status request committed its user event (sequence 5),
then failed in stage `generating` with exact exception type `ValueError`; no assistant
event was fabricated. After `/sleep`, the same named status query correctly recalled
Jimny and permit pending. `/inspect` showed seven original events, the same project
and thread, and zero omissions. This is actual Windows/Hello/SQLCipher/Gemini evidence
for this short sequence, including recall after sleep, not process-restart, all goals
or full reliability acceptance. Failed-call usage is not present in the pasted trace;
do not count it as zero.

The exact generation failure is UNKNOWN because the lab catch handler printed only
exception type. Two coordinator checks can raise a plain ValueError in this stage:
a response mixing an answer and tool request (or multiple tools), and an empty
answer without tools. The provider/invoker may also raise ValueError. A network-free
fixture reproduces the mixed-response path and identical stage, but does not prove
that it caused this owner's failed call. No speculative retry or relaxed tool/scope
validation is applied.

`tools/project_memory_failure_probe.py` is a diagnostic companion, extracted outside
the reviewed checkout. Run it with the existing lab's `source/src` on PYTHONPATH and
the same `--source-commit`, `--lab-root <existing-lab>/profile`, `--model`, and
`--resume-lab`. Exit the old process first to release its profile lock. The original
lab main still verifies source cleanliness, pinned commit and profile marker, renews
Hello consent and takes its exclusive lock. Existing history is retained.

The probe reports only response presence/counts and code locations (module/function/
line), exception class and two allowlisted reason codes. No arbitrary exception
message, frame locals, prompt, raw model text, credential or full filesystem path
is printed by the probe. Ordinary lab answers and explicit inspection keep their
existing behavior. It neither retries nor changes authority, fallback, storage or
provider inputs. Unit tests verify same-result/same-exception behavior, one dispatch,
method restoration and redaction; a real coordinator/store fixture verifies that
the failed user's event remains committed without a fake assistant event.
The diagnostic change passed 381 scoped tests (real-OPA module excluded), repository
Ruff and formatting checks. Independent review found no Critical/Important issue;
its diagnostic-output-failure minor was reproduced and fixed without changing
normal results or original exceptions.

The owner-only next step is to reproduce a generation failure under this probe,
using the retained Nepal project. A successful probe query alone does not diagnose
the earlier intermittent error. Share only `PROJECT_PROBE_STEP`,
`PROJECT_PROBE_FAILURE` and `NOT COMPLETED` lines when a failure occurs.

## Frozen actual-model questions: UNRUN

`tests/project_memory/fixtures/questions-v1.json` has 60 development and 40 held-out
source-labelled questions. Its normalized UTF-8/LF SHA-256 is
`0ea667daadbf7de34c409598e6a7e62355fe53f1896d0533f867c03a6fedf7a0`.
The 200 source events are frozen separately in `events-v1.json`.

No inference or tuning on these questions has run. The target remains ≥95% correct
on each split and zero critical scope/authority/currentness failures. Do not
substitute the deterministic replay or fake answers for these results. No new paid
benchmark allowance follows from freezing fixtures. Real provider input/output,
request count, retries, continuation and unknown usage must be recorded.

## Windows text run

Requirements: existing Python/dependencies, SQLCipher 4.17, DPAPI, OPA, Hello helper
and configured Gemini Free credential lane on the owner's Windows machine. No
package installation, SDK/model upgrade or microphone access is performed.

Use `tools/windows/Start-JarvisProjectMemoryLab.ps1` **from the reviewed exact
commit**. Parameters:

```powershell
-RepoRoot "E:\Jarvis\App" -Commit "<reviewed-40-character-sha>" `
-Model "gemini-3.5-flash-lite" -LabRoot "$env:TEMP\jarvis-project-memory-acceptance"
```

Fetch the branch explicitly before extracting the launcher; the launcher does not
fetch/retry network access implicitly. It creates an isolated detached checkout.
The lab verifies exact clean source and a marked profile, then takes an OS-backed
exclusive profile lock. It resolves existing authority tools before changing the
profile environment. Installed checkout/settings are not reset or activated.

Type this sequence with fictional details:

1. `Let's plan my Nepal trip`
2. `We will take the Jimny. The permit is pending.`
3. `What is the status of my Nepal trip?`
4. `/inspect` — confirm original USER sources, timestamps, roles and commit sequence.
5. `/sleep`, then ask the Nepal status again.
6. `Switch to interview preparation`, then `My interview is on Monday.`
7. `Which vehicle did I choose for my Nepal trip?` — restore Nepal without interview history.
8. `Correction: the permit is now sorted.` Then ask status and inspect dated sources.
9. `New conversation in Nepal trip`, then ask for the previously chosen vehicle.
   Older project-thread evidence must be available through the local search tool.
10. `/quit`. Restart the **same command and root with `-ResumeLab`**, retaining the
    exact same commit. Hello permission is renewed; IDs/history must remain.
11. `/projects` and `/inspect`. Confirm selection announcement and source provenance.
12. `/pause`; a further statement must retain only omission metadata and send no
    dependent generation. `/resume` changes the retention epoch; do not backfill
    previously excluded text as if it were recorded.
13. `/forget` requires a separate explicit owner approval. Reopen the same profile,
    select Nepal again, and confirm deleted details do not reappear. Minimal IDs
    remain redacted to reject delayed writes; this is not forensic backup erasure.

`/inspect` is an authenticated console operation and intentionally displays its
selected private sources. Ordinary failure output includes stage and correlated
IDs rather than asking the owner to reconstruct missing speech. Do not publish
raw private console output as general logs.

A source exclusion or storage failure blocks the dependent answer and reports
failure/omission. Assistant delivery receipts describe the actual printed prefix;
a late callback is tied to its original project, never to the latest selection.
Legacy topic checkpoints are not imported as fabricated original conversations.

## Remaining owner-only gates

Real Windows lab execution, actual Hello/SQLCipher integration at the published
head, real Gemini answer/usefulness/cost/latency and the frozen model questions
remain unrun here. The implementation host has no access to the owner's microphone,
Windows session or configured provider credentials.

Native speech remains a separate blocker. The pinned Google native adapter can
generate before final transcription. The installed Google Cloud Speech STT adapter
requires credentials distinct from the Gemini API key. No separate service,
account, model download or billable speech integration is silently enabled.
Qualify compatible controlled STT → Gemini → existing TTS before claiming spoken
continuity, interruptible playback or end-of-speech latency. First-audio p95 ≤3 s
has not been measured or accepted. Keep PR draft; merging and installed activation
remain separate owner decisions.
