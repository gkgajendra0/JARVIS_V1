# Existing repositories for Gemini-directed local memory

**REFERENCE research; no backend replacement selected.** The [current contract](../PROJECT_CONVERSATION_MEMORY.md) reuses existing Jarvis storage/retrieval first. These repositories are component references for a demonstrated gap, not instructions to install a new service or repeat technology benchmarks.

Date: 2026-10-30. Status: source inspection, not installation, benchmark, security audit or accepted Jarvis integration.

## Question and constraints

Find implementations of automatic conversation capture, local persistence, model-directed retrieval, project separation and shared personal context. Preserve the owner's latest constraint: API bills are already high. Do not introduce a paid hosted agent as the recommended baseline, rebuild a complete memory framework, or repeat the previous Hindsight/LangMem/retrieval experiments.

The search connector failed. Public GitHub repository metadata, READMEs, directory trees, implementation files and integration documentation were fetched directly. No package was installed, no owner records were uploaded and no memory-model inference was run.

## Findings

### 1. MCP Memory Service — strongest low-additional-API-cost backend candidate

Repository: https://github.com/doobidoo/mcp-memory-service

Inspected implementation:

- `services/memory_service.py`: `store_memory` and `retrieve_memories` expose reusable application functions. `conversation_id` is stored in metadata and skips semantic deduplication. Exact content-hash deduplication remains; the hash is generated from content. Therefore the service must not be assumed to preserve distinct repeated turns or project identities as a lossless chronological archive by itself.
- `storage/sqlite_vec.py` composes the SQLite backend. `storage/mixins/base.py` opens standard `sqlite3` connections, not Jarvis's canonical SQLCipher workers. Encrypted storage/authority compatibility requires an adapter or an explicitly permitted isolated derived index. Do not silently duplicate owner content into plaintext.
- `embeddings/onnx_embeddings.py` performs local ONNX embedding inference and can download the model on first setup. Local store/search therefore need not require another paid inference provider. Optional model-backed summaries are separate and should remain disabled for the cost-constrained baseline.
- `web/api/search.py` includes semantic search, tag queries with all/any matching, time filtering and store partitions. Project scope must be imposed by the Jarvis wrapper before search; agent-controlled arbitrary tags or a project name are not an authorization boundary.
- `harvest/auto_capture.py` explicitly uses `PatternExtractor`, a confidence threshold, selected harvest types and a `dry_run=True` default. This is selected-learning extraction, not unconditional full conversation capture. Claude/Gemini CLI integration is not proof of Gemini LiveKit compatibility.

Fit: Gemini can request memory searches through Jarvis functions backed by this service/library. It removes the need to invent another local retrieval engine. Jarvis must still supply accepted turn events, project identity, current authority and response ordering. Keep an exact source archive separate from content-deduplicating retrieval records.

Source links:
- https://github.com/doobidoo/mcp-memory-service/blob/main/src/mcp_memory_service/services/memory_service.py
- https://github.com/doobidoo/mcp-memory-service/blob/main/src/mcp_memory_service/harvest/auto_capture.py
- https://github.com/doobidoo/mcp-memory-service/blob/main/src/mcp_memory_service/embeddings/onnx_embeddings.py
- https://github.com/doobidoo/mcp-memory-service/blob/main/src/mcp_memory_service/storage/mixins/base.py
- https://github.com/doobidoo/mcp-memory-service/blob/main/src/mcp_memory_service/web/api/search.py

### 2. Memori — closest automatic Gemini-client capture pattern

Repository: https://github.com/MemoriLabs/Memori

Its BYODB Gemini documentation shows a `google-genai` client registered with Memori and a local SQLite SQLAlchemy connection. It lists sync/async/streamed `generate_content` methods. Attribution includes entity/process IDs and sessions. This is a direct example of LLM understanding plus externally managed persistence; it does not prove that a Live WebSocket voice client is intercepted.

`llm/pipelines/post_invoke.py` calls `MemoryManager.execute(payload)` after a response and separately schedules augmentation. `memory/_manager.py` distinguishes cloud persistence from local storage. `memory/augmentation/augmentations/memori/_augmentation.py` calls `Api.augmentation_async`; `_network.py` targets Memori service endpoints. Advanced augmentation cannot be described as local-only merely because the database is local. Its API/quota/deployment requirements and disabling/replacing that component need resolution before adopting it under this owner's cost constraint. No price or mandatory-fee claim is inferred from source alone.

Also note capture is post-response in the inspected pipeline. It does not establish a committed-before-reply guarantee, crash-safe recording before an unfinished response, or correct Jarvis protected-audio lifecycle.

Fit: strongest reference for automatic client capture and session attribution. Conditional candidate rather than an unrestricted zero-cost drop-in.

Source links:
- https://github.com/MemoriLabs/Memori/blob/main/docs/memori-byodb/llm/gemini.mdx
- https://github.com/MemoriLabs/Memori/blob/main/docs/memori-byodb/databases/sqlite.mdx
- https://github.com/MemoriLabs/Memori/blob/main/memori/llm/pipelines/post_invoke.py
- https://github.com/MemoriLabs/Memori/blob/main/memori/memory/augmentation/augmentations/memori/_augmentation.py
- https://github.com/MemoriLabs/Memori/blob/main/memori/_network.py

### 3. LongMemory, formerly the Cavira OpenMemory repository — strongest project/session primitives

Repository: https://github.com/CaviraOSS/LongMemory

The previous `CaviraOSS/OpenMemory` URL redirects here. Readme and project-memory documentation describe local SQLite, project worlds, decisions, tasks, sessions, scoped recall and HTTP/MCP/Python surfaces over a TypeScript engine.

`core/project/project_sessions.ts` implements actual session import with project IDs, role validation, timestamps, individual message IDs and source metadata; it is not just a screenshot feature. It rejects reimporting an existing session ID, so incremental append/retry behavior still needs an adapter design. `core/project/project_recall.ts` implements scoped project recall. `core/engine/claim_extractor.ts` includes deterministic parsing rules; do not assume a frontier LLM understands every personal utterance inside this engine.

`docs/embeddings.md` distinguishes API/local semantic embeddings from deterministic multilingual hashing. The no-external-call fast/hybrid modes are not proof of neural semantic retrieval quality. Ollama/local-HTTP configurations can avoid paid embedding APIs but require their own local model/runtime. Hindi/Hinglish quality and Windows behavior were not benchmarked here.

Fit: richer ready-made project structures than a bare memory server; more operational surface than the Python backend candidate. It still requires real voice-event capture and SQLCipher/authority bridging. Synthetic vectors must not be mistaken for an established improvement over Jarvis's tested retrieval.

Source links:
- https://github.com/CaviraOSS/LongMemory/blob/main/docs/project-memory.md
- https://github.com/CaviraOSS/LongMemory/blob/main/src/core/project/project_sessions.ts
- https://github.com/CaviraOSS/LongMemory/blob/main/src/core/project/project_recall.ts
- https://github.com/CaviraOSS/LongMemory/blob/main/docs/embeddings.md

### 4. Basic Memory — local inspectable knowledge/projects, less direct for voice history

Repository: https://github.com/basicmachines-co/basic-memory

README describes local Markdown files, SQLite/Postgres search, local FastEmbed embeddings, optional reranking and explicit `bm_write`/`bm_edit` tools. Project and client-capture integrations exist, but note-taking/capture hooks are not automatic Jarvis voice recording. Current README lists Python 3.12+ while Jarvis uses 3.11, and local Markdown is not the existing encrypted store. A separate service/runtime and storage policy would be needed. Good reference for inspectable knowledge; not the first replacement for Jarvis's archive path. Metadata/README identify AGPL-3.0 rather than the Apache license of the other two local-backend candidates.

### 5. SimpleMem — useful research, not the low-extra-inference baseline

Repository: https://github.com/aiming-lab/SimpleMem

README documents dialogue ingestion, memory construction/compression, adaptive retrieval, Python/MCP use and configurable local/OpenAI-compatible providers. It explicitly requires an OpenAI-compatible API configuration before the described memory construction/retrieval path. Local models are possible in its deployment options, but this is still an additional model-backed memory pipeline to operate. Do not confuse lower downstream prompt-token claims with zero total ingestion/embedding/reading cost. No new SimpleMem benchmark was run.

## Practical recommendation

These repositories establish that the requested pattern exists. We do not need to invent a complete memory framework. None of the inspected code proves a drop-in replacement for Jarvis's particular encrypted, authorized, realtime voice path.

Use MCP Memory Service as the first component-fit reference for cost-constrained local search/tools, Memori as the automatic capture reference, and LongMemory when project/session primitives justify a TypeScript service. This is a fit shortlist, not a measured quality ranking or authorization to migrate all owner data.

Before choosing a backend, check only the integration differences that matter: exact chronological source preservation, source/project scoped retrieval, current SQLCipher connection ownership, correction/forget propagation and Gemini Live tool delivery. Reuse the existing Jarvis retrieval if the adapter adds no measured benefit; do not discard accepted work simply because a repository advertises similar capabilities.

For any chosen component, the unavoidable Jarvis wrapper is bounded: accepted-turn recorder, stable project/session binding, authorized store/search/read functions, and a context-before-answer boundary. Gemini selects semantic queries and interprets evidence. Record every accepted eligible original turn independently of optional memory extraction.

Source snapshots are uninstalled `main` reads. Inspected tree objects (not release versions): Memori `574b1ea3e876f100ef82c37817d603eb7e258e59`; MCP Memory Service `c187ec5cd67ee103725c7fdd9ee8acaa0bc2ee8e`; LongMemory `8badf44d48d0d72a07e1ea3daf1ecbd76ae1a357`; Basic Memory `d7b16128351e8eb6570fe38f7b006d433f5e8d62`. Pin reviewed release/commit identities before implementation; repository marketing benchmarks are not Jarvis acceptance results.
