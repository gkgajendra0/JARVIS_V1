# Step 4.4 conversational corrections vs explicit memory controls (2026-10-16)

**Draft research only. No changes to Phase 4.3 production authorization.**

## Problem
The incumbent `is_explicit_memory_control_text` recognizes bare "that's
wrong" and Hindi/Hinglish "galat hai / galat tha" as an explicit
`CORRECT` control. Its Phase-4.4 candidate coordinator deliberately
skips all such turns. As a result, an owner may say "jo maine pehle bola
tha galat tha" without explicitly commanding a memory update, yet a
contextual candidate reviewer would never observe the statement.

## Shadow-only refinement
The new `assess_contextual_memory_boundary` uses the incumbent
recognizer but only diverts the turn to Phase-4.3 when explicit
memory-oriented instructions are present: remember, forget, inspect,
save/update stored memory, remembered items, common Hindi directives,
etc. Bare "wrong/galat" can be considered for **read-only shadow
correction review**, not durable mutation.

This logic is intentionally NOT a replacement for an authorization
policy: its only consumer is the completely disconnected contextual
shadow pipeline introduced by PRs #267–269.

Even if a bare correction goes through the extractor, it still needs
a verified, current, text-content-bound owner-memory target, and returns
only review or clarification. It cannot call `MemoryLifecycleService`
or `ContextAssembler`.

## Validated only by synthetic regression
Unit tests cover:
- informal English, Hindi and Hinglish corrections eligible for review;
- explicit memory commands routed away;
- one synthetic Hinglish utterance flowing through existing contextual
  review to verified correction *without changing the canonical row*;
- explicit command never launches the local encoder or model.

Limitations: imperative phrasing and negation in multilingual speech
are more complex than this bounded regex triage. Test outputs do not
prove true owner intent, ASR parsing, or actual LLM correctness.
A later release needs independent multilingual blind acceptance and
an explicit memory authorization review. Existing production memory
commands remain unchanged.

## Owner-machine offline readiness

An optional single-command offline preflight is included. It reuses the
existing project `.venv` (no model download), clears provider credentials
from the child process and runs only synthetic SQLite regression tests:

```powershell
powershell -NoProfile -File tools/research/step4_contextual_revision_preflight.ps1
```

Do not treat passing this script as production acceptance. A later true
accuracy evaluation requires *new* independent English/Hindi/Hinglish cases
and approved synthetic-only external model testing. Neither is performed by
the script, and no request to enable automatic memory writing is implied.
