# Step 4 — Bake-off Results

## Status

**EVIDENCE IN PROGRESS — THESE RESULTS DO NOT APPROVE THE FINAL STEP-4 ARCHITECTURE.**

This document records measured evidence for the Step-4 technology decision. Results must distinguish between reference-environment measurements and measurements from the real JARVIS Windows machine.

The reproducible research harness is:

- `tools/research/step4_memory_sqlite_bakeoff.py`

No runtime code under `src/jarvis` is changed by the bake-off.

## 1. SQLite temporal + FTS reference-environment spike

### Purpose

Test whether plain SQLite can satisfy the important canonical-memory mechanics before adding a temporal database server, graph database, or vector database:

- current fact lookup;
- valid-time history;
- system/learned-time history;
- historical change versus correction;
- FTS5 English/Hindi/Hinglish lexical retrieval;
- explicit-forget deletion from canonical + derived FTS representations;
- low-latency local lookup at a scale much larger than the expected early personal-memory corpus.

### Reference environment

The initial research execution used Python's built-in SQLite 3.46.1 in the research execution environment, not the owner's Windows JARVIS machine.

Corpus size: **30,000 synthetic fact records**.

### Temporal correctness

The spike passed all tested assertions:

1. At an old system time, JARVIS can recover what it believed at that time.
2. After a genuine preference change, current knowledge can retain the old value for the old valid-time interval while exposing the new value as current truth.
3. After a correction, current knowledge can answer the historical period using the corrected value while a system-time query can still show what JARVIS had previously believed.
4. The test therefore supports the required distinction between **when a fact was true** and **when JARVIS learned/believed it**.

This validates the *pattern*, not the final production schema.

### Reference latency

30,000-record corpus:

| Query | p50 | p95 | Maximum observed |
|---|---:|---:|---:|
| Exact structured current-fact lookup | ~0.008 ms | ~0.009 ms | ~0.35 ms |
| FTS5 English (`wake detector` + `TV`) | ~3.25 ms | ~4.84 ms | ~7.44 ms |
| FTS5 Hindi (`रिसर्च` + `implementation`) | ~3.45 ms | ~5.12 ms | ~7.32 ms |
| FTS5 Hinglish (`existing technology` + `Jarvis`) | ~2.89 ms | ~3.20 ms | ~4.28 ms |

These numbers are **not acceptance thresholds** and must not be used as Windows performance guarantees. They show only that there is no evidence yet that SQLite/FTS5 is too slow for this workload class.

### FTS5 deletion finding

The reference SQLite build supports the FTS5 `secure-delete` configuration. A dedicated forget-path test also verified zero normal FTS hits and zero canonical rows after physical deletion of an isolated test memory.

Important caveat: the real JARVIS Python/SQLite build must be tested because FTS5 feature availability depends on the SQLite version bundled with that Python environment.

Relevant SQLite documentation:

- https://www.sqlite.org/fts5.html
- https://www.sqlite.org/wal.html

### Current conclusion

**KEEP SQLITE + FTS5 AS THE LEADING CANONICAL/LEXICAL CANDIDATE. DO NOT ADD XTDB/QDRANT/GRAPHITI/LANCEDB TO THE RUNTIME YET.**

Reason:

- the temporal semantics required by JARVIS are representable with the mature bitemporal pattern;
- structured lookup is trivially fast in this scale test;
- lexical FTS remains comfortably small in this reference test;
- SQLite WAL is designed to allow readers and a writer to progress concurrently on the same host, with one writer at a time, which matches JARVIS's expected low write concurrency;
- additional database services would add operational, failure, security, synchronization, and self-diagnostic surface without measured benefit yet.

This conclusion remains provisional until the Windows rerun and retrieval-quality bake-off are complete.

## 2. Retrieval-quality bake-off — pending

Latency is not enough. FTS5 should be expected to miss semantic paraphrases where important words do not overlap.

The next retrieval bake-off must compare:

1. exact structured lookup;
2. FTS5 BM25;
3. FTS5 + one local multilingual embedding candidate;
4. FTS5 + the alternate embedding candidate;
5. add a vector engine only if the embedding path proves useful enough to justify it.

Current embedding candidates retained for the bake-off:

- Qwen3-Embedding-0.6B;
- BGE-M3.

The corpus must include English, Hindi, Hinglish, semantic paraphrases, stale facts, superseded facts, and absent-answer/abstention cases.

## 3. Structured memory-candidate extraction — pending

Current research supports using provider-native structured outputs rather than building an ad-hoc parser.

Evidence:

- OpenAI supports JSON-Schema Structured Outputs.
- Gemini structured outputs support JSON Schema and Pydantic-based Python schemas, while explicitly recommending application-level semantic validation even after schema validation.

Sources:

- https://openai.com/index/introducing-structured-outputs-in-the-api/
- https://ai.google.dev/gemini-api/docs/structured-output

The bake-off must measure **semantic correctness**, not merely valid JSON:

- correct candidate classification;
- false durable-memory candidate rate;
- missed explicit remember/correct/forget commands;
- extraction of temporal meaning;
- preservation of uncertainty;
- refusal to treat assistant/external content as user truth;
- English/Hindi/Hinglish behaviour;
- latency and token cost.

## 4. Encryption / Windows packaging — pending owner-machine spike

SQLCipher remains the leading whole-database encryption family, but the Python/Windows packaging decision is not approved.

Current finding:

- the `sqlcipher3` 0.6.2 PyPI project has CPython 3.11 Windows x86-64 wheels;
- PyPI marks those uploads as **not using Trusted Publishing**;
- therefore convenience alone is not enough to approve that dependency for long-lived personal memory.

Source:

- https://pypi.org/project/sqlcipher3/

The Windows spike must compare a vetted/official build path, key handling, backup/recovery, and the existing JARVIS DPAPI concept before any real personal memory is stored.

## 5. Self-knowledge / SBOM — research update

Use the maintained `cyclonedx-bom` tool directly rather than the older `CycloneDX/gh-python-generate-sbom` GitHub Action. The Action documents itself as deprecated in favour of the underlying tool.

Current `cyclonedx-bom` 7.3.1 is a production/stable Python tool and can build SBOMs from Python environments and package manifests. This is a better solved primitive for installed-dependency self-knowledge than maintaining a handwritten dependency list.

Sources:

- https://pypi.org/project/cyclonedx-bom/
- https://github.com/CycloneDX/gh-python-generate-sbom

A JARVIS-specific capability registry is still required because an SBOM can describe software/dependencies but cannot express product semantics such as `voice.listen`, authority boundaries, diagnostic tests, or known operational limitations.

## 6. Remaining evidence required before "research complete"

Research is complete only after all of the following are measured or explicitly dispositioned:

- [x] requirements and lifecycle research;
- [x] memory-framework landscape research;
- [x] first SQLite bitemporal correctness spike;
- [x] first SQLite/FTS reference latency spike;
- [ ] rerun SQLite/FTS spike on the actual JARVIS Windows environment;
- [ ] multilingual retrieval-quality bake-off;
- [ ] OpenAI/Gemini memory-candidate extraction bake-off;
- [ ] SQLCipher/DPAPI Windows encryption/package spike;
- [ ] CycloneDX SBOM + JARVIS capability-registry self-knowledge spike;
- [ ] consolidate measured results into a final technology decision;
- [ ] prepare final architecture proposal for human approval.

No production Step-4 memory implementation begins before the final technology decision and architecture approval.
