# Step 4.4 correction and duplicate grounding: research-only contract

**Status: unapproved shadow evidence experiment. Not an acceptance result.**

## Why needed
Owner's exposed synthetic 18-case, real-Gemini development comparison showed:
- c11: Hindi semantic duplicate misclassified as conflict by both JARVIS and
  LangMem. String normalizing alone cannot establish paraphrase identity.
- c12: changed Hinglish preference missed by JARVIS.
- c13: English retraction missed by JARVIS, misclassified by LangMem.
- c18: Hinglish unanchored correction skipped by both.

A code fix that simply maps exposed utterance wording to gold labels would
overfit the dataset. We need independently resolved, versioned canonical
target evidence before proposing a change, and explicit clarification when
the target is unknown.

## This PR's deliberately limited implementation

`src/jarvis/memory/revision_shadow.py` is a dependency-free, research-only
decision function receiving:
- Direct accepted owner-turn status and normal-sensitivity classification.
- A **caller-supplied** revision intent (new candidate, duplicate suspect,
  change, correction, retraction or none).
- An optional, opaque `CanonicalRevisionWitness`: versioned assertion ID,
  canonical source reference, active status, verified owner authority,
  verified subject/predicate identity, and independently verified semantic
  equivalence (True/False/unknown).

It returns one of SKIP, REVIEW, DUPLICATE, CONFLICT_REVIEW or
NEEDS_CLARIFICATION, with a reason code only. **No model call, memory text,
database read/write, actual correction or context release is possible.**

Key rules:
1. Untrusted source, sensitive data, inactive/unverified reference: SKIP.
2. New, source-eligible candidate with no conflicting witness: REVIEW only.
3. Ambiguous correction/retraction without a resolved target:
   NEEDS_CLARIFICATION, not guessed fact mutation.
4. Verified versioned target and lifecycle change: CONFLICT_REVIEW only.
5. Semantic duplicate only when independent, subject-matched canonical
   equivalence proof is supplied; without proof, NEEDS_CLARIFICATION.
6. Verified differing existing value: CONFLICT_REVIEW, no silent overwrite.

## Critical limits

This is not a real multi-turn resolver: `RevisionIntent`, all `verified`
witness booleans and the canonical assertion reference are **provided by
the test caller**. No model or database currently computes them.
This remains an oracle-like *contract*, not evidence of improved 14/18
Gemini extraction results. The live extractor may still skip retractions
before this reviewer sees them.

Future production-quality research requires a trusted resolver reading
canonical authoritative records, detecting old/active/future versions,
handling verified Hindi/Hinglish paraphrases, checking resolved identity,
correcting the extractor's temporal intents, and an independently sealed
multilingual acceptance set. Do not expose owner data to a cloud
comparison, update/erase memory, or enable passive injection here.

## Relationship to D8

The owner clarified D8 was deferred after **complex TV capability
acquisition** proved beyond the reliable end-to-end task workflow; this
does not rule out bounded self-evolution. D8 remains a separately
controlled, unactivated track. Step 4 memory research must not be used
to re-enable it.
