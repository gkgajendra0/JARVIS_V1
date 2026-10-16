# Step 4.4 — Three-call owner-approved Gemini smoke evidence (2026-10-16)

**Status: completed owner-machine developmental smoke; exact 3/3 approved
calls consumed. No further provider requests authorized.**

Owner executed
`step4_contextual_gemini_three_call_smoke.py --allow-three-calls --confirmed-free-tier`
from an isolated `jarvis_step4_smoke` Git worktree pinned to PR #271
commit `96267e48907b37c154f944f7f1b28cda7cf583d6`. The owner supplied
the sanitized JSON report in the conversation. No API key, actual
provider predicates, raw proposal values or response traces were shared.

## Observations — do not conflate structural intent with full acceptance

| Synthetic diagnostic | Intent | Type | Value evidence | Exact predicate target | Safe handling / pass |
| --- | --- | --- | --- | --- | --- |
| EN: original recap format was inaccurate | correction ✓ | fact_correction ✓ | supported ✓ | failed | FAILED |
| HI: a true report-schedule change | historical_change ✓ | fact_change ✓ | supported ✓ | failed | FAILED |
| Hinglish: unknown which workshop detail was incorrect; no replacement final | retraction (inappropriate without proof) | fact_retraction | not reported | no valid abstention | FAILED |

**Total**: attempted 3, completed 3, provider failures 0, fully passed
0/3. No retries, durable writes or rechecks. On the two unambiguous
examples, the declared intent/type were 2/2 correct, but target
predicates were 0/2 exact matches. Three examples cannot estimate
general model accuracy.

Important limitation: `target_matched=false` means the *freeform
provider predicate string was not exactly equal to the canonical
fixture predicate*. The report did NOT disclose the strings, so we
**cannot tell** whether Gemini produced a harmless alias, chose a
semantically wrong target, or missed the key for another reason.
Do not auto-map a single retrieved predicate to an arbitrary model
proposal; evidence of a genuine reference remains necessary.

The ambiguous Hinglish sample contained two plausible prior facts,
so treating a model-selected `retraction` as authority risks an
incorrect memory lifecycle proposal. It must clarify or abstain.

## Changes in this follow-up research branch (zero model requests)

- `review_contextual_revision_shadow` now **requires clarification
  whenever more than one current eligible canonical memory could be
  the intended revision target**, irrespective of the model's
  self-selected predicate. This deliberately decreases automatic
  coverage to protect safety until independent target-grounding exists.
- A retraction proposal without **direct withdrawal language in the
  current accepted turn** returns `needs_clarification` rather
  than conflict review. Examples like `galat tha`, `was wrong`,
  `not yet final` are NOT consent to retract. Explicit withdrawal
  only produces review, never an automatic modification.
- New disposable SQLite regression tests replicate both failure
  shapes with *fake proposals*, verified current sources and no
  provider calls. Existing exact-target and owner-source checks remain.

## Next architecture gate (not yet accepted)

Investigate *closed candidate selection* rather than free-text
canonical predicate generation. The extractor should be restricted
to selecting a member of a verified enumerated candidate list or
null/uncertain, followed by a non-model evidence check.

Dynamic JSON schema enum or typed index plus canonical server
mapping can prevent arbitrary invented key strings; they do not
alone prove a candidate is **the correct meaning**. Multiple
candidate references stay unresolved until independent evidence
or explicit clarification. This change requires contract tests and,
eventually, independently approved *new* Gemini/free-tier trials.
No reuse of the original 3 calls, provider retries, or Qwen retesting.

## Production decision

No memory writes, implicit memory admission, synthetic owner data
egress, context injection, voice activation, PR merge or D8 work is
authorized by this smoke. JARVIS's incumbent Gemini/SQLCipher/Qwen
components remain in place. The experimental shadow connection stays
disabled by default. Existing standalone Phase 4.3 memory commands
are unchanged.
