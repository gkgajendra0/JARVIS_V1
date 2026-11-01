# Project Search Ranking Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Recover specific old evidence without losing latest matching corrections.

**Architecture:** Scope/filter in SQLite, retain newest matching source per role plus one best lexical match, fill remaining slots by recency, interleave roles and return selected evidence chronologically. Preserve admission priority through packet byte-budget selection.

**Tech Stack:** Python 3.11, SQLite window functions, pytest.

**Spec:** ../specs/2026-11-01-project-search-ranking-design.md

## Global Constraints

Keep existing authority, scope, eight-result search and packet limits. No real provider calls, frozen fixture edits or installed activation.

## Review Focus

- Latest matching user correction with fewer query terms must remain available.
- Assistant echoes must not displace all original user evidence.
- Duplicate query words must not amplify relevance.
- Single-term and no-match behavior remain bounded and chronological.
- Foreign projects and the current question must be filtered before ranking.

## Task 1: Ranking repair and recovery evidence

Files: `src/jarvis/memory/project_access.py`, `src/jarvis/memory/project_context.py`, `tests/learning/test_pr303_scaling_probe.py`, `tests/learning/test_project_search_ranking.py`.

Interface: existing `ProjectArchiveAccess.snapshot(...)` and `ProjectMemoryTools.search_conversation_memory(project_id, query)` remain unchanged.

- [x] Convert specific-query crowded scenarios to positive recovery assertions; make JSONL reporting optional for normal pytest runs.
- [x] Add real-store regression cases for lexical relevance, duplicate terms, matching corrections and assistant echoes. Reuse existing scope and current-request exclusion tests, adding a high-relevance foreign-source case.
- [x] Run regressions RED and confirm old-decision absence is the expected failure.
- [x] Implement parameterized term coverage and per-role recency anchors in snapshot SQL.
- [x] Run scoped GREEN checks, the project suite with isolated machine config, Ruff and formatting. Record actual failures and environmental limitations.
- [x] Review final diff and package a patch, measurements and report. Keep PR draft and installed checkout unchanged.

## Execution ledger

Base: `40934ffe38bba26d0e4e82087471c953b3bca657`, isolated `review/pr303-context` checkout.

Ruling: reuse the existing isolated clone rather than create another worktree; it is already separate from installed main and holds the diagnostic fixture.

Ruling: no additional design confirmation is needed; the owner explicitly approved the proposed narrow ranking repair and regression/offline sequence. Single-keyword limitations are stated before implementation.

RED: original implementation produced four expected failures (two crowded specific-query recovery misses; two original-plus-correction echo cases), 11 passes.

Initial GREEN: 43 scoped tests passed. Added foreign-project/current-request high-relevance checks: two additional passes.

Independent review found two Important issues: relevance displaced a cancellation after newer chatter, and byte-budget admission discarded old relevant evidence. Both were reproduced as failing tests (one correction case; two 1,000-character packet cases).

Ruling: promote just one lexical candidate per role then refill by recency, instead of ranking every remaining slot by term coverage. Retain local-only source priority through packet admission. This preserves the tested correction and end-to-end recovery without expanding the eight-hit result or 6,000-byte conservative ceiling; it cannot guarantee all corrections in arbitrary histories.

Revised GREEN: 59 scoped tests passed; stable-order cleanup then 11 context/ranking tests passed; Ruff and formatting passed for four changed Python files. Independent re-review reproduced 31 passing regression scenarios and found no residual Critical or Important issue within scope.

Full-suite first attempt was interrupted after approximately 60% without observed failures because review changed the candidate. Fresh full run on final production code: **3,955 passed, 14 skipped, four dependency FutureWarnings in 295.88 seconds**. It used the existing Python 3.11.9 venv with this checkout's src and a separate machine config path. Repository-wide Ruff passed; changed-file formatting and staged diff whitespace checks passed. Skipped boundaries remain unqualified; this is no claim of real provider/Hello/SQLCipher acceptance for the new candidate.
