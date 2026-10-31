# Project conversation memory acceptance

Status: controlled **text** implementation; owner-machine and real-model acceptance
OPEN. This is not a normal-app activation or a native voice pass.

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

Latest local scoped run: **484 passed**; repository Ruff check passed. A synthetic
Linux SQLite/fake-OS run measured archive p95 **3.63 ms** (200 samples) and local
snapshot/context p95 **1.48 ms** (10 samples), with zero model requests. These are
not SQLCipher/Windows, real-authentication, provider or speech latency measurements.

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
