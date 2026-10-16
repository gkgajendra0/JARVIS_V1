# Step 4.4 — Closed canonical predicate selection (2026-10-16)

**Research-only draft, no model calls or production changes.** Stacked on
#272, which recorded the owner-approved three-call Gemini smoke as
**3 completed, 0/3 full passes**, no more approved provider requests.

## Problem

The contextual Gemini extraction output uses the incumbent
`MemoryExtractionProposal.predicate: str | None`. That allows the model to
invent or paraphrase predicate names, while canonical JARVIS requires
exact validated keys. The English and Hindi synthetic smoke returned
correct intent, type and supported new values, but 0/2 exact target
predicates matched. The sanitized report did **not** reveal whether
those strings were semantic aliases or different targets.

## This change

For **Gemini contextual research calls only**, the adapter:
1. Parses its already-verified contextual memory candidate list
   (bounded to three).
2. Builds a request-local JSON schema using the already-existing
   `MemoryExtractionProposal` schema except for `predicate`, which
   becomes an enumerated **exact candidate key or null**.
3. Independently validates the returned predicate against the same
   allowlist. If the provider ignored the enum or returns an invented
   key, the adapter fails closed without any rewrite.
4. With an explicitly empty candidate list, no revision target may be
   invented; the revision coordinator continues to require a canonical
   target. The normal production extractor is unchanged.
5. The canonical reviewer in #272 still refuses multi-target revision
   proposals without independently verified target evidence, even if
   an LLM selected a member of the enum.

## Evidence and limitations

New fake-Gemini SDK tests check dynamic allowed-key schema,
post-provider rejection, two-candidate allowlisting, zero-candidate
guard and `store=False`. No API call, provider key, full owner-memory
corpus, Qwen benchmark or state write is performed.

This is a **proposal**, not proven Gemini Interactions API schema
compatibility or improved real inference accuracy; the first provider
test of this adjusted schema would require **fresh owner approval**,
a confirmed Free-tier key, and a newly bounded budget.

Importantly, a matching key proves only that a model copied one of
the supplied keys. It does **not** prove the owner meant to revise
that memory. Multi-candidate ambiguous references still require
clarification, and exact one-candidate cases can still be unrelated.

Production deployment, admission, correction, automatic memory
deletion and response-context injection remain prohibited.
