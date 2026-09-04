# Step 4 — Bake-off Results

## Status

**EVIDENCE IN PROGRESS — THESE RESULTS DO NOT APPROVE THE FINAL STEP-4 ARCHITECTURE.**

This document records measured evidence for the Step-4 technology decision. Results distinguish between reference-environment measurements and measurements from the real JARVIS Windows machine.

Reproducible harness:

- `tools/research/step4_memory_sqlite_bakeoff.py`

No runtime code under `src/jarvis` is changed by this bake-off.

## 1. SQLite temporal + FTS bake-off

### Purpose

Test whether plain SQLite can satisfy the important canonical-memory mechanics before adding a temporal database server, graph database, or vector database:

- current fact lookup;
- valid-time history;
- system/learned-time history;
- historical change versus correction;
- FTS5 English/Hindi/Hinglish lexical retrieval;
- explicit-forget deletion from canonical + derived FTS representations;
- low-latency local lookup at a scale much larger than the expected early personal-memory corpus.

### 1.1 Reference-environment result

Initial research execution used Python's built-in SQLite 3.46.1 in the research execution environment.

Corpus size: **30,000 synthetic fact records**.

Temporal semantics passed all tested assertions:

1. at an old system time, JARVIS can recover what it believed then;
2. after a genuine preference change, the old value remains valid for its historical interval while the new value is current truth;
3. after a correction, current knowledge uses the corrected historical value while a system-time query can still recover JARVIS's earlier mistaken belief;
4. therefore the relational bitemporal pattern can represent the required distinction between **when a fact was true** and **when JARVIS learned/believed it**.

Reference latency:

| Query | p50 | p95 | Maximum observed |
|---|---:|---:|---:|
| Exact structured current-fact lookup | ~0.008 ms | ~0.009 ms | ~0.35 ms |
| FTS5 English | ~3.25 ms | ~4.84 ms | ~7.44 ms |
| FTS5 Hindi | ~3.45 ms | ~5.12 ms | ~7.32 ms |
| FTS5 Hinglish | ~2.89 ms | ~3.20 ms | ~4.28 ms |

These reference numbers are not acceptance thresholds.

### 1.2 Real JARVIS Windows-machine result — PASS

The owner reran the exact research harness on the actual JARVIS Windows/Python 3.11 environment on **2026-09-04**.

Result:

```json
{
  "status": "PASS",
  "purpose": "research-only; not a production architecture approval",
  "python_sqlite_version": "3.45.1",
  "seed_records": 30000,
  "seed_seconds": 0.5354,
  "temporal_semantics": {
    "old_system_knew_old_tyre": true,
    "current_system_knows_historical_tyre": true,
    "current_system_knows_current_tyre": true,
    "old_system_exposes_pre_correction_belief": true,
    "current_system_uses_corrected_history": true
  },
  "fts_secure_delete": {
    "supported": true,
    "detail": "enabled for research FTS table"
  },
  "latency": {
    "exact_current_fact": {
      "p50_ms": 0.0165,
      "p95_ms": 0.0186,
      "max_ms": 0.2087
    },
    "fts_english": {
      "p50_ms": 4.0938,
      "p95_ms": 4.6056,
      "max_ms": 6.1346
    },
    "fts_hindi": {
      "p50_ms": 4.3506,
      "p95_ms": 4.695,
      "max_ms": 6.0042
    },
    "fts_hinglish": {
      "p50_ms": 3.7851,
      "p95_ms": 3.9048,
      "max_ms": 4.1437
    }
  },
  "forget_zero_recall": {
    "before_delete_fts_hits": 1,
    "after_delete_fts_hits": 0,
    "after_delete_canonical_rows": 0
  },
  "database_bytes": 16928768
}
```

Interpretation:

- **Temporal correctness passed on the real machine.** Both historical-change and later-correction semantics behaved as required.
- **FTS5 `secure-delete` is available** in the actual bundled SQLite 3.45.1 environment.
- **Explicit forget passed zero-recall verification** for the tested isolated record: zero canonical rows and zero normal FTS hits after deletion.
- Exact current-fact lookup remained effectively negligible for the intended runtime path.
- English/Hindi/Hinglish FTS p95 remained below 5 ms in this 30,000-record local test.
- The resulting test database was ~16.9 MB, which gives no current storage-size concern at this scale.

These numbers are still measurements, not hard production thresholds. They establish that there is currently **no performance or feature evidence requiring a heavier canonical database**.

Relevant SQLite documentation:

- https://www.sqlite.org/fts5.html
- https://www.sqlite.org/wal.html

### Current SQLite disposition

**KEEP SQLITE + FTS5 AS THE LEADING CANONICAL/LEXICAL CANDIDATE. DO NOT ADD XTDB/QDRANT/GRAPHITI/LANCEDB TO THE RUNTIME YET.**

Reason:

- required temporal semantics are representable using the proven bitemporal relational pattern;
- that pattern passed on the actual JARVIS Windows environment;
- structured lookup is comfortably fast at the tested scale;
- local English/Hindi/Hinglish lexical retrieval is comfortably fast at the tested scale;
- FTS5 secure-delete is supported on the real machine;
- the tested forget path removed both canonical and derived searchable representation;
- SQLite WAL matches the expected low-write-concurrency, same-host JARVIS workload;
- additional database services would currently add operational, failure, synchronization, security, and self-diagnostic surface without measured benefit.

This is still provisional until retrieval quality and the other remaining Step-4 bake-offs are complete.

## 2. Retrieval-quality bake-off — pending

Latency is not enough. A small lexical probe already demonstrated expected FTS5 misses when a semantic paraphrase has weak word overlap, including concepts such as:

- `which device gives Jarvis eyes?` versus a stored camera fact;
- `meri bike kaunsi hai?` versus a stored motorcycle fact.

This gives a measured reason to evaluate semantic retrieval instead of adding embeddings by convention.

The next retrieval bake-off must compare:

1. exact structured lookup;
2. FTS5 BM25;
3. FTS5 + Qwen3-Embedding-0.6B;
4. FTS5 + BGE-M3;
5. a dedicated vector engine only if semantic retrieval proves valuable enough to justify additional runtime state.

The corpus must include English, Hindi, Hinglish, semantic paraphrases, stale facts, superseded facts, and absent-answer/abstention cases.

## 3. Structured memory-candidate extraction — pending

Current research supports using provider-native structured outputs rather than building an ad-hoc parser.

Evidence:

- OpenAI supports JSON-Schema Structured Outputs;
- Gemini structured outputs support JSON Schema and Pydantic-based Python schemas, while recommending application-level semantic validation after schema validation.

Sources:

- https://openai.com/index/introducing-structured-outputs-in-the-api/
- https://ai.google.dev/gemini-api/docs/structured-output

The bake-off must measure semantic correctness, not merely valid JSON:

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
- PyPI marks those uploads as not using Trusted Publishing;
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
- [x] rerun SQLite/FTS spike on the actual JARVIS Windows environment;
- [ ] multilingual retrieval-quality bake-off;
- [ ] OpenAI/Gemini memory-candidate extraction bake-off;
- [ ] SQLCipher/DPAPI Windows encryption/package spike;
- [ ] CycloneDX SBOM + JARVIS capability-registry self-knowledge spike;
- [ ] consolidate measured results into a final technology decision;
- [ ] prepare final architecture proposal for human approval.

No production Step-4 memory implementation begins before the final technology decision and architecture approval.
