# Contextual Hybrid HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing reactor-centric read-only HUD into a truthful, contextual view of canonical JARVIS operational state.

**Architecture:** Python v2 allowlisted projection and bounded thread-safe activity feed read existing runtime state; React strictly parses and renders this data. The backend retains all canonical state and Authority.

**Tech Stack:** Python 3.11+/unittest; TypeScript/React 18/Vite/node:test; existing localhost `ThreadingHTTPServer`.

**Spec:** `docs/superpowers/specs/2026-10-26-contextual-hybrid-hud-design.md`

**Execution record (26 October 2026):** All four scoped, read-only projection,
observer, React and bundle tasks have been implemented and tested on this Linux
checkout. Verification: 26 HUD Python unittests, both frontend Node test files,
TypeScript typecheck, Vite build, Python compilation and git diff check passed.
`pytest` and browser/Windows hardware acceptance are unavailable in this
execution environment. The separate authenticated action-command/owner-approval
gateway is explicitly outside this bounded read-only delivery and requires
owner Windows security acceptance before implementation.

## Global Constraints

- No new microphone, task/work store, model inference or permission paths.
- No private text, memory, query, result body, secrets or raw log fields in public API.
- The HTTP server remains localhost-only, GET/HEAD-only and defensive against forged Origin/Host.
- Voice offline does not erase independently available Work/health data; preview remains unlinked.
- The production bundle in `src/jarvis/ui/assets` must match the frontend source.

## Review Focus

1. Source observer receives maliciously long/private fields → public payload contains only fixed labels and bounded metadata (Task 2 tests).
2. Voice off but durable Work active → task is still shown, not interpreted as disconnected (Tasks 1 and 3 tests).
3. Missing or failing optional provider/DB/vision adapters → UI remains valid and error-free (Task 1 tests).
4. Browser staleness/schema spoofing/unknown fields → client rejects, never fabricates activity (Task 3 tests).
5. HTTP POST and forged Origin still rejected, privacy payload never leaks (Task 4 tests).

---

### Task 1: V2 canonical snapshot projection

**Files:** Modify `src/jarvis/ui/hub.py`, `src/jarvis/ui/runtime.py`; tests `tests/test_hybrid_ui.py`.

**Interfaces:** `UISnapshotHub.snapshot() -> dict`; `build_runtime_hub(runtime, self_awareness, *, activity_feed=None)`; Work estimate via `jarvis.work.estimates.estimate_work(store, item)`.

- [ ] Write failing unittest cases: offline voice and active Work coexist; no leak of Work payload; model/provider/feature states validate; vision diagnostics stay sanitized; failing adapters degrade individually.
- [ ] Run `PYTHONPATH=src python -m unittest discover -s tests -p test_hybrid_ui.py -q` and verify expected failures.
- [ ] Implement schema v2 strict allowlists and independent telemetry status; reuse existing Work estimates and vision diagnostic state.
- [ ] Rerun same unittest suite to green, including HTTP tests with loopback socket permission.
- [ ] Commit as `feat(ui): project canonical operational state to hud v2`.

### Task 2: Bounded runtime activity observers

**Files:** Create `src/jarvis/ui/activity.py`; modify `src/jarvis/ui/runtime.py`, `src/jarvis/voice/production_runtime.py`, `src/jarvis/voice/canonical_active_speaker_runtime.py`; tests `tests/test_hybrid_ui.py`.

**Interfaces:** `HUDActivityFeed.record_capability(result)`; `record_research(payload)`; `observe_turn(turn)`; `snapshot() -> list[dict]`; `CanonicalActiveSpeakerRuntimeController(..., hud_turn_observer=None)`.

- [ ] Write failing feed tests asserting finite event labels, kind/state, lock safety, ordering and non-disclosure of sensitive text.
- [ ] Run tests and verify missing feed fails.
- [ ] Implement bounded observer; connect at production capability observer, research observer and per-conversation bridge. Only attach to optional UI feed if HUD is enabled.
- [ ] Run feed/runtime unittests to green; no optional observer may interrupt canonical operations.
- [ ] Commit as `feat(ui): observe sanitized voice research and capability activity`.

### Task 3: Contextual React projection

**Files:** Modify `frontend/jarvis-hud/src/hudState.ts`, `frontend/jarvis-hud/src/hudState.test.ts`, `frontend/jarvis-hud/src/App.tsx`, `frontend/jarvis-hud/src/styles.css`.

**Interfaces:** `parseSnapshot(data: unknown): HudState` implements schema v2; `App` renders only validated fields and retains focus/low-GPU toggles.

- [ ] Write failing `hudState.test.ts` cases for v2 limits, independent voice/transport, events, features, and invalid/private keys.
- [ ] Run `npm test` and verify expected failures.
- [ ] Implement strict parser and contextual UI: real Work estimate, owner-attention, model and vision metadata, capability status, activity timeline; keep reactor and fallback.
- [ ] Run `npm test`, `npm run typecheck` and `npm run build` to green.
- [ ] Commit as `feat(ui): render contextual missions activity and diagnostics`.

### Task 4: Bundle, verify and document

**Files:** Update `src/jarvis/ui/assets/` via Vite build and `docs/CURRENT_ARCHITECTURE.md` with v2 security and operator guide; modify tests if needed.

**Interfaces:** `python -m jarvis.ui` preview; `JARVIS_UI_ENABLED=1` runtime HUD.

- [ ] Write integration tests rejecting actions/secret input and proving proper v2 schema over HTTP; run red where behavior is missing.
- [ ] Complete bundle packaging, update docs for actual enablement and feature flags, outline gated future command bridge.
- [ ] Verify Python `unittest` HUD suite, Node tests, TypeScript typecheck, Vite build and available broader regressions.
- [ ] Self-review diff for security, canonical ownership, performance and untested failure paths.
- [ ] Commit as `docs(ui): document and verify contextual hybrid integration`.
