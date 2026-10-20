# Normal JARVIS personal-context integration — 20 October 2026

The first active read slice is implemented in
`feat/personal-intelligence-runtime-20261020`, based on delivery candidate
`4abe0ec974a96fdcc792cde2251ace9fe19d2b18` / draft PR #293, stacked on repair
PR #292. Protected main is unchanged. This is a normal-app integration, not the
earlier fictional delivery CLI. It does not complete the whole personal-assistant
North Star, automatic learning or seamless speaker recognition.

## Behavior supplied

- Normal `jarvis-voice --personal-context apply` constructs real per-session
  tools, canonical memory reads, consent state and the actual audio output guard.
- The existing realtime model is instructed to select relevant personal context
  for ordinary advice in English/Hindi/Hinglish, even without a search command.
  General knowledge and third-party requests should not consult owner facts.
- Catalog names require fresh exact-request Windows Hello approval through the
  existing capability/OPA/permit broker. Cached T2 is insufficient. A model sees
  names first, proposes indices, then receives current canonical values.
- Only STANDARD owner-explicit/direct/verified facts are eligible. PRIVATE,
  LOCAL_ONLY, prohibited secrets, inferred sources, ambiguous current facts and
  unverified time-sensitive assertions are excluded. The catalog is partial and
  cannot prove that the owner has no other constraints.
- Bounds: 8,000 UTF-8 request bytes, 128 names (128 UTF-8 bytes each), four facts
  and 1,800 value bytes per answer. Catalog IDs are opaque and turn-bound;
  repeated reads cannot accumulate additional facts.
- New speech, a new canonical turn, close, expiry, Windows continuity loss or
  changed/deleted released facts revoke output. Actual audio frames pass the
  lease/current-fact guard. A watchdog also clears queued private audio.
- Provider history is closed after one personal answer. Wake JARVIS again for
  another request. This avoids pretending that the pinned Gemini adapter can
  erase populated session history. It adds Hello and wake friction.
- Explicit remember/correct/forget retain grounded intent/operand checks, add
  fresh owner consent in APPLY, and retire history after acknowledgement. The
  canonical writer rechecks consent/request state in its transaction before
  mutation and before commit, including writes that waited in a queue.
- OFF remains the default; `--personal-context off` disables the new automatic
  path. Persisted `JARVIS_PERSONAL_CONTEXT_MODE` follows normal machine precedence;
  an explicit CLI choice wins for that process. APPLY enables memory and disables
  transcript logging/SDK recording without changing saved settings.

No dependency, schema, model/provider substitution or second memory store is
introduced. No separate structured HTTP selector must be available. The isolated
PI-1B shadow packet still cannot be exported to a provider. Speaker/active-speaker
scores remain SHADOW and never grant authority.

APPLY explicitly supplies the SDK's same bundled local Silero VAD. The default
SDK path also turns Gemini's synthetic tool-follow-up interruption event into
"user speaking"; that cannot be used as evidence of new physical speech. Final
answer completion uses speech-handle completion, not intermediate "listening"
states emitted during tool execution. Gemini tool-bearing handles are intermediate
and its separate automatic final-reply handle retires the private session.

## Verification boundary

Network-free tests use fictional data in temporary canonical databases. They
exercise correction/deletion, strict proposals, private exclusions, cumulative
bounds, late/cancelled/timed-out consent, repeated same-text turns, denial versus
unavailable/absent data, lock loss, actual chained AudioOutput forwarding and
listener cleanup, queued write rollback, CLI non-persistence and OFF behavior.

The normal runtime session method is exercised in English, Hindi and Hinglish:
it constructs the actual tool bundle/output guard, starts the session with SDK
recording disabled, calls real tools against canonical fixtures, forwards approved
audio and closes the session. The model proposal is synthetic in these tests;
they prove wiring and release behavior, not actual semantic selection quality.
Earlier actual fictional Gemini advice evidence remains separately documented in
[delivery qualification](PERSONAL_CONTEXT_DELIVERY_QUALIFICATION_2026-10-20.md).

Final local full suite after review fixes: **2,609 passed, 8 skipped in 256.32s**.
Repository lint, formatting, whitespace and dependency consistency pass. The
installed `jarvis-voice.exe --help` exposes the actual APPLY/OFF switch without
launching audio. Exact-head remote CI is tracked on the integration PR; owner
local spoken acceptance and protected promotion remain open. No microphone,
owner database, real Hello prompt or production app is started by this run.

Independent whole-branch review found three Important issues and no Critical or
Minor issues at the reviewed pre-fix head: a final-await interruption race in read
and audio release, premature retirement on intermediate SDK listening, and Gemini
tool-follow-up events being mistaken for new human speech. Each was reproduced
with a failing test before its fix. The expanded 37-test context/production/activity
group passes, including actual pinned AgentActivity provider-event behavior and
real SpeechHandle completion. Existing ordinary authority/voice behavior is
covered by the full repository suite. The post-review fix pass is verified by
tests; it was not independently re-reviewed.

## Implementation decisions and limits

1. Existing exact-request Hello consent is the initial owner-authority fallback;
   shadow biometric scores remain diagnostics. Cost: extra approval and wake
   friction until seamless owner-speaking attribution is qualified.
2. A correction/deletion after facts reached the provider closes that conversation,
   rather than injecting a new result into stale history. Cost: a fresh wake.
3. An optional commit guard extends the existing MemoryService/lifecycle so queued
   mutations can roll back after interruption. Cost: a small optional API surface;
   existing callers retain their behavior.
4. Actual Hello, owner DB, microphone and live-model quality remain the owner's
   requested local-app acceptance. Tests establish software wiring and policy;
   they cannot establish owner-perceived spoken usefulness or latency.
5. The implementer verifies the full suite and the post-review fixes. Protected-main
   acceptance remains a separate owner decision. No minor review findings were
   deferred.

## Owner local-app acceptance

Use the existing configured PC and normal app, from the candidate branch:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-context apply
```

With an empty database, first give an explicit fictional remember command, such
as “Remember my diet preference is vegetarian.” Approve that exact request in
Windows Hello. Wake JARVIS again and ask ordinary personal questions in your
preferred language. Correct or forget explicitly and check after a new wake and
after restarting. This is normal-app acceptance, not a special test harness.
Do not infer personalization from a compatible answer alone: it should actually
use the relevant current fact, be honest when unavailable/unknown and respect
language. Generic advice remains possible when consent or facts are unavailable.

Remaining product work: actual local spoken acceptance, broader held-out relevance
and latency/cost quality, protected promotion, qualified seamless owner-speaker
follow-ups, and separately governed natural learning. Do not label these complete
because implementation/automated checks pass.
