# Personal-context delivery and usefulness qualification — 20 October 2026

The next personal-assistant slice now has actual fictional-data evidence: the
configured Gemini voice model can automatically choose relevant canonical facts
and use them in ordinary English, Hindi and Hinglish dinner advice. Simply
attaching a memory tool did **not** achieve that behavior. An explicit automatic
context-use instruction to the isolated test agent made the difference.

This is a bounded experiment and an offline-tested proposal adapter, **not a
production APPLY implementation or owner-identity acceptance**. Main and machine
settings remain unchanged. The separate reviewed repair candidate is PR #292;
this work starts from its `7b7ea56b` revision without merging it.

## What was measured

The [evidence manifest](../../benchmarks/results/personal_context_delivery_2026-10-20/manifest.json)
preserves raw fictional results, hashes and reference-only experiment source.
All cloud inputs were fictional. Temporary databases used canonical migrations,
MemoryService and SemanticRetrievalService; they never opened owner memory.
Microphones, cameras and real action tools were not used.

| Experiment | Actual observation | Interpretation |
|---|---|---|
| Repaired original probe | Fictional canary appeared in the captured model answer | One delivery path works; an instruction-triggered answer is insufficient evidence for normal conversation |
| No-context control | Unknown in all 3 language cases | No accidental canary knowledge in those cases |
| Initial history | Correct canaries in all 3 language cases | Working startup delivery on the pinned stack |
| Mid-session history plus ordinary user input | Unknown in all 3 language cases | Not qualified for integration; an awaited update is not proof of answer use |
| Tool-result follow-up | Correct English/Hinglish tokens and correct Hindi transliteration | Tool results can inform a separate automatic follow-up generation |
| Structured text relevance | All attempted selections unavailable; SDK timeouts and HTTP 503 diagnostic | Semantic selector quality remains NOT_MEASURED; empty unavailable results are not successful abstention |

Stack: configured `gemini-3.8-live`, `livekit-agents` / Google plugin 1.8.3,
`google-genai` 2.22.0. No dependency upgrades or provider/model substitutions.

The historical matrix predates two evaluator corrections and is retained as raw
diagnostic evidence. The current comparison uses the pinned `AgentSession.run`
boundary to await automatic post-tool generations and preserves session/failed-turn
usage. It separately reports literal canary matches and fixed Hindi spoken aliases.
Neither canary occurrence nor an SDK return value is a personalization score.

## Ordinary personal advice

[Experiment V1](../../benchmarks/results/personal_context_delivery_2026-10-20/voice-advice-v1.json)
captured three baseline answers and three answers with the fictional memory tool
available, followed by correction and deletion checks. On ordinary dinner questions
the model never called the tool. English context advice suggested chicken even
though the saved fictional preference was vegetarian. A question explicitly asking
to consider the current preference did call the tool and gave suitable vegan advice.

[Experiment V2](../../benchmarks/results/personal_context_delivery_2026-10-20/voice-advice-v2.json)
added an automatic-context-use instruction **only to the fictional test agent**:
consult relevant saved facts before personal recommendations, even when the user
does not explicitly request a memory search. Tool choice was not forced.

| Question/condition | Model-selected facts | Captured answer |
|---|---|---|
| English dinner advice | diet preference + food restriction | Paneer butter masala and garlic naan |
| Hindi dinner advice | diet preference + food restriction | Vegetarian paneer dinner, in Hindi |
| Hinglish dinner advice | diet preference + food restriction | Vegetarian paneer dinner, explicitly peanut-free |
| Current preference corrected to vegan | corrected diet + food restriction | Vegan tofu/vegetable stir-fry, avoiding peanuts |
| Diet/restriction deleted; fresh provider session | No diet fact released | Honestly said the saved preference was unknown |

The unrelated headphone budget was not selected in these four tool reads. Each
used one tool call; the model proposed facet indices and canonical current reads
validated the records. A separate fixed fictional assertion allowlist bounded
cloud release in the experiment. It did not export a PI-1B shadow packet or
establish authority for real owner data.

The deletion answer was in English despite a Hinglish question: language adherence
is not fully qualified. V2 session times, including startup and cleanup, were
6.25–13.125 seconds. This is not a warm-session latency result or release threshold.
Adapter-reported usage is retained; billed cost is unknown, not zero. Adapter TTFT
values are not an independently measured user-perceived first-response latency.

These small exploratory cases show a useful behavior and an important failure.
They do not establish held-out quality, broad language coverage, injection resistance,
guest safety, interruption/reconnect correctness or long-running reliability.

An independent review of all 13 advice sessions confirmed V1 ordinary-question
retrieval was 0/3 and V2 was 3/3 in these single observations. Compatible vegetarian
answers without a tool call were not counted as personalization. English/Hindi dish
names do not establish peanut handling; even the explicit peanut-free statements
do not prove ingredients or preparation. Correction used an explicit current-preference
request in a fresh session. Deleted-fact abstention involved no exact tool lookup
and proves neither history erasure nor revocation in a populated provider session.
There were no general/third-party negative cases in the advice experiment; the
separate unavailable structured-selector cases cannot supply those results.

## Code supplied

- An offline-by-default four-session comparison CLI. Real sessions require
  `--allow-four-real-provider-tests`; each session has a bounded timeout and
  stops the matrix on transport failure.
- `GeminiPersonalFacetSelector`, conforming to PI-1B's existing selector protocol:
  it proposes at most four eligible owner-personal facet indices from names only.
  It validates strict types, membership, duplicates and consistency, with bounded
  question/catalog/payload sizes and provider wait. The canonical coordinator
  retains eligibility and release policy. The caller owns the SDK client.
- Network-free regressions for these behaviors, automatic post-tool answers,
  Hindi aliases, cleanup, timeout, failure sanitization and retained partial usage.

The structured relevance adapter is not active in voice. The native realtime-tool
experiment is a separate supported PI-1C path; its success does not qualify the
unavailable structured-text adapter.

## Verification and remaining release work

Related network-free tests: **40 passed** after correcting both independent review
findings. Repository lint, formatting and dependency consistency passed. The first
full run had 2,568 passes, 8 skips and one existing 30 ms Pocket 3 BLE timing failure;
the exact test passed alone without a BLE code change. Final full-suite verification
after both review corrections: **2,571 passed, 8 skipped in 263.39 seconds**.
No BLE code or test was changed. Final repository lint and formatting checks passed;
remote checks are tracked on the review PR separately from these local results.

The independent code review found a preamble/post-tool wait gap and dropped usage
on failed turns. Both were reproduced RED and corrected GREEN. Experimental live
quality and production release were outside that code review's verdict; they need
their own evidence.

Next implementation should reuse the existing native reader, tool boundary and
accepted-turn lifecycle. It needs a trusted owner/turn binding before real private
release, bounded in-flight reads with revalidation, and an actual reversible APPLY/OFF
bridge. Prefer the measured tool-result path over assuming arbitrary mid-session
history replacement works. Because Gemini cannot remove prior messages, correction,
forgetting, identity loss and OFF require an explicit provider-history invalidation
strategy and fresh-session qualification; local deletion alone is insufficient.

Structured-text HTTP service availability, independent held-out answer review,
real spoken owner-machine behavior, applicable authority acceptance and protected
promotion remain prerequisites to activation. Automatic learning, indiscriminate
capture, new memory servers and local fine-tuning were not enabled.

Implementation references checked against the installed source and official
[LiveKit Gemini guide](https://docs.livekit.io/agents/models/realtime/gemini/),
[tool guide](https://docs.livekit.io/agents/logic/tools/) and
[Gemini Interactions migration guide](https://ai.google.dev/gemini-api/docs/migrate-to-interactions).
Installed-source behavior and actual experiment results govern claims about this
pinned runtime; current documentation alone is not qualification.
