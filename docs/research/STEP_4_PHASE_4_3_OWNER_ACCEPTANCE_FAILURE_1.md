# Step 4 — Phase 4.3 Owner Acceptance Failure 1

## Status

**REAL OWNER-PC CROSS-SESSION ACCEPTANCE: FAILED — DETERMINISTIC KEY NORMALIZATION GAP IDENTIFIED AND FIXED; RETEST REQUIRED.**

This is an acceptance-learning record, not a rollback of the SQLCipher/DPAPI technology decision.

## What passed before the failure

On the real JARVIS Windows PC, the retained SQLCipher 4.17.0 wheel was installed after exact SHA-256 verification and the production memory adapter smoke passed with:

- SQLCipher `4.17.0 community`;
- SQLite `3.53.3`;
- schema migration and FTS5 checks passing;
- DPAPI-protected key present;
- plaintext stdlib SQLite open blocked;
- no synthetic marker visible in DB/WAL/SHM/key artifacts;
- final adapter status `PASS`.

The normal voice runtime then started with explicit persistent memory enabled and accepted the harmless synthetic command equivalent to:

`Remember that my phase 4 test city is Sagar.`

The process was fully stopped and restarted before recall, so the next read was a real cross-process test rather than LiveContext reuse.

## Failure observed

The owner then asked the equivalent of:

`What do you remember about my phase four test city?`

The provider called exact inspect with predicate:

`phase_four_test_city`

and `MemoryService` returned:

`no current memory for predicate 'phase_four_test_city'`

The assistant therefore reported no recollection.

## Root cause

Phase 4.3 intentionally uses deterministic exact structured keys and does not permit fuzzy/semantic target resolution. The original key canonicalizer normalized Unicode, case, punctuation, and separators, but did not normalize spoken number words.

Therefore these semantically identical exact target phrases became different canonical keys:

```text
phase 4 test city    -> phase_4_test_city
phase four test city -> phase_four_test_city
```

This is a deterministic normalization defect at the exact-key boundary. It is not evidence of SQLCipher persistence failure.

## Research-first correction

Existing libraries were rechecked before implementation.

Selected: `number-parser==0.3.2`.

Reasons:

- purpose-built deterministic natural-language number normalization;
- in-place conversion of number words to digits;
- English and Hindi cardinal-number support;
- Python 3.11 support;
- OS-independent pure-Python wheel;
- BSD license;
- production/stable classifier and extensive upstream tests;
- avoids inventing a custom number-word parser inside JARVIS.

The newer `text2num` package was also reviewed and is active/fast, but its documented language set does not include Hindi. JARVIS Phase 4.3 already has English/Hindi/Hinglish owner interaction requirements, so `number-parser` is the better fit for this narrow deterministic normalization layer.

## Implemented correction

The canonical memory surface now:

1. applies Unicode NFKC;
2. converts English number words to digits;
3. when Devanagari is present, converts Hindi number words to digits;
4. case-folds;
5. applies the existing exact deterministic predicate canonicalization.

The same normalization is reused by the voice-tool argument grounding layer, so the model cannot bypass grounding merely by changing `four` to `4` or vice versa.

Examples now intentionally converge:

```text
phase 4 test city     -> phase_4_test_city
phase four test city  -> phase_4_test_city
चरण चार परीक्षण शहर   -> चरण_4_परीक्षण_शहर
```

No fuzzy target resolution, embedding lookup, or semantic guessing was introduced. Existing stored key `phase_4_test_city` remains readable because recall-side normalization now converges onto that same key; no database migration is required for this specific acceptance record.

## Observability improvement

Safe memory-tool logging was also added for owner acceptance:

- successful remember: operation + predicate + memory ID + sensitivity;
- successful correction: operation + predicate + memory ID + sensitivity;
- successful forget: operation + predicate;
- successful inspect: predicate + sensitivity + verification state;
- stored values are not written to these logs.

This makes future acceptance evidence distinguish a real durable tool commit from a model-only acknowledgement.

## Regression coverage

Tests now explicitly reproduce the owner failure:

1. remember `phase 4 test city = Sagar`;
2. query `phase four test city`;
3. exact inspect must resolve the same canonical key and return `Sagar`.

Additional tests verify English numeric-word equivalence and Hindi numeric-word normalization.

## Acceptance disposition

Phase 4.3 remains **ACTIVE**, not complete.

The owner does not need to re-create the synthetic memory before the first retest if the original remember actually committed under `phase_4_test_city`; the corrected recall path should be able to read it. Safe operation logging on the corrected build will provide clearer evidence for subsequent mutation stages.

Required next gate after CI is green:

- owner pulls the corrected branch and installs the newly declared `number-parser==0.3.2` dependency;
- restart normal JARVIS voice runtime with persistent memory enabled;
- ask the same `phase four test city` recall question;
- if recall succeeds, continue correction -> restart -> forget -> restart acceptance sequence.
