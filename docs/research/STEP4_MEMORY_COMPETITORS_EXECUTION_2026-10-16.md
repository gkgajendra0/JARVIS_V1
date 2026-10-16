# Memory competitors: executable research lane (2026-10-16)

**STATUS: DRAFT / NOT ACCEPTED. No production model, store or context path changed.**

## Why a new stacked PR

PR #260 added a synthetic post-extraction policy benchmark. Those 42
authored development cases are not a blind holdout or a genuine model
quality comparison. This stacked PR adds *real optional model/service
invocation entrypoints* and an isolated typed task compiler. It does
NOT report LangMem/Hindsight quality without real model executions.

PR #260 remains the base. Autonomous capability acquisition (D8)
remains paused. Do not merge JEV/GICC/capability acquisition branches.

## Technology choices and what is actually comparable

| Candidate | Measured behavior | Status |
| --- | --- | --- |
| Current JARVIS Phase-4.4 | Real `MemoryCandidateExtractor.extract(text=...)` with selected Gemini or OpenAI *only if explicitly called* | Opt-in runner ready; no live call by CI |
| LangMem 0.0.30 | Real `create_memory_manager`, user utterance only, typed Triple extraction into proposals | Opt-in runner ready; model dependency and key required; *no consolidation evaluation yet* |
| Hindsight 0.10.3 | Real localhost SDK `retain_batch` + `recall` against disposable synthetic bank | Opt-in runner ready; requires locally running server and its LLM; retrieval diagnostic only |
| MemCompiler-inspired task brief | Explicit trusted task need/scope + evidence gate -> minimal opaque assertion IDs | Local deterministic prototype, no learned MemCompiler model, no injected context |
| No memory | Nothing injected | Accepted passive-injection safety baseline; useful context not captured |
| JEV | Not invoked | Separate deferred challenger; PR #250's Phase-9 results do not cover memory |

LangMem functional/stateless API:
https://langchain-ai.github.io/langmem/guides/extract_semantic_memories/
Hindsight localhost/SDK API:
https://hindsight.vectorize.io/developer/api/quickstart
State-conditioned design inspiration (not replicated algorithm):
https://arxiv.org/abs/2605.07594

## Setup outside the production JARVIS environment

For provider/model experiments, use a new disposable venv on the owner
machine or an isolated runner. Use only the synthetic development cases.
LangMem may need the matching LangChain provider integration and an API
key provided through environment variables; the CLI does not create one,
select paid fallback or access JARVIS's personal database. Hindsight's
server needs its own separately approved LLM configuration, even when
the API listens on localhost.

```powershell
py -3.11 -m venv .venv-memory-comparison
.\.venv-memory-comparison\Scripts\python -m pip install "pydantic==2.13.5" "langmem==0.0.30" "hindsight-client==0.10.3"
# Install the corresponding provider integration ONLY for the selected model,
# e.g. langchain-google-genai, in this disposable research environment.
# An explicit --allow-model-calls is required for any online extraction.
.\.venv-memory-comparison\Scripts\python tools/research/step4_memory_model_comparators.py --backend langmem --model google_genai:gemini-3.5-flash-lite --allow-model-calls --max-cases 3
```

For current Jarvis baseline, its normal project dependencies must
also be installed in the chosen **disposable** environment:

```powershell
python tools/research/step4_memory_model_comparators.py --backend jarvis --provider gemini --model gemini-3.5-flash-lite --allow-model-calls --max-cases 3
```

Provider calls are **OFF by default**. Model names above are illustrative
for the account/environment; verify LangChain provider/model availability
before running. Cloud tokens may cost money. Do not use actual owner facts
or unredacted SQLCipher memory for this research.

The model CLI reads synthetic USER `utterance` fields only; it does NOT
send the fixture's expected class or pregenerated `proposal` to the
model. The executor reuses direct-user, explicit-control and secret
prefilters before any optional model call. It catches failures and
omits failed predictions rather than treating them as correct abstains.

The output can be supplied to the PR-#260 scoring harness:

```powershell
python tools/research/step4_memory_shadow_benchmark.py --challenger path-to-predictions.json
```

The scorer reports submitted coverage separately. LangMem mapping from
zero/one or more extracted triples to SKIP/REVIEW is deliberately coarse,
and current-value matches get DUPLICATE/CONFLICT_REVIEW. It is *not*
a complete update/supersession test; do not interpret favorable numbers
as proven automatic durable admission. Real 4.4 consolidation will need
multi-turn sessions with corrections and source-grounded verification.

Hindsight local probe, when its server is configured and separately
running with its LLM provider:

```powershell
python tools/research/step4_hindsight_isolated_probe.py --allow-local-server-writes --max-queries 3
```

It *refuses non-loopback endpoints*, generates a new `jarvis-dev-only-`
bank, ingests only synthetic memory hints, queries and attempts deletion
in a finally block. A failed cleanup raises; never presume success if
the server errors. This is a server-operation test (not a 4.5E relevance,
completeness or answer-utility score). Real Hindsight may call its
configured LLM as part of retain/recall and use resources on the machine.

## State-conditioned compiler

`src/jarvis/memory/task_context_shadow.py` accepts a typed task brief
with a user-turn-grounded task need and pre-eligible metadata-only memory
candidates. It filters based on existing JARVIS canonical metadata
checks, evidence support, provenance and exact task scope; returns a
bounded ordered tuple of **opaque IDs**. No source text, memory values,
answer prompt or ContextAssembler invocation is possible.

It does *not* determine for itself whether a memory truly supports
the task. `provenance_verified`, `fact_support_verified`, and
`utility_signal` are caller-supplied research inputs. Until JARVIS
can independently ground those signals and pass blind testing, a
favorable task-compiler result would be an **oracle-dependent research
simulation**, not automatic injection authority.

## Evaluation gates that are still outstanding

1. Real Jarvis/LangMem same-provider synthetic model outputs with
   versioned dependencies, failed calls counted, cold/warm latency and
   sufficient correct/negative examples. This is **not yet executed**.
2. Hindsight self-hosted isolated run with correct client/server
   compatibility and cleanup, showing useful retrieval vs distractors;
   not yet run.
3. Actual paired downstream answer-quality tests (no memory vs
   selected memory) with provenance, intent/contradiction, unrelated
   subject and high-stakes safeguards.
4. Fresh **independent unseen** English/Hindi/Hinglish labels, frozen
   methods, steering false positives and useful-memory recall gates.
   Published dev fixtures and all retired 4.5D/4.5E corpora cannot be
   used as independent acceptance.
5. Windows 11 / 16 GB RAM / RTX 5060 Ti 8 GB concurrency with real
   audio, video, wake, DPAPI and provider failures.
6. Explicit owner approval of a narrowly bounded, default-off production
   shadow in a separate PR. No implicit durable memory writes or
   automatic context injection before distinct production acceptance.

Never claim this work has activated either Phase 4.4 automatic admission
or Phase 4.5E automatic influence. JARVIS's original SQLCipher canonical
store, DPAPI, current exact recall, explicit memory operations and the
paused D8 state are unaffected.
