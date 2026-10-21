# Memory intention and canonical-target repair — 21 October 2026

Implemented on `feat/personal-intelligence-runtime-20261020`, in draft PR #294.
This is a bounded repair of the existing normal-app personal-memory path. The
owner approved implementation followed by their own full local-app testing.
Protected main and the accepted production architecture are unchanged.

## Problem and resulting behavior

The owner's supplied logs show a successful `diet_preferences` save, an explicit
correction-intent rejection, then a lookup for the different `diet_preference`
key and a rejected remember fallback. They do not contain the spoken text; no
claim is made about the exact utterance. Reproductions confirmed that “Update
my diet preference to vegan” and natural Hindi/Hinglish changes failed the old
affirmative command matcher even though they clearly propose a correction.

In APPLY mode, the existing realtime model now interprets a natural correction
or deletion as a proposal. It uses the owner-approved catalog to select the
actual existing canonical record by opaque catalog token and facet index. The
user need not pronounce an internal key or the word “correct.” Ambiguous targets
require clarification; unresolved targets cannot silently become new memories.
The new value must be grounded in the latest accepted utterance, in its original
script. Plain statements, hypothetical and third-party remarks are not approved
automatic learning. New remembers retain their explicit-save intent requirement.

The owner separately approves the resolved target and full proposed value through
fresh Windows Hello. The permit binds the target version, value and sensitivity
by digest; canonical transactions recheck both approval and current record.
An old request cannot rebind to a newer turn after an awaited lookup. Superseded
records cannot be overwritten or deleted through a stale selection.

Catalog and direct lookup both require read consent before accessing target
metadata. An existing-memory change can therefore require **two approvals**:
resolve/read, then approve the concrete write. Read permission alone never grants
write authority. Private/local-only records remain outside the automatic catalog;
explicit direct changes retain the narrower path. History still retires after
one personal answer, requiring another wake. OFF retains its legacy intent gate.

## Review and regression evidence

Independent review of `0958174..a2219c6` found two Important issues and one Minor
diagnostic mismatch. Failing regressions reproduced each before fixes:

- Failed/cancelled remembers now clear the in-flight mutation and retire protected
  history rather than leaving audio permanently blocked in an open session.
- “Meri diet preference mat hatao” and “मेरी खाने की पसंद मत हटाओ” are vetoed
  before a deletion approval. This veto supplements semantic proposals; it is
  not claimed to be an exhaustive natural-language intent parser.
- Successful mutation logs now contain operation/status/turn only, without the
  predicate, record ID, proposed value or utterance.

Additional regressions cover consent-before-direct-lookup and mandatory concrete
write payloads. The related memory/context/authority group passes **66 tests,
1 skipped**. Review fixes are regression-verified, not independently re-reviewed.
No dependency, schema, model/provider substitution or parallel memory store was
introduced. Final full local suite: **2,636 passed, 8 skipped in 170.99 seconds**.
Repository lint, formatting, whitespace and dependency consistency checks pass.
Exact-head CI evidence is recorded on PR #294 and the portable verification report
after publishing the candidate.

## Actual native-model measurement

A bounded text-only experiment used the real production tool bundle and configured
`gemini-3.8-live`, temporary fictional canonical data and synthetic consent. It
did not open microphone/camera, owner storage, Windows Hello or the full app.
The existing record deliberately used plural `diet_preferences`; requests used
different natural wording. Actual tools and canonical postconditions, rather
than compatible answer text alone, established these three observed successes:

| Input | Canonical value after actual model/tool execution | Whole turn |
| --- | --- | --- |
| Update my diet preference to vegan. | vegan | 6.547 s |
| Ab main vegan hoon, meri saved diet preference badal do. | vegan | 8.062 s |
| मेरी पहले से सेव खाने की पसंद बदलकर वीगन कर दो। | वीगन | 8.016 s |

All three selected `personal_context_catalog` then `correct_memory` and received
`ok: true`. These times exclude real human approval and physical audio playback.
One negated request returned `RealtimeError` without a completed answer or tool
call; it is **inconclusive**, not a passed semantic negative case. Usage events
were available, but billed cost was not measured. This small sample does not
establish held-out multilingual quality, ASR fidelity, all-language support,
provider reliability or owner-perceived spoken latency.

The remaining two cases completed: “If I became vegan, how might my meals change?”
and “My friend is vegan. What could they eat?” Both produced general answers,
made no memory tool calls or consent proposals, and left the canonical preference
unchanged. Their text turns took 12.406 and 15.843 seconds respectively. Overall:
five observed expected outcomes, one provider-inconclusive case; no failed case
is counted as passing. The deterministic negative-change regressions pass.

## Normal local-app acceptance

After updating the same candidate branch, run the existing app:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-context apply
```

Use an existing fictional preference or explicitly save one, then wake again
and naturally ask to update it in your preferred language. Approve only the
intended concrete change; wake again and ask a personal question to check the
current value. Check deletion and a restart similarly. An incorrect or ambiguous
proposal should be denied/clarified. There is no need for a separate microphone
test harness. Owner spoken acceptance and explicit protected-main promotion
remain open; this repair does not complete the whole personal-intelligence goal.
