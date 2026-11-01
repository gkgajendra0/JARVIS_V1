# PR 303 bounded search-ranking repair

Base: `40934ffe38bba26d0e4e82087471c953b3bca657`. Provider-free follow-up to the committed six-case owner report. No frozen questions or provider calls were used for this repair.

## Problem and resulting behavior

The old archive search selected the newest matching rows. In 100/200-event synthetic histories, newer accessory messages mentioning Jimny displaced the earlier user decision even for `Jimny chose`. The initial bounded context also lacked that old decision.

Search now preserves the newest matching original per role, promotes one best distinct-term match per role, fills other slots by recency, and interleaves user/assistant evidence. It returns at most the existing eight search sources. Scope, request exclusion, authority checks and one-search/one-read tool budgets are unchanged. No schema or dependency change.

Packet admission preserves local search priority before presenting selected evidence chronologically. Priority is not serialized as source content or treated as truth. Re-reading source IDs cannot erase the positive search priority already present in the request.

## Measured offline recovery

Twenty-four real-store scenarios cover 20/100/200 events, unrelated versus repeated-keyword distractors, broad versus specific queries, and short versus 1,000-character-padded originals. Both specific-query 100/200-event cases now retain the original decision in the final packet at both text lengths. Conservative packet bounds in the crowded specific-query cases:

| Events | Padding per source | Final bound | Old decision in final context |
| --- | --- | --- | --- |
| 100 | 0 | 5,410 | Yes |
| 200 | 0 | 5,432 | Yes |
| 100 | 1,000 | 5,510 | Yes |
| 200 | 1,000 | 5,512 | Yes |

Bounds are UTF-8 payload bytes plus 32, **not provider token counts**. The final packet ceiling remains 6,000 in that conservative unit. These tests establish deterministic evidence recovery in these fixtures, not answer accuracy, semantic relevance, provider speed, billing or production acceptance.

## Review and regression evidence

Original RED: four expected recovery failures. An independent review of the first patch identified two Important issues: redundant high-term matches displaced an intervening cancellation, and long sources caused packet assembly to discard a retrieved original. Both were reproduced RED and repaired before finalization. The cancellation-after-chatter regression remains in the final suite, as do long-message recovery and recovery after a source read.

Revised scoped run: 59 tests passed. Independent re-review: 31 regression tests passed, no remaining Critical or Important findings within this repair's scope. Final full Windows pytest: **3,955 passed, 14 skipped, four dependency FutureWarnings in 295.88 seconds** using Python 3.11.9, existing dependencies, this checkout's src and an isolated machine-config path. Repository-wide Ruff, changed-file formatting and diff whitespace checks passed. Skipped boundaries are not accepted by these results.

The [raw synthetic measurements](2026-11-01-pr303-search-ranking-offline.jsonl) contain the final 24 offline cases; no user conversation, credentials or provider outputs are included.

## Limits and next gate

Single-term `Jimny` search still cannot distinguish an old decision from newer discussion. Fixed eight-hit selection can omit other historical evidence, including corrections; this is explicitly partial coverage, never proof of absence or current truth. One lexical candidate per role can replace one older recency slot. Unicode casefold versus SQLite `lower()` matching is an existing limitation. Sources too large to fit the packet remain explicitly omitted.

The earlier live answer-grounding weaknesses have not been demonstrated fixed by this retrieval repair. The next gate is limited live development evaluation of the reviewed candidate, followed by broader development qualification before the untouched held-out set. Keep PR draft; native voice, Hello usability, main merge and installed activation remain open.
