# Step 4 memory — owner pilot evidence and next gates (2026-10-16)

**Status: research-only, draft. No activation, model admission, autonomous storage,
passive context injection or production approval.** This branch stacks on PR #261
at commit `5695fd34`. The D8/acquisition workstream stays paused.

## Results observed by the owner (not reproduced by GitHub CI)

Owner ran the **same exposed synthetic development corpus**, 18 4.4 cases
(6 English / 6 Hindi / 6 Hinglish), Gemini `gemini-3.5-flash-lite`.

| Evidence | JARVIS | LangMem |
| --- | ---: | ---: |
| Correct development labels | 14/18 | 11/18 |
| Over-review (SKIP incorrectly escalated) | 0 | 4 |
| Missed-review metric | 3 | 1 |
| Initial 18-case eligible attempts | 13 | 13 |
| Initial 18-case provider/extractor failures | 6 | 0 |
| Initial successful-call p50 latency | 3,078ms | 3,765ms |

The JARVIS 14/18 classification was **recovered across multiple owner runs**:
7 original completed model calls, 5 known pre-provider skips, two single-case
retries (c02/c04), and four later retries under one async loop (c06/c11/c13/c16).
This is NOT a single fresh 18-case run; p50 comparison is not controlled.
The repeated-loop defect is strongly suspected, but the precise API exceptions
were not captured in the first run. A fixed runner still needs owner-machine
validation with API-call budget approval. The dev set must not be repurposed
as a blind quality acceptance or used to claim generalization.

## Failure interpretation and 4.4 engineering implications

The measured errors were:

- c11 (Hindi semantic duplicate): both systems flagged a conflict rather
  than semantic identity. Current `assess_candidate_shadow` only compares
  normalized strings; it cannot prove multilingual paraphrase equivalence.
- c12 (Hinglish updated preference): JARVIS skipped a real proposed change,
  while LangMem sent it for review.
- c13 (English retraction): JARVIS skipped and LangMem returned plain review,
  rather than conflict review.
- c18 (Hinglish ambiguous correction without target): both skipped. An
  unanchored correction should *not* mutate memory. An explicit
  **needs-clarification** path may be appropriate once grounded in canonical
  preceding turns; forcing CONFLICT_REVIEW from ambiguous text alone is
  not necessarily safer.
- c04, c05, c06 and c16: LangMem proposed unnecessary reviews for
  temporary or uncertain statements.

**Do not simply rewrite the prompt until these exposed examples pass.**
The 4.4 typed proposal currently has no durable memory reference ID and the
runner exposes only `current_exact_value`, not a proven matching entity,
subject/predicate, source/version or full timeline. To handle changes and
retractions safely, a future **research-only** candidate review contract
should include independently resolved current memory IDs, meaning-preserving
paraphrase evidence, the original assertion version, temporal semantics and a
typed unresolved-reference disposition. A model must not self-authorize
source authority, mutation, deletion or sensitive persistence.

## Current branch changes

1. `step4_memory_model_comparators.py`: JARVIS extractor now runs sequential
   calls on **one managed async event loop**, with provider transport cleanup
   and sanitized failure classes. LangMem's stateless comparison remains
   unchanged. The `--allow-model-calls` gate remains mandatory.
2. `step4_hindsight_isolated_probe.py`: Hindsight's temporary bank is seeded
   with the **full 24-case synthetic context set**, even when only 3 queries
   are evaluated. Top-1 and top-3 correct source-document counts for useful
   cases, exposure of unrelated/unsafe candidate documents for negative cases,
   unknown/missing provenance, and p50/p95 latency are now reported.
   Results depend on the server actually returning `document_id`, and remain
   development-only retrieval diagnostics, **not answer improvement or
   permission to inject**. A local Hindsight service with its own configured
   LLM is required to measure live behavior.
3. Added fake-client regression tests for loop reuse, mid-run exceptions,
   provably ungrounded Hindsight results, source provenance, distractor
   seeding and disposable-bank cleanup. No production code is imported into
   a voice or context release path by these changes.

## Step 4.5E: task-conditioned memory use is still unresolved

The existing `compile_shadow_plan` returns **opaque IDs**, not a real
injection candidate or memory value. Provenance, fact support, task need,
utility score and task scope are currently **caller-supplied**. It cannot
demonstrate independent task necessity. The earlier 24-case scope probe
selected all 8 useful cases but also 4 unsafe-steering and 2 unnecessary
ones. This is precisely why scope matching or retrieval alone cannot
promote memory into the model's response.

Next research requires a genuinely independent task-need signal and an
answer-effect verifier comparing **no memory** against relevant eligible
memory. Use fresh holdouts, current-turn primacy, temporal validity,
zero observed unsafe steering with denominator and confidence bounds,
per-language strata, no cloud upload of personal data by default, and
strict no-write/no-release failure behavior.

## Exact tests (no model/API calls)

On the **separate owner-machine worktree**, after fetching this branch,
invoke `tools/research/setup_step4_memory_windows.ps1 -SkipInstall`.
The script runs regression tests and Ruff without provider credentials.
An independent real Gemini rerun is OPTIONAL, consumes quota, requires
explicit owner approval and a fixed call budget. It must be measured
as a new run, not blended with the previous 14/18 results.

Hindsight local server access and `--allow-local-server-writes` similarly
require an explicit opt-in. The Hindsight SDK runs against localhost,
but its server may still call cloud models.

## Decision

- Keep canonical JARVIS SQLCipher/DPAPI and explicit memory operations.
- Maintain existing 4.4 non-durable quarantine; no auto-admission.
- Keep LangMem/Hindsight as isolated research comparators.
- Fix runner lifecycle, then validate new multilingual temporal reviews.
- Do not merge these research PRs to `main` or activate 4.5E/D8.
