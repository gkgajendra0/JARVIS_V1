# Approved native personal-context shadow boundary

The owner approved **"Approve read-only test mode"** on 2026-10-19, including
measuring native JARVIS before memory-service adapters. This branch implements
the first read-only boundary and a repeatable fictional probe. It preserves
existing memory ownership and exact-fact recall. It does not yet give live JARVIS
new context, general advice relevance or automatic memory capture.

## Implemented behavior

- OFF by default. An explicit test caller can enable SHADOW; no APPLY mode exists.
- Bind the request to the latest accepted USER turn and session, with an independent
  trusted owner-identity observer. Guest requests do not reach memory selection.
- Ask the existing query coordinator for one bounded canonical fact. Require an
  explicit admitted owner source and the personal owner subject. Resolve text and
  provenance locally; assistant claims and inferred profiles cannot become facts.
- Re-read exact eligible canonical state after selection. Corrections, forgetting,
  expiry, conflicts, source changes, future facts and disallowed sensitivity cause
  abstention. Open-ended time-sensitive observations need a future refresh contract.
- Respect local/cloud eligibility and a conservative UTF-8 byte budget with framing.
  Those units are not provider billing tokens. Do not truncate facts to fit.
- Bound reads by deadline, propagate caller cancellation, invalidate pending reads
  on reconnect/OFF, discard stale turns and suppress duplicate turn events.
  At most one source read may remain outstanding; a cancellation-resistant provider
  causes `source_busy` rather than accumulating further requests.
- Keep packets transient. The operational summary omits personal values, utterances
  and private exception messages. No provider, executor or memory-writer handle is
  supplied to the selector, and no production configuration is changed.

The source uses `MemoryQueryCoordinator` (or its existing provider-verified wrapper),
`SemanticRetrievalService` and `CanonicalMemoryReader`. The reader gains a narrow
read-only immutable-provenance lookup; it grants no independent release permission.
`ready` means a checked shadow snapshot. Any future APPLY consumer needs its own
fresh source and turn validation immediately before release.

## Repeatable local probe

From the repository root, run:

```powershell
& .venv\Scripts\python.exe -I tools\research\personal_context_shadow_probe.py
```

The command uses a disposable fictional SQLite store with the real memory schema,
lifecycle, query coordinator and shadow selector. It does not read production
configuration or live memories and makes no model, network or hardware calls.
Its planner supplies controlled exact-facet proposals; it tests software contracts,
not whether a model understands natural everyday requests.

The [observed run](../../benchmarks/results/personal_context_shadow_probe_2026-10-19.json)
passes 13 scenarios: default OFF, exact fact, duplicate, correction, forgetting,
local-only cloud exclusion, local release, guest exclusion, unsupported advice,
budget, deadline, reconnect and closed session. Timing fields are local operation
times, not retrieval-model or first-spoken-output measurements.

## Configured native model smoke

A separate [one-query native smoke](../../benchmarks/results/personal_context_native_model_smoke_2026-10-19.json)
also ran against the machine's existing Gemini `gemini-3.8-flash` memory route.
The production planner and semantic verifier classes both completed using a
disposable fictional store. The coordinator allowed the exact saved coffee fact;
the selector returned the correct canonical value in shadow mode.

This used two logical SDK calls, with 1,304 total tokens reported by the provider
(1,023 input, 87 output, 194 thought tokens), and approximately 7,000 ms for the
complete selection. No lab retry, alternate provider or settings change occurred.
Currency cost and SDK wire retry count were not observed. Raw planner/verifier
outputs were not retained; the artifact preserves the coordinator decision,
fictional fixture, numeric usage and normalized implementation hashes.

This verifies one real configured-route lookup. It is not a native 20-case answer
baseline or evidence that adding context synchronously before speech is acceptable.
These two calls are additional to the earlier context diagnostic's 47 inference
attempts; all earlier successes and failures remain preserved separately.

## Voice bridge finding and remaining delivery

The actual voice session still uses provider-native turn completion, with
`TurnHandlingOptions(turn_detection=None, preemptive_generation.enabled=False)`.
The canonical bridge exposes accepted-turn observers and deduplicates provider
items. A local event test attaches a shadow-only observer, delays selection until
after an interrupted assistant response, and verifies one selection and zero
provider context updates. It preserves canonical USER truth through false VAD
activity and assistant output.

This is an in-process event simulation. No live provider/audio run occurred and
time to first spoken output is unmeasured. An accepted-turn observer alone does
not prove that evidence can reach a realtime model before its response. The
existing Gemini 3.1 context policy also declares initial-history-only support.
No hook or turn-detection configuration was changed to conceal this limitation.

The next bridge slice must establish a supported provider-specific delivery seam
and demonstrate late-result rejection, interruption/reconnect behavior and voice
timing on the owner machine before APPLY. Broader advice selection, current Work
and session context, native model/answer comparison, held-out cases and external
service lifecycle trials remain open. This work does not select a vendor or mark
CAP-053 accepted.

## Verification

The final local Windows suite passed **2,528 tests / 8 skipped** after review fixes.
The shadow module has **40 focused checks**; the four existing provider-verifier
checks also pass. Full repository Ruff format/lint checks pass (931 Python files).

Independent review found two important failures: upstream verifier error logging
could expose private exception details, and cancellation-resistant timed-out reads
could accumulate. All three reproducing tests failed before fixes and pass now.
The verifier logs static error messages without traceback; selection bounds pending
reads at one. The reviewer checked both fixes and found no further blocking issue.
The initial additional late-read race was likewise reproduced and fixed before review.

Production voice activation and owner-machine speech timing remain untested; local
regression/probe success does not establish CAP-053 acceptance. The existing draft
PR receives fresh exact-head CI before any protected merge.
