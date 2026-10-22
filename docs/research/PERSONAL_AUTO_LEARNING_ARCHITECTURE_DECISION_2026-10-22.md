# Personal automatic learning implementation decision — 22 October 2026

The owner approved the [written design](../superpowers/specs/2026-10-21-personal-auto-learning-design.md) and [Native implementation plan](../superpowers/plans/2026-10-21-personal-auto-learning.md). This record describes an unpromoted implementation candidate, not accepted production architecture.

Use native structured extraction/reconciliation behind replaceable Gemini/OpenAI adapters. Canonical conversation owns accepted input, canonical Authority owns registered delegation/one-use children, MemoryService owns admission, and the existing serial writer owns one atomic SQL transaction. Keep individual source identities, exact canonical target versions, replay receipts and category epochs. No separate vector/memory service or resident GPU model is introduced.

One local Windows Hello opens a private owner-operated session for 15 minutes maximum and 5 minutes idle. It delegates standard memory read/admit only. Every later speaker is not biometrically verified; camera/speaker shadow cannot grant permission. Do not expose open/re-enable authority as a model-selected tool. Exact destructive/private operations remain separately approved. Mode is OFF by default and APPLY also enables context while suppressing transcripts.

The process worker survives wake/provider-history retirement but not runtime close or a revoked source. Queue limit 32; source window up to four USER turns/8,000 UTF-8 bytes; at most eight validated facts; one inference in flight; extraction and reconciliation deadlines 10 seconds; receipt lifetime 30 seconds; no retries. Reconciliation reads only a complete authorized standard catalog and fails closed above 32 eligible records. That capacity limitation needs qualification before expansion. Context still releases at most four current facts / 1,800 UTF-8 bytes, with current-version checks and guarded audio. Changeable facts are last known, not proof of continuing truth or purchase motives.

Forgetting purges exact facet lineage, derived rows, per-item sources and receipts, atomically suppressing its category. Replay digests are candidate-local so another item's receipt does not retain the forgotten item's value-derived digest. Explicit mutations invalidate all pending automatic windows conservatively; re-enable does not make old input eligible again. No low-entropy value/label hash is kept in the suppression registry.

Earlier Hindsight/LangMem/classifier/retrieval experiments remain the historical evidence described in the design. Hindsight is not dismissed as universally unsuccessful; no vendor superiority claim follows from this implementation. Consider an external component only for a concrete measured gap with a comparable, fresh evaluation. Current [qualification](PERSONAL_AUTO_LEARNING_QUALIFICATION_2026-10-22.md) remains incomplete after provider failures/rate limiting and does not establish broad semantic quality. The exact current quota/reset and billing tier are unknown.

Do not merge or activate until independent review, exact-head CI, semantic/resource qualification and normal-app owner acceptance pass, followed by the owner's protected-promotion decision. Keep the accepted architecture and CAP-053 status partial until then.

## Reviewed control boundaries

One shared code-owned relation registry limits delegated reads and resolver catalogs to the approved categories, with conservative supported legacy mappings. Category vetoes persist as permission reductions without cloud inference; current-turn vetoes remain scoped to that turn. Forgetting a supported legacy vehicle/device also suppresses its category. Distinct labels/kinds preserve separate identities, and scalar updates must target exactly the registered scalar predicate.

The normal local startup accepts `--reenable-learning-category owned_item.vehicle` together with `--personal-learning apply`. Re-enable uses a separate exact-category fresh Windows Hello approval, consumed once under the canonical writer commit guard. It invalidates old source receipts, reports suppression category state without values, and is never a model tool. The original session-start consent and default-OFF behavior are unchanged.


## Targeted extraction research after measured misses

The original mixed-revision cohort exposed under-capture rather than a storage-capacity problem. Fresh development outputs specifically confused a goal objective with its active status and a reschedule with a first-time fact. Clarify the existing structured fields and use disjoint few-shot illustrations, retaining exact verbatim grounding and code-owned admission. This is a hypothesis requiring fresh qualification, not a proved quality improvement.

Primary sources reviewed: [Google LangExtract](https://github.com/google/langextract) uses examples and source alignment; its [resolver](https://github.com/google/langextract/blob/main/langextract/resolver.py) also supports fuzzy alignment. [Instructor citation validation](https://python.useinstructor.com/concepts/citation/) validates quotes but does not establish every attribute's truth. [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) supports schema guidance. None proves this application's multilingual recall. No additional framework, fuzzy write authority, model switch or resident model is adopted. The current narrow schema change costs input tokens and risks overfitting; the separately frozen45-case preliminary subset addresses that risk within remaining quota, without substituting for the full approved gate.


Natural full-category veto grammar now also supports any-of-my/about-category forms, with the same code-owned reparse and permission-reduction-only binding. This is a deterministic repair; generic semantic fact extraction remains model-based. A fresh full90-case/30-pair v4 protocol retains intermediate fictional outputs and separates current-context mismatches from admission scoring. V3 remains offline development only after exposing the privacy defect; prior provider evidence is not rescored.
