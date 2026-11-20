# Personal memory evidence retention (current rule)

**Status:** current, owner-approved 2026-11-20 (personal memory slice 1, design
revision 2, evidence option B). This is the single rule for keeping owner
words as evidence in personal memory. It supersedes the earlier "`evidence_text`
is NULL by default" statements in the Step-4 lifecycle contract (2026-09, pruned
from the tree) and in `docs/superpowers/specs/2026-10-21-personal-auto-learning-design.md`
and `docs/superpowers/plans/2026-10-21-personal-auto-learning.md`, which now
point here.

## Rule

1. **What may be kept:** only the **minimum supporting owner quote** for an
   **admitted** automatically learned fact of **`standard` sensitivity** in an
   everyday category (owned items, food and response preferences, routines,
   goals, personal facts, activities, events, plans). Nothing else is kept.
2. **How much:** the shortest validated span(s) of the owner's own words that
   support that one fact. **500 characters is a ceiling, not a target**; a
   quote is cut to the supporting clause, never padded to the limit.
3. **No widening:** this grants **no permission** to retain sensitive
   information (health, financial, anything above `standard`), unrelated
   speech, Jarvis's own replies, other people's speech, or whole turns.
   Rejected, skipped or not-yet-admitted candidates keep no quote; their
   outcome record is content-free (reason code only).
4. **One source per fact:** each fact has its own `memory_source` row and its
   own quote. Facts from the same sentence share only the turn reference,
   never a source row or quote, so forgetting one fact cannot leave its words
   inside another fact's evidence.
5. **Reference and time stay separate:** the source-turn reference
   (`canonical_ref`) and the recorded time (`observed_at`, when Jarvis was
   told) are kept as their own fields, independent of the quote and never
   used as the time the fact happened.
6. **No backfill:** quotes are captured only for facts admitted after this rule
   ships. Old conversations and existing facts are **not** reprocessed to add
   quotes.
7. **Forgetting:** forgetting a fact (fresh Windows Hello, existing path)
   deletes its lineage and its own sources with their quotes, then scrubs any
   remaining personal-memory quote that still names the forgotten item or its
   aliases (the other fact is kept; only the quote text is cleared, marked
   `evidence_removed_by_forget`). A residual check then confirms no
   personal-memory text store still holds the forgotten label or aliases:
   assertion values and normalized text, the search index, embeddings, quotes,
   learning outcome records and topic checkpoints.
8. **Explicit memory tools** (owner `remember` / `correct`) keep their
   existing behaviour: no quote is copied; the reviewed value itself is the
   record.

## Retention limits that stay explicit

- **Diagnostic logs:** when conversation diagnostics are on, `jarvis.jsonl`
  and lab logs contain transcripts and memory-decision text. Forgetting does
  not rewrite logs.
- **Backups:** rollback copies of `memory.db` (for example under
  `E:\Jarvis\Backups`) keep data, including forgotten facts and quotes, until
  those copies are deleted.
- **Project history** redacts whole rows; a shared sentence forgotten for one
  item is removed entirely from project history (span-level redaction is out
  of scope).
- **Live model context:** the current wake ends after a forget; provider-side
  retention is outside Jarvis's control.

## Enforcement

`MemoryLifecycle._ensure_source` accepts a non-empty `evidence_text` only for
an automatic-learning source (`owner_direct`, `standard`, canonical
conversation turn reference) within 500 characters; every other source still
rejects it. Learning admission (`MemoryService.admit_learning`) checks the same
conditions per mutation, and the reconciler builds the quote only from
grounded spans of the admitted fact.
