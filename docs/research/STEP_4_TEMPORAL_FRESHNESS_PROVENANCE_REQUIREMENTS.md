# Step 4 — Temporal Freshness, Current Truth, and Provenance Requirements

## Status

**RESEARCH REQUIREMENT — NOT AN APPROVED ARCHITECTURE OR IMPLEMENTATION.**

This note records Step 4 requirements agreed during research for handling latest information, changes over time, freshness, provenance, supersession, and authoritative current truth. It is a companion to:

- `STEP_4_LIVE_CONTEXT_PERSONAL_MEMORY_RESEARCH.md`
- `STEP_4_SELF_KNOWLEDGE_CONTINUOUS_LEARNING_REQUIREMENTS.md`

The central rule is:

> **Latest database update is not automatically the latest truth.**

JARVIS must distinguish when information was true, when it was learned, when it was last verified, and whether it has since been superseded, retracted, or deleted.

## Why a single `updated_at` field is insufficient

A memory record can be modified today while describing an old fact. Likewise, JARVIS can discover an old document today even though the information in it was only true years ago. Therefore recency of storage cannot be treated as recency of truth.

Example:

- JARVIS reads a 2025 document on 2026-09-04 stating that the owner had a particular configuration.
- `learned_at` is 2026-09-04.
- The source information may have been valid only in 2025.
- The record must not outrank newer verified 2026 information merely because JARVIS encountered it later.

## Temporal fields to evaluate in the Step 4 schema

The research should evaluate a bitemporal-style model with fields equivalent to:

| Field | Meaning |
|---|---|
| `recorded_at` / `learned_at` | When JARVIS learned or stored the information. |
| `valid_from` | When the information became true in the real world or system state. |
| `valid_to` | When it stopped being true; null while current if appropriate. |
| `last_verified_at` | Last time the information was explicitly or authoritatively confirmed. |
| `superseded_at` | When a newer value replaced it as current truth. |
| `updated_at` | When the database representation itself was last modified. |
| `source_created_at` | When the source artifact/event was created, if known. |
| `source_observed_at` | When JARVIS encountered the source. |

Exact field names are not approved yet; the semantic distinction is the requirement.

## Current truth versus historical truth

JARVIS must preserve useful history without confusing history with the present.

Example lifecycle:

```text
Fact A
value       = old_value
valid_from  = T1
valid_to    = T2
status      = SUPERSEDED

Fact B
value       = new_value
valid_from  = T2
valid_to    = NULL
status      = ACTIVE
```

A current-state question should retrieve `Fact B`.

A historical question such as "what was the previous value?" may retrieve `Fact A`.

This distinction is required for:

- personal preferences;
- employment/project status;
- vehicles/devices owned;
- addresses/location where appropriate;
- selected providers/libraries;
- architecture/configuration changes;
- capability availability;
- incident/repair outcomes;
- any other state that can legitimately change over time.

## Correction, historical change, retraction, and deletion are different

Step 4 must not collapse all changes into one generic update operation.

### Historical change

The old fact was once true but is no longer current.

Example: an old provider was used previously and a new provider is used now.

The old record may remain queryable as historical truth.

### Correction

The current value is replaced by more accurate information.

Whether the previous value remains as history depends on whether it was genuinely true before or merely inaccurate.

### Retraction

The owner states that a previous memory was wrong.

The invalid value must not remain usable as historical truth simply because it was once stored.

### Forget / deletion

The owner requests erasure.

The canonical record and every derived searchable representation must be removed according to the deletion policy. Hiding a record from normal retrieval is not sufficient.

## Provenance requirements

Durable information must be traceable to its source.

The schema/policy should carry or resolve at least:

- stable memory ID;
- stable source/provenance ID;
- source type/class;
- source timing;
- source authority/trust level;
- relevant session/turn/event/document/config/runtime reference;
- verification state;
- confidence where the information is inferred rather than explicit.

Step 4 therefore needs stable provenance identifiers in the conversation/event boundary. Current `ConversationTurn` does not yet provide a stable session/turn/event identity suitable for durable provenance; this remains a design requirement, not an implementation decision.

## Authority and recency must be evaluated together

JARVIS must not use a naive "newest timestamp wins" rule.

A working research principle is:

```text
explicit current owner correction / statement
        >
current authoritative system source where applicable
        >
recent verified durable memory
        >
older verified durable memory
        >
inference / reflection candidate
        >
external untrusted content
```

This is conceptual ordering, not a final scoring algorithm.

Important implication:

> **A newer weak source must not silently override an older stronger source.**

For example, a recent LLM inference cannot override an explicit owner statement simply because its timestamp is newer.

## Freshness classes

Different kinds of memory age differently. The Step 4 design should support freshness policy rather than treating all memories identically.

### Stable / effectively permanent

Examples:

- birth date;
- historically completed milestones;
- immutable accepted project decisions as historical records.

These generally do not require periodic re-verification.

### Slow-changing

Examples:

- preferences;
- employment;
- vehicle ownership;
- long-running project state;
- personal routines.

These can become stale and should be superseded cleanly when newer authoritative evidence arrives.

### Dynamic

Examples:

- active realtime provider;
- installed software/model version;
- runtime configuration;
- device availability;
- device endpoint/index;
- currently enabled capability;
- service health.

These should preferentially be read from the authoritative live/configuration/runtime source rather than trusted from old durable memory.

## Self-knowledge freshness rule

JARVIS self-knowledge must not become a stale duplicate of the repository, configuration, or runtime state.

Examples:

- Current implementation -> repository/code is authoritative.
- Current configuration -> configuration/runtime source is authoritative.
- Why a technology was chosen -> ADR/research record is authoritative.
- Past incident and successful repair -> episodic/incident memory is appropriate.
- Learned weakness such as "tracking degrades in low light" -> learned self-knowledge with evidence/confidence.

Durable self-memory may index or summarize authoritative sources for retrieval, but should not silently override them.

## `last_verified_at` is distinct from `updated_at`

A record can be edited without its truth being re-verified, and a fact can be re-verified without changing its value.

Therefore Step 4 should preserve the conceptual distinction:

```text
updated_at       = when representation changed
last_verified_at = when truth was last confirmed
```

This matters especially for slow-changing and dynamic facts.

## Retrieval behaviour

Memory retrieval should consider, before prompt injection:

1. subject/scope relevance;
2. source authority;
3. active/retracted/deleted state;
4. valid-time interval;
5. freshness / last verification;
6. supersession relationships;
7. user query temporal intent (current versus historical);
8. sensitivity/privacy policy;
9. only then lexical/semantic relevance/ranking where needed.

Semantic similarity alone must not determine current truth.

## Step 4 evaluation implications

The JARVIS-specific memory benchmark must include temporal/freshness scenarios such as:

- old fact superseded by a newer current fact;
- old source encountered after a newer fact was already known;
- newer inference conflicting with older explicit owner truth;
- correction of an inaccurate value;
- legitimate historical change where the previous state remains queryable;
- explicit retraction where the old value must not be treated as historical truth;
- explicit forget/delete and verification that no derived index returns it;
- stale dynamic self-knowledge conflicting with current runtime/configuration;
- questions explicitly asking for current state versus previous state;
- Hindi/Hinglish variants of all relevant cases.

No acceptance threshold should be invented until baseline measurements are available.

## Research direction

This requirement strengthens the case for evaluating mature temporal-memory patterns rather than inventing ad hoc timestamp logic. Graphiti/Zep's distinction between event/episode timing and fact validity is relevant evidence, while relational/bitemporal database patterns should also be researched before schema approval.

The next Step 4 research should therefore explicitly cover:

1. mature bitemporal/temporal data-model patterns;
2. conflict-resolution semantics combining authority and recency;
3. freshness-policy representation;
4. provenance-ID design across conversation, tool, repository, configuration, runtime, and memory events;
5. exact correction/supersession/retraction/deletion lifecycle;
6. benchmark cases proving that current truth, historical truth, and stale evidence are handled correctly.

No runtime implementation should begin from this note alone.