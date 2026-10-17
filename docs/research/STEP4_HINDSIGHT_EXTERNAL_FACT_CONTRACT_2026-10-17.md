# Step 4 — Hindsight external-fact integration contract (2026-10-17)

**Research-only; zero provider calls, zero Hindsight server interaction, zero
canonical JARVIS memory access. The initial POC is an OFFLINE archive and
integrity-contract test, NOT a live Hindsight engine acceptance.**

## Motivation and existing work

Keep the proven SQLCipher/DPAPI owner-memory store and the existing
Qwen/FTS5 retrieval and Gemini structured extraction. Do not repeat the
old Qwen benchmark or use the three already consumed Gemini smoke calls.
Hindsight's supported external-fact import can reuse facts extracted
elsewhere, so test the data-interface compatibility before any model
install or automatic consolidation research.

Official API specification (Oct 2026):
https://hindsight.vectorize.io/developer/api/memory-banks
- `POST /v1/default/banks/{bank_id}/transfer/import`, mode=`merge`
- ZIP: `manifest.json`, `documents/<id>.json`
- Document: `id`, `original_text`, `chunks`, `facts`
- Fact: `text`, `fact_type` (`world` or `experience`), `chunk_index`,
  `mentioned_at`, `occurred_start`, `entities`, per-fact `metadata`.
- Operation submission is async and **not success** until polled to
  `completed`. Import re-embeds facts, resolves entities and fires webhooks
  and automatic consolidation if those are enabled.

## Implementation

`src/jarvis/memory/hindsight_transfer_shadow.py`:
- Frozen, hard-coded fictional Atlas workshop / Nile project facts.
- A correction, actual schedule change, unrelated venue, and both
  predecessor records. No fabricated ambiguous correction is admitted.
- Stable source-turn IDs and assertion IDs, bounded version lineage,
  UTC timestamps, explicit revision kinds, `world` fact type, and source
  scope written into per-fact metadata.
- Bounded deterministic ZIP produced in memory only, with no network,
  no API imports, no server hooks, no filesystem/database writes.
- One fact per document: using document conflict=`skip` on a future
  fresh bank avoids overwriting an unrelated fact. Reimports into the
  same bank must still be evaluated against the real server.
- Archive read-back independently checks the pinned identity, original
  source text, recorded dates and lineage. It does **not** verify a
  Hindsight server's treatment of that data.

`tests/test_memory_hindsight_transfer_shadow.py`:
- ZIP structure, provenance/time/version integrity, deterministic bytes,
  duplicate IDs, unauthorized identifiers, bad timestamps, tampering
  detection and ambiguous/no-change non-admission.

`tools/research/step4_hindsight_external_fact_preflight.py`:
- Zero-network command. Prints only aggregate counts, checksum and flags,
  never source values.

Run from research checkout (no Hindsight server, no key or PyPI install):
```powershell
& C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe tools\research\step4_hindsight_external_fact_preflight.py
& C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe -m pytest -q tests\test_memory_hindsight_transfer_shadow.py
```

## Crucial third-party configuration risk

Hindsight's default bank settings may enable observations and
`enable_auto_consolidation=true`. External-fact ZIP import can trigger
automatic consolidation and associated LLM usage. **A local URL is not
proof of zero cloud calls.**

Before any actual server import, a SEPARATE owner-approved phase must:
1. Use a fresh disposable isolated Hindsight server and fresh PostgreSQL
   database, never JARVIS's working database.
2. Disable automatic consolidation at server startup
   (`HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=false`), and confirm the
   target bank's **resolved** config also has
   `enable_auto_consolidation=false`, since per-bank overrides can win
   over server defaults. Disable other autonomous model features/webhooks.
3. Confirm all configured embedding/entity resolution/inference backends
   are local and offline, and network egress is blocked or audited;
   server `localhost` does not guarantee local-only downstream inference.
4. Create a new research-only bank with no webhook/mental-model template.
5. Import the pinned synthetic ZIP using mode=`merge` and
   document_conflict=`skip`; **poll** the operation and verify status,
   counts, evidence metadata, original document IDs and historical state.
6. Record failures and **delete the created bank** with proof of cleanup.
   On uncertain cleanup, stop; don't leave an unobserved recurring job.
7. Evaluate consolidation in a **separate** explicitly approved phase,
   with bounded local inference and no state migration.

## Decision boundary

Offline ZIP validation proves only interchange *schema shape*, not actual
SDK/API version compatibility, semantic target accuracy, Hindi/Hinglish
performance, deduplication, temporal consolidation or server idempotency.
It does not make Hindsight a production memory authority.

Do not merge draft research into main, enable implicit writes, import
real owner memories, turn on D8, or use external paid providers.
Cost to validate this code in GitHub CI and local Python: ₹0 in new
service/API fees (machine electricity excluded).
